from apps.api.reports import render_html


def snapshot(currency="PLN", minor_unit=2):
    return {"title": "Raport", "revision": 1, "decisions": [], "members": [],
            "model": {"currency": currency, "minor_unit": minor_unit, "offers": [], "variables": []},
            "requirements": {"budget_minor": 560000, "timezone": "Europe/Warsaw"},
            "analysis": None, "questions": [], "facts": [], "documents": [], "history": [],
            "export": {"at": "2026-10-03T14:00:00Z", "historical": False}}


def test_report_displays_major_currency_units_and_snapshot_timezone():
    html = render_html(snapshot())
    assert "5 600,00 PLN" in html
    assert "03.10.2026 16:00 +0200" in html
    assert "560000" not in html
    assert "560 000 JPY" in render_html(snapshot("JPY", 0))


def test_report_escapes_untrusted_document_content_and_marks_historical():
    data = snapshot()
    data["title"] = '<script>alert("document")</script>'
    data["export"]["historical"] = True
    data["facts"] = [{"key": "note", "value": "<img src=x onerror=alert(1)>",
                      "origin": "document", "confirmation": "unconfirmed", "evidence": [
                          {"source_id": "s1", "page": 1, "quote": "<script>bad()</script>", "quote_validated": True}]}]
    data["documents"] = [{"id": "s1", "name": "Oryginalna oferta.pdf", "version": 1, "status": "parsed", "sha256": "a" * 64}]
    html = render_html(data)
    assert "WERSJA HISTORYCZNA" in html
    assert "<script>" not in html
    assert "<img" not in html
    assert "&lt;script&gt;bad()&lt;/script&gt;" in html
    assert "Oryginalna oferta.pdf, strona 1" in html


def test_report_preserves_fact_minor_major_and_explicit_currency_units():
    data = snapshot()
    data["facts"] = [{"key": "price", "value": value, "unit": unit, "origin": "document",
                      "confirmation": "proposed", "evidence": []}
                     for value, unit in [("120000", "minor"), ("5500,50", "major"), ("42.00", "EUR"), (12, "%")]]
    html = render_html(data)
    assert "1 200,00 PLN" in html
    assert "5 500,50 PLN" in html
    assert "42,00 EUR" in html
    assert "120000" not in html
