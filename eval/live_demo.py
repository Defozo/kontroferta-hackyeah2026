"""Actual PDF + Gemini + deterministic comparison, including both supplier answers.

This is a synthetic machine check, not a human approval or a user study.
Saved model proposals remain proposed. Only the test requirement fixture is confirmed.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.api.ai import extract_offer, AIError
from apps.api.extraction import parse_document, DocumentError
from packages.domain import demo_model, evaluate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="eval/results/live-demo-v4")
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--concurrency", type=int, choices=[1, 2], default=2)
    args = parser.parse_args()
    output = ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)
    requirements = {**demo_model()["requirements"], "timezone": "Europe/Warsaw"}
    cases = {
        "A_ambiguous": ["A-offer", "A-annex"],
        "B": ["B-offer"],
        "C": ["C-offer"],
        "A_included": ["A-offer", "A-annex", "A-answer-included"],
        "A_surcharge": ["A-offer", "A-annex", "A-answer-surcharge"],
    }
    def run(name):
        path = output/(name+".json")
        if args.retry_errors and path.exists():
            previous = json.loads(path.read_text(encoding="utf-8"))
            if "error" not in previous:
                return name, previous
            archive = output/"prior-attempts"
            archive.mkdir(exist_ok=True)
            (archive/(name+"-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+".json")).write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding="utf-8")
        started = datetime.now(timezone.utc).isoformat()
        try:
            pages, sources = [], []
            for stem in cases[name]:
                parsed = parse_document(ROOT / "fixtures/demo" / (stem + ".pdf"), source_id=stem)
                pages.extend(parsed["pages"])
                sources.append({"source_id": stem, "sha256": parsed["sha256"], "relation": "answer" if "answer" in stem else "annex" if "annex" in stem else "offer", "relationConfirmed": True})
            extraction = extract_offer(pages, requirements, offer_id=name[0], existing_sources=sources)
            value = {"mode": "real_gemini_inference", "started_at": started, "sources": sources, "extraction": extraction}
        except (AIError, DocumentError) as exc:
            value = {"started_at": started, "error": {"code": exc.code, "message": str(exc), "trace": getattr(exc, "trace", {})}}
        (output / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"case": name, "result": value.get("error", {}).get("code", "ok")}), flush=True)
        return name, value
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        predictions = dict(pool.map(run, cases))
    report = {"mode": "real_pdf_inference_and_engine", "human_approval": False, "retried_failed_requests_only": args.retry_errors, "cases": {}}
    for name, expected in (("A_ambiguous", None), ("A_included", "A"), ("A_surcharge", "B")):
        selected = [predictions[item] for item in (name, "B", "C")]
        if any("error" in item for item in selected):
            report["cases"][name] = {"passed": False, "reason": "extraction_error"}
            continue
        model = demo_model()
        model["offers"] = [item["extraction"]["domain_offer"] for item in selected]
        model["variables"] = [variable for item in selected for variable in item["extraction"]["variables"]]
        model["issues"] = [{"code": "extraction_gap", "offer_id": item["extraction"]["domain_offer"]["id"], "message": issue, "blocking": True} for item in selected for issue in item["extraction"]["issues"]]
        analysis = evaluate(model)
        passed = analysis["complete"] and analysis["unique_winner"] == expected
        if name == "A_ambiguous":
            passed = passed and analysis["status"] == "needs_clarification" and {tuple(row["winners"]) for row in analysis["scenarios"]} == {("A",), ("B",)}
        report["cases"][name] = {"passed": bool(passed), "expected_unique_winner": expected, "analysis": analysis}
    report["passed"] = all(case["passed"] for case in report["cases"].values())
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(output / "report.json"), "passed": report["passed"], "cases": {key: {"passed": value["passed"], "status": value.get("analysis", {}).get("status"), "issues": value.get("analysis", {}).get("issues")} for key, value in report["cases"].items()}}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
