"""Actual new A PDF + annex extraction with production-length storage identifiers."""
from pathlib import Path
import argparse
import json
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.api.ai import extract_offer, AIError
from apps.api.extraction import parse_document, DocumentError
from packages.domain import demo_model, evaluate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", action="store_true", help="Isolate the provider adapter on matching authored text fixtures; does not claim PDF parsing.")
    parser.add_argument("--unconfirmed", action="store_true", help="Leave annex relationship unconfirmed; expected analysis remains incomplete pending human review.")
    args = parser.parse_args()
    output = ROOT/("eval/results/live-uuid-v8-text.json" if args.text else "eval/results/live-uuid-v8.json")
    ids = {name: str(uuid.uuid5(uuid.NAMESPACE_URL, "kontroferta/"+name)) for name in ("A-offer", "A-annex", "offer-A")}
    try:
        pages, sources = [], []
        for name in ("A-offer", "A-annex"):
            document = parse_document(ROOT/"fixtures/demo"/(name+(".txt" if args.text else ".pdf")), source_id=ids[name])
            pages.extend(document["pages"])
            sources.append({"source_id": ids[name], "relation": "offer" if name == "A-offer" else "annex", "replacesId": None, "relationConfirmed": name == "A-offer" or not args.unconfirmed, "documentDate": None})
        requirements = {**demo_model()["requirements"], "currency": "PLN", "budget_minor": 560000, "timezone": "Europe/Warsaw"}
        result = extract_offer(pages, requirements, offer_id=ids["offer-A"], existing_sources=sources)
        model = demo_model()
        model["offers"] = [result["domain_offer"], *model["offers"][1:]]
        model["variables"] = result["variables"]
        model["issues"] = [{"code": "extraction_gap", "message": issue, "blocking": True} for issue in result["issues"]]
        analysis = evaluate(model)
        expected_status = "incomplete" if args.unconfirmed else "needs_clarification"
        passed = analysis["status"] == expected_status and {tuple(row["winners"]) for row in analysis["scenarios"]} == {(ids["offer-A"],), ("B",)}
        data = {"mode": "real_new_text_extraction_with_uuid_sources" if args.text else "real_new_pdf_extraction_with_uuid_sources", "source_relationship_confirmed": not args.unconfirmed, "expected_status": expected_status, "passed": bool(passed), "extraction": result, "analysis": analysis, "limit": "B/C comparison peers are authored engine fixtures; this specifically exercises a fresh A+annex provider call with production-length IDs, not the full app approval flow."}
    except (AIError, DocumentError) as exc:
        data = {"passed": False, "error": {"code": exc.code, "trace": getattr(exc, "trace", {})}}
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "passed": data["passed"], "error": data.get("error"), "issues": data.get("extraction", {}).get("issues"), "usage": data.get("extraction", {}).get("trace", {}).get("usage"), "fact_count": len(data.get("extraction", {}).get("facts", []))}), flush=True)
    return 0 if data["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
