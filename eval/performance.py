"""Real repeated three-offer/five-page PDF pipeline timing, without application cache."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.api.ai import extract_offer, AIError
from apps.api.extraction import parse_document, DocumentError
from packages.domain import demo_model, evaluate


def build():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, PageBreak, Spacer
    import pypdfium2 as pdfium
    import pdfplumber
    folder = ROOT/"eval/performance-inputs"
    folder.mkdir(parents=True, exist_ok=True)
    path = next(path for path in (Path("C:/Windows/Fonts/arial.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")) if path.exists())
    pdfmetrics.registerFont(TTFont("PerfSans", str(path)))
    body = ParagraphStyle("body", fontName="PerfSans", fontSize=10.5, leading=16, spaceAfter=15)
    title = ParagraphStyle("title", parent=body, fontSize=21, leading=28, spaceAfter=25)
    manifest = []
    for identifier, price, readiness in (("A", 4800, "08:30"), ("B", 5500, "08:30"), ("C", 5100, "09:30")):
        pages = [
            ("Zakres konferencji", [
                f"Oferta {identifier}. Dokument syntetyczny przeznaczony do pomiaru wydajności. Wydarzenie: 10.10.2026. Strefa Europe/Warsaw, UTC+02:00. Autor: fikcyjny wykonawca {identifier}. Data dokumentu: 03.10.2026.",
                "Potwierdzamy, że oferowany zestaw nagłośnienia jest odpowiedni dla konferencji 120 osób. Zakres obejmuje salę konferencyjną, mowę prowadzącego i wypowiedzi uczestników. W zestawie są 4 mikrofony bezprzewodowe. Potwierdzenie dotyczy całej opisanej konferencji i pełnego okresu pracy określonego na stronie harmonogramu.",
                "Zespół wykonawcy przygotowuje urządzenia, przeprowadza sprawdzenie sygnału i zapewnia bieżącą obsługę. Zamówienie obejmuje kompletną usługę, a nie sam wynajem urządzeń. Wskazany komplet jest jedną ofertą dla jednego wydarzenia. Opis wyposażenia na kolejnej stronie rozwija ten sam zakres i nie stanowi odrębnego pakietu do zakupu.",
                "Materiały służą porównaniu trzech fikcyjnych wykonawców. Organizator wymaga gotowości do 09:00 i technika od 09:00 do 17:00. Własne zobowiązania wykonawcy co do godzin gotowości i obecności technika zapisano na stronie trzeciej. Wymaganie organizatora nie zastępuje tego oświadczenia wykonawcy."
            ]),
            ("Wyposażenie i sposób obsługi", [
                "Nagłośnienie obejmuje urządzenia głośnikowe, mikser, mikrofony, odbiorniki bezprzewodowe, statywy i przewody potrzebne do pracy zestawu. Każdy z tych elementów należy do zakresu usługi. Nie ma odrębnych opłat za wymienione wyposażenie. Opis techniczny wyjaśnia sposób realizacji, bez wprowadzania dodatkowych wariantów ceny.",
                "Mikrofony będą przygotowane do przekazywania między prowadzącym i osobami zabierającymi głos. Technik odpowiada za sprawdzenie łączności, poziomy sygnału oraz reakcję na zakłócenia. Rezerwowe materiały eksploatacyjne są częścią zaplecza wykonawcy. Organizator nie kupuje osobno baterii ani przewodów potrzebnych do wykonania wskazanego zakresu.",
                "Ustawienie sprzętu uwzględnia widoczność prezentera i utrzymanie przejść. Obsługa porządkuje przewody oraz zabezpiecza stanowisko przed przypadkowym rozłączeniem. Po sprawdzeniu sygnału zestaw pozostaje przygotowany do rozpoczęcia konferencji. Ostateczną godzinę takiej gotowości określono jednoznacznie w harmonogramie.",
                "Ten dokument nie oferuje ekranu LED, dodatkowej sceny ani transmisji internetowej. Te elementy nie są wymagane w analizowanym zamówieniu. Opis nie stanowi zapewnienia dotyczącego innych sal lub większych wydarzeń. Potwierdzony zakres dotyczy wyłącznie konferencji wskazanej na pierwszej stronie."
            ]),
            ("Harmonogram i odpowiedzialność", [
                f"Gotowość całego sprzętu: 10.10.2026 o {readiness}, Europe/Warsaw (UTC+02:00). To wiążąca godzina gotowości wykonawcy dla tego dokumentu.",
                "Technik jest dostępny i obecny przez cały okres 10.10.2026 od 09:00 do 17:00, Europe/Warsaw (UTC+02:00). Cały wskazany okres pracy technika jest objęty pełną ceną usługi. W razie przerwy w obradach technik pozostaje na miejscu i nadal odpowiada za działanie zestawu.",
                "Przygotowanie stanowiska obejmuje rozłożenie i podłączenie urządzeń oraz sprawdzenie toru dźwiękowego. Wykonawca organizuje transport i czynności przygotowawcze we własnym zakresie. Organizator nie musi samodzielnie odbierać sprzętu ani konfigurować połączeń. Obsługa obejmuje również uporządkowanie wyposażenia po zakończeniu pracy.",
                "Wymaganie organizatora dotyczące gotowości do 09:00 nie jest automatycznym potwierdzeniem jego spełnienia. Przy porównaniu należy użyć własnej godziny wykonawcy zapisanej powyżej. Godziny nie są orientacyjnym przedziałem ani datą względną. Dokument wskazuje konkretny dzień i strefę, nie posługuje się określeniem jutro."
            ]),
            ("Pełna cena usługi", [
                f"Ostateczna pełna cena usługi: {price} PLN brutto. Cena dotyczy całego opisanego zakresu konferencji i wszystkich stron tego dokumentu.",
                "Cena obejmuje nagłośnienie, mikrofony bezprzewodowe, transport, przygotowanie zestawu i obecność technika przez cały wskazany okres pracy. Nie dolicza się osobnej kwoty za dojazd, uruchomienie ani demontaż. Wskazane składniki są zawarte w pełnej cenie, a nie kolejnymi pozycjami do jej zwiększania.",
                "Nie jest wymagana dodatkowa kaucja. Dokument nie określa odrębnej opłaty za anulowanie. Harmonogram płatności pozostaje kwestią organizacyjną i nie zmienia pełnej ceny wykonanej usługi. Nie należy tworzyć dodatkowego kosztu z samego faktu, że płatność może nastąpić w innym terminie niż realizacja.",
                "Kwota jest wyrażona w polskich złotych i jest kwotą brutto. Nie jest potrzebne założenie dotyczące kursu walut do porównania z budżetem w PLN. Nie podajemy stawki podatku, ponieważ wskazana pełna kwota brutto jest wystarczająca do porównania tego zamówienia."
            ]),
            ("Potwierdzenie spójności zakresu", [
                "Wszystkie strony należą do tej samej oferty i dotyczą tego samego wykonawcy, wydarzenia oraz zestawu. Nie ma dodatkowego aneksu ani cennika, który należałoby dopiero dostarczyć. Opisy organizacyjne rozwijają zakres, ale nie zmieniają ceny ani godzin określonych na wcześniejszych stronach.",
                "Wykonawca potwierdza, że technik ma zapewnione zasoby potrzebne do obsługi opisanego wydarzenia. Zestaw jest kompletny w zakresie zadeklarowanym na pierwszej stronie. Potwierdzenie nie zwalnia organizatora z porównania deklaracji różnych wykonawców z własnym terminem, budżetem i zamówionym zakresem.",
                "Przy rozliczeniu tej usługi należy brać pod uwagę pojedynczą pełną cenę ze strony dotyczącej kosztu. Elementów zawartych w pakiecie nie należy naliczać po raz kolejny. Opis dotyczy usługi wykonywanej zgodnie z zamówieniem, nie kosztu zakupu sprzętu na własność ani kolejnego wydarzenia.",
                "Dokument jest fikcyjny. Nie stanowi oferty rynkowej ani potwierdzenia dostępności realnego wykonawcy. Jego celem jest sprawdzenie, czy aplikacja odczytuje wszystkie strony, oddziela wymagania od deklaracji, zachowuje źródła oraz porównuje koszty bez podwójnego naliczania."
            ]),
        ]
        story = []
        for number, (heading, paragraphs) in enumerate(pages, 1):
            story.extend([Paragraph(f"Oferta {identifier} / {heading}", title), Paragraph(f"Strona {number} z 5 | wyłącznie dane syntetyczne", body), Spacer(1, 8)])
            story.extend(Paragraph(paragraph, body) for paragraph in paragraphs)
            if number < 5:
                story.append(PageBreak())
        target = folder/(identifier+"-5-pages.pdf")
        SimpleDocTemplate(str(target), pagesize=A4, leftMargin=45, rightMargin=45, topMargin=40, bottomMargin=45).build(story)
        with pdfplumber.open(target) as doc:
            if len(doc.pages) != 5:
                raise RuntimeError("Unexpected page overflow")
            lengths = [len(page.extract_text() or "") for page in doc.pages]
        rendered = pdfium.PdfDocument(str(target))
        preview = folder/"previews"
        preview.mkdir(exist_ok=True)
        for i in range(len(rendered)):
            page = rendered[i]
            bitmap = page.render(scale=1)
            bitmap.to_pil().save(preview/(identifier+f"-{i+1}.png"))
            bitmap.close()
            page.close()
        rendered.close()
        manifest.append({"file": target.name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "pages": 5, "characters_by_page": lengths, "synthetic": True})
    (folder/"manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"created": manifest}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--output", default="eval/results/performance-v6")
    args = parser.parse_args()
    if args.build:
        build()
    if not args.live:
        return
    output = ROOT/args.output
    output.mkdir(parents=True, exist_ok=True)
    inputs = json.loads((ROOT/"eval/performance-inputs/manifest.json").read_text(encoding="utf-8"))
    requirements = {**demo_model()["requirements"], "timezone": "Europe/Warsaw"}
    batches = []
    for repetition in range(1, args.repetitions+1):
        started = time.monotonic()
        def run(item):
            source = ROOT/"eval/performance-inputs"/item["file"]
            if hashlib.sha256(source.read_bytes()).hexdigest() != item["sha256"]:
                raise RuntimeError("Performance source changed")
            offer_start = time.monotonic()
            try:
                parsed = parse_document(source, source_id=item["file"])
                value = {"extraction": extract_offer(parsed["pages"], requirements, offer_id=item["file"][0])}
            except (AIError, DocumentError) as exc:
                value = {"error": {"code": exc.code, "trace": getattr(exc, "trace", {})}}
            value["elapsed_seconds"] = round(time.monotonic()-offer_start, 3)
            (output/(f"batch-{repetition}-"+item["file"][0]+".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            return value
        with ThreadPoolExecutor(max_workers=2) as pool:
            predictions = list(pool.map(run, inputs))
        analysis = None
        if all("extraction" in value for value in predictions):
            model = demo_model()
            model["offers"] = [value["extraction"]["domain_offer"] for value in predictions]
            model["variables"] = [variable for value in predictions for variable in value["extraction"]["variables"]]
            model["issues"] = [{"code": "extraction_gap", "message": issue, "blocking": True} for value in predictions for issue in value["extraction"]["issues"]]
            analysis = evaluate(model)
        row = {"repetition": repetition, "seconds": round(time.monotonic()-started, 3), "errors": [value["error"]["code"] for value in predictions if "error" in value], "correct": bool(analysis and analysis["complete"] and analysis["unique_winner"] == "A"), "analysis": analysis}
        batches.append(row)
        print(json.dumps({key: value for key, value in row.items() if key != "analysis"}), flush=True)
    times = sorted(row["seconds"] for row in batches)
    report = {"run_at": datetime.now(timezone.utc).isoformat(), "scope": "parse + real AI + source validation + deterministic comparison of three five-page text PDFs", "cache": "application cache disabled; each repetition makes three provider calls", "concurrency": 2,
              "sample_size": len(batches), "median_seconds": statistics.median(times), "observed_p95_nearest_rank_seconds": times[max(0, int(len(times)*.95+.999)-1)], "min_seconds": min(times), "max_seconds": max(times),
              "observed_target_60_seconds_met": all(value <= 60 for value in times) and all(row["correct"] for row in batches), "batches": batches,
              "hardware": {"platform": platform.platform(), "python": platform.python_version(), "processor": platform.processor(),
                           "cgroup_cpu_max": Path("/sys/fs/cgroup/cpu.max").read_text().strip() if Path("/sys/fs/cgroup/cpu.max").exists() else None,
                           "cgroup_memory_max": Path("/sys/fs/cgroup/memory.max").read_text().strip() if Path("/sys/fs/cgroup/memory.max").exists() else None},
              "limitations": ["Small n does not establish a stable production p95.", "Synthetic text PDFs have clean layout; scans are measured separately in extraction corpus.", "HTTP upload, authentication, worker queue, persistence and UI rendering are not included.", "This workstation also had other workloads; CPU, disk and network were not isolated.", "First repetition includes cold parser/provider-client effects; all individual times are reported."], "inputs": inputs}
    (output/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("sample_size", "median_seconds", "observed_p95_nearest_rank_seconds", "observed_target_60_seconds_met")}), flush=True)


if __name__ == "__main__":
    main()
