"""Human-readable decision snapshots; JSON remains the lossless machine format."""
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
from jinja2 import Environment, BaseLoader, select_autoescape
from playwright.sync_api import sync_playwright

TEMPLATE = Path(__file__).with_name("report_template.html").read_text(encoding="utf-8")
LABELS = {
    "participants": "Liczba uczestników", "microphones": "Liczba mikrofonów",
    "ready_by": "Najpóźniejsza gotowość", "ready_at": "Deklarowana gotowość",
    "service_start": "Początek obsługi", "service_end": "Koniec obsługi",
    "scope_required": "Wymagane potwierdzenie zakresu", "scope_confirmed": "Potwierdzony zakres",
    "currency": "Waluta", "timezone": "Strefa czasu", "budget_minor": "Budżet",
    "confirmed": "Potwierdzone", "tax_basis": "Podstawa podatkowa", "tax_rate": "Stawka podatku",
    "gross": "brutto", "net": "netto", "unknown": "Nieustalone",
    "needs_clarification": "Potrzebne wyjaśnienie", "incomplete": "Niepełne dane",
    "infeasible": "Brak wykonalnej oferty", "no_feasible_offer": "Brak wykonalnej oferty",
    "resolved": "Rozstrzygnięte", "winner": "Wskazany najtańszy wykonawca",
    "unique_winner": "Jedna najtańsza oferta", "shared_winners": "Wspólne najtańsze oferty",
    "common_winner": "Wspólny najtańszy wybór", "inconsistent": "Sprzeczne warunki",
    "description": "Opis zakresu", "preferences": "Preferencje jakościowe",
    "exact_enumeration": "Dokładna enumeracja", "analytic_partition": "Analityczny podział przedziału",
    "tie": "Remis", "robust": "Wspólny wybór", "no_offers": "Brak ofert",
    "service": "Koszt usługi", "deposit": "Zwrotna kaucja",
    "payment": "Harmonogram płatności", "cancellation": "Anulowanie",
    "open": "Otwarte", "draft": "Robocze", "copied": "Skopiowane",
    "awaiting_answer": "Oczekuje na odpowiedź", "answer_added": "Dodano odpowiedź",
    "final": "Decyzja ostateczna", "conditional": "Decyzja warunkowa",
    "document": "Odczyt z dokumentu", "human": "Ustalenie człowieka",
    "unconfirmed": "Niepotwierdzone", "needs_review": "Do ponownego przeglądu",
    "pending": "Oczekuje", "parsed": "Odczytane", "failed": "Błąd odczytu",
    "declared_author": "Autor dokumentu", "document_date": "Data dokumentu",
    "base_price_minor": "Cena bazowa", "transport_minor": "Transport",
    "technician_minor": "Dopłata za technika", "total_minor": "Pełna cena",
    "case_created": "Utworzenie sprawy", "requirements_updated": "Zmiana wymagań",
    "offer_created": "Dodanie oferty", "document_added": "Dodanie dokumentu",
    "analysis_completed": "Zakończenie analizy", "facts_confirmed": "Potwierdzenie ustaleń",
    "fact_confirmed": "Potwierdzenie ustalenia", "fact_updated": "Korekta ustalenia",
    "answer_added": "Dodanie odpowiedzi", "decision_created": "Zapis decyzji",
    "revision_restored": "Przywrócenie wersji", "member_joined": "Dołączenie do sprawy",
    "analysis_requested": "Zlecenie analizy", "critical_fields_approved": "Potwierdzenie pól krytycznych",
    "decision_approved": "Zatwierdzenie decyzji", "document_imported": "Import dokumentu",
    "invitation_created": "Utworzenie zaproszenia",
}


