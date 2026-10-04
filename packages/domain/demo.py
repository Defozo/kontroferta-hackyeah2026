"""The documented fictional A/B/C case. It is not a new model inference."""
from copy import deepcopy


def demo_model(surcharge_minor=None, continuous=False):
    day = "2026-10-10T"
    start, end = day + "09:00:00+02:00", day + "17:00:00+02:00"
    variable = {"id": "technician_surcharge", "label": "Dopłata za technika w A",
                "kind": "enum", "values": [0, 120000], "complete": True, "unit": "minor",
                "source": "Fikcyjna oferta A i aneks A1: dwa dopuszczalne odczytania ceny.",
                "question": "Czy łączna cena 4800 PLN brutto obejmuje obecność technika od 09:00 do 17:00? Jeśli nie, proszę podać ostateczną cenę całej usługi z technikiem.",
                "difficulty": 0, "evidence_ids": ["demo-a-technician", "demo-a-annex"]}
    if surcharge_minor is not None:
        variable["values"] = [surcharge_minor]
        variable["source"] = "Jawna odpowiedź użytkownika zapisana jako nowe źródło i wersja."
    if continuous:
        variable.update(kind="interval", values=[], lower=0, upper=120000, step=1,
                        assumption="Analiza progu: dopłata od 0 do 1200 PLN, co 1 grosz.")

    def cost(identifier, label, amount, evidence):
        return {"id": identifier, "label": label, "amount": amount, "category": "service", "evidence_ids": [evidence]}

    common = {"currency": "PLN", "tax_basis": "gross", "participants": 120,
              "microphones": 4, "service_start": start, "service_end": end,
              "scope_confirmed": True}
    offers = [
        {**deepcopy(common), "id": "A", "name": "Oferta A · Fala Audio", "ready_at": day + "08:30:00+02:00",
         "evidence_ids": ["demo-a-price", "demo-a-technician", "demo-a-annex"],
         "cost_items": [cost("a-set", "Zestaw nagłośnienia", {"op": "literal", "value": 420000}, "demo-a-price"),
                        cost("a-transport", "Transport", {"op": "literal", "value": 60000}, "demo-a-price"),
                        cost("a-technician", "Technik 09:00–17:00", {"op": "var", "name": "technician_surcharge"}, "demo-a-annex")]},
        {**deepcopy(common), "id": "B", "name": "Oferta B · Scena Partner", "ready_at": day + "08:30:00+02:00",
         "evidence_ids": ["demo-b-price"],
         "cost_items": [cost("b-package", "Pełny zakres z transportem i technikiem", {"op": "literal", "value": 550000}, "demo-b-price")]},
        {**deepcopy(common), "id": "C", "name": "Oferta C · Echo Events", "ready_at": day + "09:30:00+02:00",
         "evidence_ids": ["demo-c-price", "demo-c-ready"],
         "cost_items": [cost("c-package", "Pełny zakres", {"op": "literal", "value": 510000}, "demo-c-price")]},
    ]
    return {"schema_version": "1.0", "currency": "PLN", "minor_unit": 2,
            "budget_minor": 560000, "timezone": "Europe/Warsaw",
            "requirements": {"participants": 120, "microphones": 4, "ready_by": start,
                             "service_start": start, "service_end": end, "scope_required": True,
                             "description": "Fikcyjne wydarzenie AV dla 120 osób", "confirmed": True},
            "variables": [variable], "offers": offers, "constraints": [], "issues": []}
