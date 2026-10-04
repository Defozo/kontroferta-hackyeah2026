"""Rebuild the explicitly fictional evidence set; no customer data or external assets."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parent
DATE = "2026-10-10"
COMMON = "Termin wydarzenia: 10.10.2026. Strefa: Europe/Warsaw (UTC+02:00).\nPotwierdzamy odpowiedniość oferowanego nagłośnienia dla konferencji 120 osób.\nW zestawie są 4 mikrofony bezprzewodowe.\nTechnik jest dostępny i obecny przez cały okres 09:00-17:00."
DOCUMENTS = {
    "A-offer": "OFERTA A | Fala Audio\nDokument fikcyjny do demonstracji. Autor: Fala Audio, dział ofert. Data: 03.10.2026.\n"+COMMON+"\nGotowość sprzętu: 10.10.2026 o 08:30.\nZestaw nagłośnienia i obsługa wydarzenia: 4200 PLN brutto.\nTransport: 600 PLN brutto. Łącznie: 4800 PLN brutto.\nOkreślenie obsługa wydarzenia wymaga wyjaśnienia w świetle aneksu A-1.\nDostępność technika przez 09:00-17:00 jest gwarantowana w obu odczytaniach ceny.\nOferta nie zawiera innych opłat za wskazany zakres.",
    "A-annex": "ANEKS A-1 DO OFERTY A | Fala Audio\nDokument fikcyjny do demonstracji. Data: 03.10.2026.\nDotyczy wyłącznie oferty A na konferencję 120 osób 10.10.2026.\nPozycja cennika: technik przez 09:00-17:00: 1200 PLN brutto.\nNie wskazano jednoznacznie, czy pozycja jest zawarta w kwocie 4800 PLN brutto.\nDwa opisane warianty interpretacji: technik w cenie (dopłata 0 PLN brutto) albo technik dodatkowo (dopłata 1200 PLN brutto).\nOba warianty zapewniają obecność technika przez pełne 09:00-17:00.\nTo zakres dwóch interpretacji dokumentu, nie zamknięta lista przyszłych odpowiedzi wykonawcy.\nPowiązanie aneksu i wybór interpretacji musi potwierdzić organizator.",
    "B-offer": "OFERTA B | Pracownia Dźwięku\nDokument fikcyjny do demonstracji. Autor: Pracownia Dźwięku. Data: 03.10.2026.\n"+COMMON+"\nGotowość sprzętu: 10.10.2026 o 08:30.\nPełna cena usługi: 5500 PLN brutto.\nCena obejmuje nagłośnienie, 4 mikrofony, transport i technika przez 09:00-17:00.\nBrak dodatkowych opłat za ten zakres.",
    "C-offer": "OFERTA C | Sygnał Studio\nDokument fikcyjny do demonstracji. Autor: Sygnał Studio. Data: 03.10.2026.\n"+COMMON+"\nGotowość sprzętu: 10.10.2026 o 09:30. Nie możemy zapewnić gotowości przed 09:00.\nPełna cena usługi: 5100 PLN brutto.\nCena obejmuje transport i technika przez pełne 09:00-17:00.\nBrak dodatkowych opłat za ten zakres.",
    "A-answer-included": "ODPOWIEDŹ WYKONAWCY A\nFikcyjna odpowiedź z 03.10.2026 do oferty A oraz aneksu A-1.\nPotwierdzamy: 4800 PLN brutto obejmuje zestaw, transport i obecność technika 10.10.2026 przez 09:00-17:00.\nDopłata za technika wynosi 0 PLN brutto. Pozycja 1200 PLN brutto z aneksu A-1 jest częścią ceny pakietu, nie dodatkową opłatą.\nPozostałe parametry oferty A pozostają bez zmian.",
    "A-answer-surcharge": "ODPOWIEDŹ WYKONAWCY A\nFikcyjna odpowiedź z 03.10.2026 do oferty A oraz aneksu A-1.\nPotwierdzamy dopłatę 1200 PLN brutto za obecność technika 10.10.2026 przez 09:00-17:00.\nOstateczna pełna cena usługi, z zestawem i transportem, wynosi 6000 PLN brutto.\nKwota 4800 PLN brutto z oferty A nie zawierała technika.\nPozostałe parametry oferty A pozostają bez zmian.",
}


def make_pdf(path: Path, text: str):
    font_paths = [Path("C:/Windows/Fonts/arial.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    found = next((p for p in font_paths if p.exists()), None)
    if not found:
        raise RuntimeError("A Unicode font is required to preserve Polish evidence")
    if "EvidenceSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("EvidenceSans", str(found)))
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="EvidenceBody", fontName="EvidenceSans", fontSize=11, leading=17, textColor=colors.HexColor("#122642"), spaceAfter=11))
    styles.add(ParagraphStyle(name="EvidenceTitle", parent=styles["EvidenceBody"], fontSize=21, leading=28, spaceAfter=25))
    lines = text.splitlines()
    story = [Paragraph(lines[0], styles["EvidenceTitle"])]
    story.extend(Paragraph(line, styles["EvidenceBody"]) for line in lines[1:])
    def footer(canvas, document):
        canvas.setFont("EvidenceSans", 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(44, 28, "KontrOferta | wyłącznie dane syntetyczne | źródło demonstracyjne")
        canvas.drawRightString(A4[0]-44, 28, str(document.page))
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=44, rightMargin=44, topMargin=45, bottomMargin=55).build(story, onFirstPage=footer, onLaterPages=footer)


def build():
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, text in DOCUMENTS.items():
        (ROOT/(name+".txt")).write_text(text+"\n", encoding="utf-8")
        make_pdf(ROOT/(name+".pdf"), text)
    document = pdfium.PdfDocument(str(ROOT/"B-offer.pdf"))
    page = document[0]
    bitmap = page.render(scale=2.25)
    image = bitmap.to_pil().convert("RGB")
    image.save(ROOT/"B-scanned.png")
    image.save(ROOT/"B-scanned.jpg", quality=88)
    image.save(ROOT/"B-scanned.pdf", "PDF", resolution=162)
    bitmap.close()
    page.close()
    document.close()
    files = [{"file": file.name, "sha256": hashlib.sha256(file.read_bytes()).hexdigest(), "synthetic": True} for file in sorted(ROOT.iterdir()) if file.suffix in {".txt", ".pdf", ".png", ".jpg"}]
    (ROOT/"manifest.json").write_text(json.dumps({"version": "1.0", "generated_from": "build_fixtures.py", "event_date": DATE, "timezone": "Europe/Warsaw", "files": files, "warning": "Synthetic demonstration. No real supplier or offer. Annex relationship and critical fields require explicit user review."}, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    build()
