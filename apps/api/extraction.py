"""Bounded local document parsing, OCR and exact source quotation validation."""
from __future__ import annotations

from functools import lru_cache
import hashlib
from importlib import metadata
import base64
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

PARSER_VERSION = "pdfplumber-pdfium-tesseract-v1"
TEXT_MIMES = {"text/plain", "text/markdown"}
SUPPORTED_MIMES = TEXT_MIMES | {"application/pdf", "image/png", "image/jpeg"}


@lru_cache(maxsize=1)
def _parser_libraries() -> dict[str, str]:
    versions = {}
    for package in ("pdfplumber", "pdfminer.six", "pypdfium2", "pytesseract", "Pillow"):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = "unavailable"
    return versions


@lru_cache(maxsize=16)
def _tesseract_version(command: str) -> str:
    try:
        result = subprocess.run([command, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
        lines = (result.stdout or result.stderr).strip().splitlines()
        return lines[0] if result.returncode == 0 and lines else "unavailable:version_command_failed"
    except (OSError, subprocess.TimeoutExpired) as exc:
        # Text documents and text PDFs remain usable without an OCR executable.
        return "unavailable:" + type(exc).__name__


def parser_runtime_metadata() -> dict:
    command = os.getenv("TESSERACT_CMD", "tesseract")
    return {"parser_version": PARSER_VERSION, "libraries": dict(_parser_libraries()),
            "ocr_languages": os.getenv("OCR_LANGUAGES", "pol+eng"),
            "tesseract_command": command, "tesseract_version": _tesseract_version(command),
            "tessdata_prefix": os.getenv("TESSDATA_PREFIX", "")}


def parser_cache_key() -> str:
    signature = json.dumps(parser_runtime_metadata(), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return PARSER_VERSION + ":" + hashlib.sha256(signature.encode()).hexdigest()


class DocumentError(ValueError):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code, self.retryable = code, retryable


def detect_mime(path: str | Path, mime: str | None = None, max_mb: int | None = None) -> str:
    file = Path(path)
    limit = (max_mb or int(os.getenv("MAX_UPLOAD_MB", "20"))) * 1024 * 1024
    if not file.is_file() or file.stat().st_size == 0:
        raise DocumentError("empty_file", "Plik jest pusty lub nie istnieje.")
    if file.stat().st_size > limit:
        raise DocumentError("file_too_large", f"Plik przekracza limit {limit // 1024 // 1024} MB.")
    with file.open("rb") as stream:
        head = stream.read(4096)
    supplied = (mime or "").split(";")[0].strip().lower()
    if supplied == "image/jpg":
        supplied = "image/jpeg"
    if head.startswith(b"%PDF-"):
        detected = "application/pdf"
    elif head.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = "image/png"
    elif head.startswith(b"\xff\xd8\xff"):
        detected = "image/jpeg"
    else:
        try:
            # UTF-8 is deliberate: silently guessing an encoding corrupts evidence.
            content = file.read_bytes().decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentError("unsupported_file", "Obsługiwane są PDF, PNG, JPEG i tekst UTF-8.") from exc
        if "\x00" in content or sum(ord(c) < 32 and c not in "\t\r\n\f" for c in content) > 0:
            raise DocumentError("unsupported_file", "Plik zawiera binarne dane zamiast tekstu.")
        detected = "text/markdown" if supplied == "text/markdown" or file.suffix.lower() == ".md" else "text/plain"
    if supplied and supplied != "application/octet-stream" and supplied not in SUPPORTED_MIMES:
        raise DocumentError("unsupported_mime", "Ten typ pliku nie jest obsługiwany.")
    if supplied and supplied != "application/octet-stream" and supplied != detected and not {supplied, detected} <= TEXT_MIMES:
        raise DocumentError("mime_mismatch", "Zawartość pliku nie odpowiada zadeklarowanemu typowi.")
    return detected


def _page(number: int, source_id: str, text: str, width: float, height: float, method: str, blocks: list, issues: list | None = None) -> dict:
    problems = issues or []
    cursor = 0
    for block in blocks:
        start = text.find(block["text"], cursor)
        if start >= 0:
            block["start"], block["end"] = start, start+len(block["text"])
            cursor = block["end"]
    if not text.strip():
        problems.append("no_readable_text")
    return {"number": number, "source_id": source_id, "text": text, "width": width, "height": height,
            "method": method, "status": "read" if not problems else "needs_review", "blocks": blocks, "issues": problems}


def _ocr(image, number: int, source_id: str, width: float | None = None, height: float | None = None) -> dict:
    import pytesseract
    from pytesseract import Output
    if image.width * image.height > 30_000_000:
        raise DocumentError("image_too_large", "Obraz przekracza limit 30 milionów pikseli.")
    pytesseract.pytesseract.tesseract_cmd = os.getenv("TESSERACT_CMD", "tesseract")
    languages = os.getenv("OCR_LANGUAGES", "pol+eng")
    try:
        available = set(pytesseract.get_languages(config=""))
        missing = set(languages.split("+")) - available
        if missing:
            return _page(number, source_id, "", width or image.width, height or image.height, "ocr", [], ["ocr_language_missing:" + ",".join(sorted(missing))])
        result = pytesseract.image_to_data(image, lang=languages, output_type=Output.DICT,
                                         config="--psm 3", timeout=int(os.getenv("OCR_PAGE_TIMEOUT_SECONDS", "25")))
    except (RuntimeError, pytesseract.TesseractNotFoundError) as exc:
        return _page(number, source_id, "", width or image.width, height or image.height, "ocr", [], ["ocr_failed:" + type(exc).__name__])
    lines: dict[tuple, list] = {}
    confidences = []
    sx, sy = (width or image.width) / image.width, (height or image.height) / image.height
    for index, word in enumerate(result["text"]):
        if not word.strip():
            continue
        key = (result["block_num"][index], result["par_num"][index], result["line_num"][index])
        x, y, w, h = (result[field][index] for field in ("left", "top", "width", "height"))
        lines.setdefault(key, []).append({"text": word, "bbox": [x*sx, y*sy, (x+w)*sx, (y+h)*sy]})
        confidences.append(float(result["conf"][index]))
    blocks = []
    for words in lines.values():
        blocks.append({"text": " ".join(word["text"] for word in words), "bbox": [min(w["bbox"][0] for w in words), min(w["bbox"][1] for w in words), max(w["bbox"][2] for w in words), max(w["bbox"][3] for w in words)]})
    issues = ["low_ocr_confidence"] if confidences and sum(confidences)/len(confidences) < 65 else []
    page = _page(number, source_id, "\n".join(block["text"] for block in blocks), width or image.width, height or image.height, "ocr", blocks, issues)
    page["ocr_languages"] = languages
    page["ocr_mean_confidence"] = round(sum(confidences)/len(confidences), 2) if confidences else None
    # Private inline preview supports multimodal interpretation; evidence still must
    # match the locally extracted OCR text and carries its original coordinates.
    preview = image.copy().convert("RGB")
    preview.thumbnail((1800, 1800))
    buffer = io.BytesIO()
    preview.save(buffer, format="JPEG", quality=85)
    page["source_image"] = {"mime_type": "image/jpeg", "data": base64.b64encode(buffer.getvalue()).decode("ascii")}
    return page


def _parse_local(path: str | Path, mime: str, source_id: str, max_pages: int) -> dict:
    import PIL.Image
    PIL.Image.MAX_IMAGE_PIXELS = 30_000_000
    file = Path(path)
    pages = []
    if mime in TEXT_MIMES:
        texts = file.read_text(encoding="utf-8-sig").split("\f")
        if len(texts) > max_pages:
            raise DocumentError("too_many_pages", f"Dokument przekracza limit {max_pages} stron.")
        for index, text in enumerate(texts, 1):
            blocks = [{"text": line, "bbox": [0, n*18, 1000, (n+1)*18]} for n, line in enumerate(text.splitlines())]
            pages.append(_page(index, source_id, text, 1000, max(18, len(blocks)*18), "text", blocks))
    elif mime in {"image/png", "image/jpeg"}:
        from PIL import Image, ImageOps
        with Image.open(file) as opened:
            if opened.width * opened.height > 30_000_000:
                raise DocumentError("image_too_large", "Obraz przekracza limit 30 milionów pikseli.")
            if getattr(opened, "n_frames", 1) != 1:
                raise DocumentError("animated_image", "Obraz ma wiele klatek. Wczytaj statyczny PNG lub JPEG.")
            pages.append(_ocr(ImageOps.exif_transpose(opened).convert("RGB"), 1, source_id))
    else:
        import pdfplumber
        import pypdfium2 as pdfium
        try:
            with pdfplumber.open(file) as document:
                if len(document.pages) > max_pages:
                    raise DocumentError("too_many_pages", f"Dokument przekracza limit {max_pages} stron.")
                if not document.pages:
                    raise DocumentError("empty_pdf", "PDF nie zawiera stron.")
                render_doc = None
                try:
                    for index, page in enumerate(document.pages, 1):
                        try:
                            text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
                            words = page.extract_words()
                            blocks = [{"text": word["text"], "bbox": [word["x0"], word["top"], word["x1"], word["bottom"]]} for word in words]
                            # Pages with text plus an image can contain an unread scanned annex.
                            large_image = any(abs(img.get("width", 0)*img.get("height", 0)) > page.width*page.height*.20 for img in page.images)
                            if len(text.strip()) < 30 or large_image:
                                if render_doc is None:
                                    render_doc = pdfium.PdfDocument(str(file))
                                render_page = render_doc[index-1]
                                scale = min(2.5, (30_000_000/max(1, page.width*page.height))**.5)
                                bitmap = render_page.render(scale=scale)
                                try:
                                    ocr_page = _ocr(bitmap.to_pil(), index, source_id, page.width, page.height)
                                finally:
                                    bitmap.close()
                                    render_page.close()
                                if text.strip() and not ocr_page["text"].strip():
                                    ocr_page = _page(index, source_id, text, page.width, page.height, "pdf_text_partial", blocks, ocr_page["issues"])
                                pages.append(ocr_page)
                            else:
                                pages.append(_page(index, source_id, text, page.width, page.height, "pdf_text", blocks))
                        except Exception as exc:
                            pages.append(_page(index, source_id, "", page.width, page.height, "failed", [], ["page_read_failed:" + type(exc).__name__]))
                finally:
                    if render_doc is not None:
                        render_doc.close()
        except DocumentError:
            raise
        except Exception as exc:
            raise DocumentError("invalid_pdf", "PDF jest uszkodzony, zaszyfrowany lub nie można go odczytać.") from exc
    return {"source_id": source_id, "sha256": hashlib.sha256(file.read_bytes()).hexdigest(), "mime": mime,
            "parser_version": PARSER_VERSION, "pages": pages, "complete": bool(pages) and all(p["status"] == "read" for p in pages),
            "issues": [{"page": p["number"], "code": issue} for p in pages for issue in p["issues"]]}


def parse_document(path: str | Path, mime: str | None = None, source_id: str = "source", *, max_pages: int | None = None, timeout: int | None = None) -> dict:
    """Run parsers outside the API process, enforcing wall-clock and page limits."""
    detected = detect_mime(path, mime)
    max_pages = max_pages or int(os.getenv("MAX_DOCUMENT_PAGES", "100"))
    started = time.monotonic()
    command = [sys.executable, "-m", "apps.api.extraction", "--worker", str(Path(path).resolve()), detected, source_id, str(max_pages)]
    try:
        process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=timeout or int(os.getenv("PARSER_TIMEOUT_SECONDS", "120")), cwd=Path(__file__).resolve().parents[2])
    except subprocess.TimeoutExpired as exc:
        raise DocumentError("parser_timeout", "Przekroczono limit odczytu dokumentu. Podziel dokument lub zwiększ jawny limit.") from exc
    try:
        result = json.loads(process.stdout)
    except (ValueError, TypeError) as exc:
        raise DocumentError("parser_failed", "Proces odczytu dokumentu zakończył się błędem.") from exc
    if "error" in result:
        raise DocumentError(result["error"]["code"], result["error"]["message"])
    result["parser_fingerprint"] = parser_cache_key()
    result["parser_runtime"] = parser_runtime_metadata()
    result["elapsed_seconds"] = round(time.monotonic()-started, 3)
    return result


def _normalized_with_offsets(text: str) -> tuple[str, list[int]]:
    chars, offsets = [], []
    for i, character in enumerate(text):
        if character.isspace():
            if chars and chars[-1] != " ":
                chars.append(" ")
                offsets.append(i)
        else:
            chars.append(character)
            offsets.append(i)
    return "".join(chars).strip(), offsets


def validate_citation(citation: dict, pages: list[dict]) -> dict:
    """Accept exact quotations, allowing only whitespace normalization."""
    page = next((page for page in pages if page["number"] == citation["page"] and page.get("source_id") == citation["source_id"]), None)
    if page is None:
        raise DocumentError("invalid_evidence", "Cytat wskazuje nieistniejącą stronę źródła.")
    quote = citation["quote"].strip()
    normalized, offsets = _normalized_with_offsets(page["text"])
    needle = re.sub(r"\s+", " ", quote)
    index = normalized.find(needle)
    if not needle or index < 0:
        raise DocumentError("invalid_evidence", "Cytat nie istnieje w odczytanym tekście źródła.")
    start, end = offsets[index], offsets[index+len(needle)-1]+1
    hits = [block for block in page.get("blocks", []) if block.get("start", -1) < end and block.get("end", -1) > start]
    bbox = [min(b["bbox"][0] for b in hits), min(b["bbox"][1] for b in hits), max(b["bbox"][2] for b in hits), max(b["bbox"][3] for b in hits)] if hits else None
    return {**citation, "quote": page["text"][start:end], "quote_validated": True, "start": start, "end": end, "bbox": bbox, "method": page["method"]}


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "--worker":
        if os.name != "nt":
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))
            resource.setrlimit(resource.RLIMIT_CPU, (100, 100))
        try:
            output = _parse_local(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]))
        except DocumentError as error:
            output = {"error": {"code": error.code, "message": str(error)}}
        except Exception as error:
            output = {"error": {"code": "parser_failed", "message": "Parser failure: " + type(error).__name__}}
        print(json.dumps(output, ensure_ascii=True))
