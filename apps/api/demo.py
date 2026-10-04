"""Public example is authored fictional data, clearly labelled as recorded."""
import copy
import json
import hashlib
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from .config import ROOT
from .db import now
from .service import compute, fail
from .routes import preview

router = APIRouter(prefix="/api/demo", tags=["Recorded fictional example"])


@lru_cache(maxsize=1)
def _data():
    from packages.domain import demo_model
    from .extraction import parse_document, validate_citation
    cached = ROOT / "fixtures" / "demo" / "recorded.json"
    if cached.exists():
        data = json.loads(cached.read_text(encoding="utf-8"))
        for document in data["documents"]:
            source = ROOT / "fixtures" / "demo" / document["name"]
            if hashlib.sha256(source.read_bytes()).hexdigest() != document["sha256"]:
                raise RuntimeError("Recorded example source has changed; regenerate the example")
            document["storagePath"] = str(source)
        return data
    model = demo_model()
    documents = []
    for name, offer_id, relation in (("A-offer", "A", "offer"), ("A-annex", "A", "annex"), ("B-offer", "B", "offer"), ("C-offer", "C", "offer")):
        path = ROOT / "fixtures" / "demo" / (name + ".pdf")
        parsed = parse_document(path, "application/pdf", source_id=name)
        documents.append({"id": name, "offerId": offer_id, "name": path.name, "mime": "application/pdf",
            "sha256": parsed["sha256"], "bytes": path.stat().st_size, "author": "Fikcyjny wykonawca",
            "addedBy": "demo", "documentDate": "2026-10-03", "addedAt": "2026-10-03T12:00:00Z",
            "version": 1, "relation": relation, "relationConfirmed": True, "active": True,
            "storagePath": str(path), "status": "analyzed", "pages": parsed["pages"],
            "parserVersion": parsed["parser_version"]})
    facts = []
    for offer in model["offers"]:
        doc = next(d for d in documents if d["offerId"] == offer["id"] and d["relation"] == "offer")
        fields = ["currency", "tax_basis", "participants", "microphones", "ready_at", "service_start", "service_end", "scope_confirmed"]
        for field in fields:
            identifier = "demo-" + offer["id"].lower() + "-" + field
            page = doc["pages"][0]
            evidence = validate_citation({"source_id": doc["id"], "page": 1, "quote": page["text"]}, doc["pages"])
            facts.append({"id": identifier, "key": field, "value": offer[field], "offer_id": offer["id"],
                          "unit": None, "scope": "Fikcyjne wydarzenie 2026-10-10", "condition": None,
                          "origin": "recorded_example", "confirmation": "confirmed", "confirmedBy": "demo-author",
                          "evidence": [evidence], "critical": True, "conflict": False})
        for item in offer["cost_items"]:
            selected = next(d for d in documents if d["id"] == "A-annex") if item["id"] == "a-technician" else doc
            evidence = validate_citation({"source_id": selected["id"], "page": 1, "quote": selected["pages"][0]["text"]}, selected["pages"])
            identifier = item["evidence_ids"][0]
            if any(f["id"] == identifier for f in facts):
                identifier += "-" + item["id"]
            item["evidence_ids"] = [identifier]
            facts.append({"id": identifier, "key": "cost:" + item["id"], "value": item["amount"].get("value", [0, 120000]),
                          "label": item["label"], "offer_id": offer["id"], "unit": "minor", "condition": None,
                          "origin": "recorded_example", "confirmation": "confirmed", "confirmedBy": "demo-author",
                          "evidence": [evidence], "critical": True, "conflict": False})
        offer["evidence_ids"] = [f["id"] for f in facts if f["offer_id"] == offer["id"]]
    data = {"title": "Forum organizatorów · porównanie AV", "model": model,
            "requirements": {**model["requirements"], "currency": model["currency"], "timezone": model["timezone"], "budget_minor": model["budget_minor"]},
            "documents": documents, "facts": facts, "questions": [], "analysis": None,
            "decisions": [], "approval": {"current": True, "author": "demo-author"}, "impact": [], "pendingAnalysis": False,
            "recordedDemo": True}
    compute(data)
    return data


def demo_data():
    data = copy.deepcopy(_data())
    for offer in data["model"]["offers"]:
        if offer["id"] == "B":
            offer["name"] = "Pracownia Dźwięku"
        elif offer["id"] == "C":
            offer["name"] = "Sygnał Studio"
    compute(data)
    from packages.domain import evaluate
    exploration = copy.deepcopy(data["model"])
    variable = next(v for v in exploration["variables"] if v["id"] == "technician_surcharge")
    variable.update({"kind": "interval", "lower": 0, "upper": 120000, "step": 1,
                     "complete": True, "assumption": "Hipotetyczna dopłata od 0 do 1200 PLN; eksploracja, nie dziedzina dokumentu."})
    variable.pop("values", None)
    data["exploration_thresholds"] = {"preview": True, "assumption": variable["assumption"],
                                      "thresholds": evaluate(exploration).get("thresholds", [])}
    return data


@router.get("")
def read_demo():
    data = demo_data()
    for doc in data["documents"]:
        doc.pop("storagePath", None)
        doc["fileUrl"] = f"/api/demo/documents/{doc['id']}/file"
    return {**data, "id": "demo", "revision": 1, "role": "public", "updatedAt": "2026-10-03T12:00:00Z",
            "status": data["analysis"]["status"], "offers": data["model"]["offers"], "members": [], "jobs": [], "history": [],
            "usage": {"measuredUsd": 0, "estimatedUsd": 0, "note": "Zapisany przykład autorski, bez nowej inferencji."}}


@router.get("/recalculate")
def recalculate_demo(variable: str, value: int):
    if variable != "technician_surcharge" or not 0 <= value <= 10000000:
        fail("invalid_preview", "Podaj dopłatę od 0 do 100000 PLN.")
    return preview(demo_data(), {variable: value})


@router.get("/documents/{document_id}/file")
def demo_file(document_id: str):
    doc = next((d for d in _data()["documents"] if d["id"] == document_id), None)
    if not doc:
        fail("not_found", "Nie znaleziono dokumentu demonstracyjnego.", 404)
    return FileResponse(doc["storagePath"], media_type="application/pdf", filename=doc["name"], content_disposition_type="inline")
