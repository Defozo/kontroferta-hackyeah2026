"""Record and verify the published authored demo through real browser interactions."""
import json
import os
import shutil
import time
import functools
import http.server
import threading
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

URL = os.environ.get("DEMO_URL", "https://thorny-quasar-2wy3.here.now/")
if os.environ.get("LOCAL_STATIC_DIR"):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 9090), functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=os.environ["LOCAL_STATIC_DIR"]))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    URL = "http://127.0.0.1:9090/"
OUT = Path(os.environ.get("EVIDENCE_DIR", "/evidence"))
OUT.mkdir(parents=True, exist_ok=True)
report = {"url": URL, "publicRecordedOnly": True, "mouseSteps": [], "keyboard": {}}

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
    context = browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True,
                                  record_video_dir="/tmp/demo-recording", record_video_size={"width": 1280, "height": 900})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(URL, wait_until="networkidle")
    expect(page.locator(".comparison-table")).to_be_visible()
    start = time.monotonic()

    def step(name, pause=2):
        report["mouseSteps"].append({"seconds": round(time.monotonic() - start, 1), "step": name})
        page.wait_for_timeout(pause * 1000)

    step("Zapisany publiczny przykład i wymagania")
    page.locator(".comparison-table").evaluate("e=>window.scrollTo({top:e.getBoundingClientRect().top+scrollY-100,behavior:'smooth'})")
    step("Pełne koszty A/B/C, wykonalność i przyczyna wykluczenia C", 3)
    page.get_by_role("button", name="Otwórz dowód: Oferta A · Fala Audio, technician", exact=True).click()
    expect(page.locator(".pdf-preview canvas")).to_be_visible()
    step("Cytat i oryginalny PDF aneksu A o techniku", 4)
    page.get_by_role("button", name="Zamknij", exact=True).click()
    page.get_by_role("tab", name="Pytania", exact=True).click()
    page.locator(".question-detail").evaluate("e=>e.scrollIntoView({block:'center',behavior:'smooth'})")
    step("Pytanie, uzasadnienie oraz dwa scenariusze zmieniające zwycięzcę", 4)
    page.locator(".explorer").evaluate("e=>window.scrollTo({top:e.getBoundingClientRect().top+scrollY-100,behavior:'smooth'})")
    for value, winner in [("0", "A"), ("700", "A, B"), ("1200", "B")]:
        page.get_by_label("Dokładna dopłata", exact=True).fill(value)
        page.get_by_role("button", name="Przelicz scenariusz", exact=True).click()
        expect(page.locator(".scenario-result > strong")).to_have_text(winner)
        expect(page.locator(".scenario-result tbody th").nth(1)).to_have_text("Pracownia Dźwięku")
        step(f"Dopłata {value} PLN, najtańszy wybór: {winner}", 4)
    page.get_by_role("tab", name="Decyzja i raport", exact=True).click()
    page.locator(".export-card").evaluate("e=>e.scrollIntoView({block:'center',behavior:'smooth'})")
    step("Raport zapisanej wersji z oznaczeniem stanu", 3)
    with page.expect_download() as download_event:
        page.get_by_role("link", name="PDF", exact=True).click()
    download = download_event.value
    assert download.failure() is None, download.failure()
    download.save_as(OUT / "walkthrough-report.pdf")
    assert (OUT / "walkthrough-report.pdf").read_bytes().startswith(b"%PDF")
    step("PDF pobrany przez widoczny przycisk eksportu", 2)
    with page.expect_download() as download_event:
        page.get_by_role("link", name="JSON", exact=True).click()
    download_event.value.save_as(OUT / "public-downloaded-report.json")
    json.loads((OUT / "public-downloaded-report.json").read_text())
    report["mouseErrors"] = errors
    report["downloadedPdfBytes"] = (OUT / "walkthrough-report.pdf").stat().st_size
    video = page.video
    context.close()
    shutil.copyfile(video.path(), OUT / "walkthrough.webm")
    (OUT / "public-browser-flow.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Recorded flow and actual PDF/JSON downloads passed", flush=True)

    context = browser.new_context(viewport={"width": 1440, "height": 1100}, accept_downloads=True)
    page = context.new_page()
    page.goto(URL, wait_until="networkidle")
    expect(page.locator(".comparison-table")).to_be_visible()

    def focus_state():
        return page.evaluate("""() => {const e=document.activeElement;return {tag:e.tagName,
          role:e.getAttribute('role'),label:e.getAttribute('aria-label'),text:e.textContent,
          type:e.getAttribute('type'),href:e.getAttribute('href'),insideDialog:!!e.closest('[role=dialog]')}}""")

    def tab_until(predicate, backwards=False, limit=60):
        for count in range(limit):
            state = focus_state()
            if predicate(state):
                return count
            page.keyboard.press("Shift+Tab" if backwards else "Tab")
        raise AssertionError(f"Keyboard target not reached: {focus_state()}")

    source_label = "Otwórz dowód: Oferta A · Fala Audio, technician"
    report["keyboard"]["tabsToSource"] = tab_until(lambda s: s["label"] == source_label)
    page.keyboard.press("Enter")
    expect(page.get_by_role("dialog")).to_be_visible()
    report["keyboard"]["tabsToQuote"] = tab_until(lambda s: s["tag"] == "BLOCKQUOTE", limit=15)
    quote = page.locator("blockquote")
    before = quote.evaluate("e=>({top:e.scrollTop,height:e.clientHeight,total:e.scrollHeight})")
    page.keyboard.press("PageDown")
    page.wait_for_timeout(300)
    after = quote.evaluate("e=>e.scrollTop")
    assert before["total"] <= before["height"] or after > before["top"]
    report["keyboard"]["quoteScroll"] = {"before": before, "after": after}
    page.screenshot(path=OUT / "keyboard-source-focus.png")
    for _ in range(18):
        page.keyboard.press("Tab")
        assert focus_state()["insideDialog"], "Focus escaped the modal"
    report["keyboard"]["focusTrapTabs"] = 18
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).not_to_be_visible()
    expect(page.get_by_role("button", name=source_label, exact=True)).to_be_focused()
    report["keyboard"]["escapeRestoresTrigger"] = True
    tab_until(lambda s: s["role"] == "tab", backwards=True)
    page.keyboard.press("ArrowRight")
    expect(page.get_by_role("tab", name="Pytania", exact=True)).to_have_attribute("aria-selected", "true")
    tab_until(lambda s: s["tag"] == "INPUT" and s["type"] == "number")
    page.keyboard.press("Control+A")
    page.keyboard.type("700")
    page.keyboard.press("Tab")
    assert "Przelicz scenariusz" in focus_state()["text"]
    page.keyboard.press("Enter")
    expect(page.locator(".scenario-result > strong")).to_have_text("A, B")
    report["keyboard"]["typed700Result"] = "A, B"
    tab_until(lambda s: s["role"] == "tab", backwards=True)
    for _ in range(3):
        page.keyboard.press("ArrowRight")
    expect(page.get_by_role("tab", name="Decyzja i raport", exact=True)).to_have_attribute("aria-selected", "true")
    tab_until(lambda s: s["href"] == "/demo-report.pdf")
    with page.expect_download() as download_event:
        page.keyboard.press("Enter")
    assert download_event.value.failure() is None
    download_event.value.save_as(OUT / "keyboard-report.pdf")
    report["keyboard"]["exportPdf"] = (OUT / "keyboard-report.pdf").read_bytes().startswith(b"%PDF")
    report["keyboard"]["status"] = "passed"
    report["limitations"] = ["Keyboard test covers the public recorded flow; no screen-reader audit or complete private-form keyboard audit.",
                              "Automated axe reports are separate and are not a complete WCAG conformance certification."]
    context.close()
    browser.close()
    (OUT / "public-browser-flow.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
