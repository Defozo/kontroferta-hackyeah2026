"""Real extraction evaluation with frozen-input integrity and explicit denominators.

Run via psst GOOGLE_AI_STUDIO_API_KEY -- .venv/Scripts/python.exe eval/run.py --split frozen.
No model request is made without --live. Offline scoring reads prior real predictions.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from apps.api.ai import AIError, extract_offer
from apps.api.extraction import parse_document, DocumentError


def verify_manifest() -> dict:
    manifest = json.loads((ROOT/"datasets/manifest.json").read_text(encoding="utf-8"))
    split_families = {split: set() for split in ("development", "frozen")}
    for case in manifest["cases"]:
        split_families[case["split"]].add(case["family"])
        for relative, expected in case["hashes"].items():
            path = ROOT/"datasets"/relative
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError("Frozen corpus changed: "+relative)
    if split_families["development"] & split_families["frozen"]:
        raise ValueError("Document-family leakage between development and frozen split")
    return manifest


def run_offer(case: dict, offer: dict, outdir: Path, live: bool, retry_errors: bool = False) -> dict:
    file = outdir/(case["id"]+"-"+offer["id"]+".json")
    if not live:
        if not file.exists():
            return {"case_id": case["id"], "offer_id": offer["id"], "error": {"code": "not_run"}}
        return json.loads(file.read_text(encoding="utf-8"))
    if retry_errors and file.exists():
        previous = json.loads(file.read_text(encoding="utf-8"))
        if "error" not in previous:
            return previous
        archive = outdir/"prior-attempts"
        archive.mkdir(parents=True, exist_ok=True)
        (archive/(file.stem+"-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+".json")).write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding="utf-8")
    pages, source_manifests = [], []
    started = time.monotonic()
    result = {"case_id": case["id"], "offer_id": offer["id"], "executed_at": datetime.now(timezone.utc).isoformat(), "mode": "real_gemini_inference"}
    try:
        for name in offer["files"]:
            parsed = parse_document(ROOT/"datasets"/case["id"]/name, source_id=case["id"]+"/"+name)
            pages.extend(parsed["pages"])
            source_manifests.append({"file": name, "sha256": parsed["sha256"], "parser_version": parsed["parser_version"], "complete": parsed["complete"], "pages": len(parsed["pages"])})
        result["extraction"] = extract_offer(pages, {**case["requirements"], "timezone": case["timezone"]}, offer_id=offer["id"], existing_sources=[{"relationship": "unconfirmed", "files": offer["files"]}] if len(offer["files"]) > 1 else [])
    except (AIError, DocumentError) as error:
        result["error"] = {"code": error.code, "message": str(error), "trace": getattr(error, "trace", {})}
    except Exception as error:
        result["error"] = {"code": "unexpected", "type": type(error).__name__}
    result["sources"] = source_manifests
    result["elapsed_seconds"] = round(time.monotonic()-started, 3)
    outdir.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def literal(expression: dict):
    if expression["op"] == "literal":
        return Decimal(str(expression["value"]))
    if expression["op"] == "sum":
        values = [literal(value) for value in expression["args"]]
        return sum(values) if all(value is not None for value in values) else None
    if expression["op"] == "mul":
        left, right = [literal(value) for value in expression["args"]]
        return left*right if left is not None and right is not None else None
    return None


def cost_total(offer: dict, category: str, currency: str):
    if category == "service" and offer.get("currency") != currency:
        return None
    if category == "service" and offer.get("tax_basis") not in {"net", "gross"}:
        return None
    items = [literal(item["amount"]) for item in offer.get("cost_items", []) if item["category"] == category]
    if not items:
        return None if category == "service" else Decimal(0)
    if any(value is None for value in items):
        return None
    total = sum(items)
    if category == "service" and offer.get("tax_basis") == "net":
        if offer.get("tax_rate") is None:
            return None
        total *= Decimal(1)+Decimal(str(offer["tax_rate"]))
    return total


def score(case: dict, offer: dict, prediction: dict) -> dict:
    expected = offer["expected"]
    result = {"case_id": case["id"], "offer_id": offer["id"], "split": case["split"], "modality": case["modality"], "tags": case["tags"], "fields": [], "error": prediction.get("error"), "evidence_count": 0, "accepted_fabricated_citations": 0}
    extraction = prediction.get("extraction", {})
    actual = extraction.get("domain_offer", {})
    fact_ids = [fact["id"] for fact in extraction.get("facts", [])]
    result["duplicate_normalized_fact_ids"] = len(fact_ids)-len(set(fact_ids))
    result["invalid_evidence_references"] = sum(reference not in fact_ids for item in actual.get("cost_items", []) for reference in item.get("evidence_ids", []))
    for key, value in expected["fields"].items():
        observed = actual.get(key)
        # Numeric decimal values and equivalent ISO offsets are compared semantically.
        match = observed == value
        if key == "tax_rate" and observed is not None and value is not None:
            match = Decimal(str(observed)) == Decimal(str(value))
        if key in {"ready_at", "service_start", "service_end"} and observed is not None and value is not None:
            try:
                match = datetime.fromisoformat(observed) == datetime.fromisoformat(value)
            except ValueError:
                match = False
        result["fields"].append({"key": key, "expected": value, "observed": observed, "correct": match and not prediction.get("error"), "omitted": observed is None and value is not None})
    for category, key in (("service", "service_total_minor"), ("deposit", "deposit_minor"), ("cancellation", "cancellation_minor"), ("payment", "payment_minor")):
        value = expected[key]
        observed = cost_total(actual, category, case["currency"])
        match = observed == (Decimal(value) if value is not None else None) and not prediction.get("error")
        result["fields"].append({"key": key, "expected": value, "observed": str(observed) if observed is not None else None, "correct": bool(match), "omitted": observed is None and value is not None})
    if expected.get("domain_values"):
        observed = sorted({value for variable in extraction.get("variables", []) for value in variable["values"] if isinstance(value, int)})
        result["fields"].append({"key": "domain_values", "expected": expected["domain_values"], "observed": observed, "correct": observed == expected["domain_values"], "omitted": not observed})
    if expected.get("conflict_required"):
        has_conflict = any("conflict" in issue for issue in extraction.get("issues", []))
        result["fields"].append({"key": "conflict", "expected": True, "observed": has_conflict, "correct": has_conflict, "omitted": not has_conflict})
    for fact in extraction.get("facts", []):
        for evidence in fact.get("evidence", []):
            result["evidence_count"] += 1
            if not evidence.get("quote_validated"):
                result["accepted_fabricated_citations"] += 1
    return result


def summarize(rows: list[dict]) -> dict:
    fields = [field for row in rows for field in row["fields"]]
    count = len(fields)
    correct = sum(field["correct"] for field in fields)
    return {"offers": len(rows), "critical_fields": count, "correct_fields": correct, "accuracy": correct/count if count else None,
            "omissions": sum(field["omitted"] for field in fields), "provider_or_parser_errors": sum(bool(row["error"]) for row in rows),
            "accepted_fabricated_citations": sum(row["accepted_fabricated_citations"] for row in rows), "evidence_count": sum(row["evidence_count"] for row in rows),
            "duplicate_normalized_fact_ids": sum(row["duplicate_normalized_fact_ids"] for row in rows),
            "invalid_evidence_references": sum(row["invalid_evidence_references"] for row in rows),
            "goal_95_percent_met": correct/count >= .95 if count else False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["development", "frozen", "all"], default="development")
    parser.add_argument("--live", action="store_true", help="Actually call Gemini. Without this flag, score previously saved real predictions.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", type=int, default=2, choices=[1, 2])
    parser.add_argument("--output", default="results/evaluation-v1")
    parser.add_argument("--post-tuning-regression", action="store_true", help="Declare that held-out failures have informed changes. This is no longer blind evaluation.")
    parser.add_argument("--retry-errors", action="store_true", help="With --live, retain successful real predictions and archive/retry errors only.")
    parser.add_argument("--case", action="append", help="Run only these explicit manifest case IDs; repeat the option for multiple cases.")
    args = parser.parse_args()
    manifest = verify_manifest()
    cases = [json.loads((ROOT/"datasets"/case["annotation"]).read_text(encoding="utf-8")) for case in manifest["cases"] if args.split == "all" or case["split"] == args.split]
    if args.case:
        available = {case["id"] for case in cases}
        if set(args.case)-available:
            raise ValueError("Unknown case IDs for selected split: "+", ".join(sorted(set(args.case)-available)))
        cases = [case for case in cases if case["id"] in args.case]
    if args.limit:
        cases = cases[:args.limit]
    outdir = ROOT/args.output
    jobs, predictions = [], {}
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        for case in cases:
            for offer in case["offers"]:
                jobs.append((executor.submit(run_offer, case, offer, outdir, args.live, args.retry_errors), case, offer))
        lookup = {future: (case, offer) for future, case, offer in jobs}
        for future in as_completed(lookup):
            case, offer = lookup[future]
            prediction = future.result()
            predictions[(case["id"], offer["id"])] = prediction
            print(json.dumps({"case": case["id"], "offer": offer["id"], "result": prediction.get("error", {}).get("code", "ok")}, ensure_ascii=True), flush=True)
    rows = [score(case, offer, predictions[(case["id"], offer["id"])]) for case in cases for offer in case["offers"]]
    elapsed = [value["elapsed_seconds"] for value in predictions.values() if "elapsed_seconds" in value]
    traces = [value.get("extraction", {}).get("trace", value.get("error", {}).get("trace", {})) for value in predictions.values()]
    report = {"dataset_version": manifest["dataset_version"], "frozen_at": manifest["frozen_at"], "run_at": datetime.now(timezone.utc).isoformat(),
              "execution": "live" if args.live else "score_saved_predictions", "split": args.split, "model": sorted({trace.get("model", "unknown") for trace in traces}),
              "retried_failed_requests_only": args.retry_errors,
              "evaluation_design": "post_tuning_regression_not_blind" if args.post_tuning_regression else "initial_split_run_not_independent_human_benchmark",
              "prompt_versions": sorted({trace.get("prompt_version", "unknown") for trace in traces}), "schema_versions": sorted({trace.get("schema_version", "unknown") for trace in traces}),
              "summary": summarize(rows), "by_split": {split: summarize([row for row in rows if row["split"] == split]) for split in {row["split"] for row in rows}},
              "by_modality": {modality: summarize([row for row in rows if row["modality"] == modality]) for modality in {row["modality"] for row in rows}},
              "by_tag": {tag: summarize([row for row in rows if tag in row["tags"]]) for tag in {tag for row in rows for tag in row["tags"]}},
              "duration_seconds": round(time.monotonic()-started, 3), "median_offer_seconds": statistics.median(elapsed) if elapsed else None,
              "p95_offer_seconds": sorted(elapsed)[max(0, int(len(elapsed)*.95+.999)-1)] if elapsed else None,
              "usage": {key: sum(trace.get("usage", {}).get(key, 0) for trace in traces) for key in ("input_tokens", "output_tokens", "thinking_tokens")},
              "estimated_api_cost_usd": str(sum(Decimal(trace["estimated_cost_usd"]) for trace in traces)) if traces and all(trace.get("estimated_cost_usd") is not None for trace in traces) else None,
              "hardware": {"platform": platform.platform(), "python": platform.python_version(), "processor": platform.processor()},
              "release_status": "NOT CERTIFIED: independent annotation review and organizer study pending",
              "limitations": ["Synthetic authored fixtures, not a supplied or validated industry dataset.", "Second human annotation review has not occurred.", "This run measures extraction, not five-user time savings or full service quality.", "Frozen examples were authored by the implementing assistant. No blind human benchmark claim.", "Missing provider rates/usage are unknown cost, not zero."] + (["Earlier frozen failures informed prompt changes. This rerun is a regression check, not held-out evidence."] if args.post_tuning_regression else []), "rows": rows}
    outdir.mkdir(parents=True, exist_ok=True)
    report_file = outdir/("report-"+args.split+".json")
    report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"report": str(report_file), "summary": report["summary"], "duration_seconds": report["duration_seconds"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
