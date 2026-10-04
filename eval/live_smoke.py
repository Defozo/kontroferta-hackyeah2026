"""Real provider smoke from a new synthetic PDF, never a prerecorded inference."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.api.extraction import parse_document
from apps.api.ai import extract_offer, AIError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="fixtures/demo/B-offer.pdf")
    parser.add_argument("--output", default="eval/results/live-smoke.json")
    args = parser.parse_args()
    requirements = {"participants": 120, "microphones": 4, "ready_by": "2026-10-10T09:00:00+02:00", "service_start": "2026-10-10T09:00:00+02:00", "service_end": "2026-10-10T17:00:00+02:00", "timezone": "Europe/Warsaw"}
    parsed = parse_document(ROOT/args.file, source_id="fresh-smoke-pdf")
    try:
        result = extract_offer(parsed, requirements, offer_id="smoke")
    except AIError as error:
        result = {"error": {"code": error.code, "message": str(error)}, "trace": error.trace}
    output = ROOT/args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"input": args.file, "sha256": parsed["sha256"], "parser": {key: value for key, value in parsed.items() if key != "pages"}, "result": result}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": args.output, "error": result.get("error"), "facts": len(result.get("facts", [])), "issues": result.get("issues"), "domain_offer": result.get("domain_offer"), "trace": result.get("trace")}, ensure_ascii=True))
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