def render_html(data):
    env = Environment(loader=BaseLoader(), autoescape=select_autoescape(default=True))
    current = next((d for d in reversed(data.get("decisions", [])) if d.get("current")), None)
    model = data["model"]
    digits = model.get("minor_unit", 2)
    factor = Decimal(10) ** digits
    timezone = data.get("requirements", {}).get("timezone", model.get("timezone", "Europe/Warsaw"))
    offer_names = {o["id"]: o["name"] for o in model.get("offers", [])}
    people = {m["userId"]: m.get("name") or m["userId"] for m in data.get("members", [])}
    documents = {d["id"]: d["name"] for d in data.get("documents", [])}
    variables = {v["id"]: v for v in model.get("variables", [])}

    def money(amount, currency=None):
        if amount is None:
            return "brak danych"
        return f"{Decimal(str(amount)) / factor:,.{digits}f}".replace(",", " ").replace(".", ",") + " " + (currency or model["currency"])

    def yes(item):
        return "tak" if item else "nie"

    def label(item):
        if str(item).startswith("restored_revision:"):
            return "Przywrócenie wersji " + str(item).split(":", 1)[1]
        return LABELS.get(str(item), str(item).replace("_", " "))

    def value(item):
        if item is None or item == "":
            return "brak"
        if isinstance(item, bool):
            return yes(item)
        if isinstance(item, dict):
            return "; ".join(f"{label(k)}: {value(v)}" for k, v in item.items())
        if isinstance(item, list):
            return ", ".join(value(v) for v in item) or "brak"
        return label(item)

    def date(item):
        if not item:
            return "nieustalona"
        try:
            parsed = datetime.fromisoformat(str(item).replace("Z", "+00:00"))
            if "T" not in str(item):
                return parsed.strftime("%d.%m.%Y")
            if parsed.tzinfo:
                parsed = parsed.astimezone(ZoneInfo(timezone))
            return parsed.strftime("%d.%m.%Y %H:%M %z").strip()
        except (ValueError, TypeError):
            return str(item)

    def requirement(key, item):
        if key == "budget_minor":
            return money(item)
        if key in ("ready_by", "service_start", "service_end"):
            return date(item)
        return value(item)

    def variable_value(variable, item):
        return money(item) if variable.get("unit") == "minor" and item is not None else value(item)

    def domain(variable):
        kind = variable.get("kind")
        if kind == "enum":
            return "Dopuszczalne wartości: " + ", ".join(variable_value(variable, v) for v in variable.get("values", []))
        if kind == "interval":
            return "Przedział od " + variable_value(variable, variable.get("lower")) + " do " + variable_value(variable, variable.get("upper"))
        return "Dziedzina otwarta: wymaga dodatkowego ustalenia."

    def assignment(items):
        return "; ".join(f"{variables.get(k, {}).get('label', k)}: {variable_value(variables.get(k, {}), v)}" for k, v in items.items()) or "bez dodatkowych założeń"

    def fact_value(fact):
        unit = str(fact.get("unit") or "").lower()
        explicit_currency = {"pln": "PLN", "zl": "PLN", "zł": "PLN", "eur": "EUR", "usd": "USD", "gbp": "GBP", "chf": "CHF"}
        raw = fact.get("value")
        if unit in {"minor", "major", *explicit_currency} and raw is not None and not isinstance(raw, bool):
            try:
                amount = Decimal(str(raw).replace(",", "."))
                if amount.is_finite():
                    return money(amount if unit == "minor" else amount * factor, explicit_currency.get(unit))
            except (ValueError, ArithmeticError):
                pass
        if fact.get("key") in ("ready_at", "service_start", "service_end", "document_date"):
            return date(fact.get("value"))
        return value(fact.get("value"))

    offer = lambda identifier: offer_names.get(identifier, identifier or "Cała sprawa")
    return env.from_string(TEMPLATE).render(
        data=data, current=current, money=money, label=label, value=value, yes=yes,
        date=date, timezone=timezone, requirement=requirement, domain=domain,
        assignment=assignment, fact_value=fact_value, offer=offer,
        offers=lambda ids: ", ".join(offer(i) for i in ids) or "brak",
        person=lambda identifier: people.get(identifier, identifier or "nieprzypisana"),
        document=lambda identifier: documents.get(identifier, identifier),
    )


def render_pdf(data):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page()
        page.set_content(render_html(data), wait_until="load")
        result = page.pdf(format="A4", print_background=True, display_header_footer=True,
                          header_template="<span></span>", footer_template='<div style="font:9px Arial;width:100%;text-align:center"><span class="pageNumber"></span> / <span class="totalPages"></span></div>')
        browser.close()
        return result
