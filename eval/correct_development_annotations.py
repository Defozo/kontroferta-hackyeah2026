"""Disclosed corrections to development annotation mistakes, preserving prior hashes.

No held-out source or annotation is changed. The original evaluation report remains.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
manifest_path = ROOT/"datasets/manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if manifest["dataset_version"] != "synthetic-av-v1":
    raise SystemExit("Corrections already applied or unsupported corpus version")
archive = ROOT/"annotation-history/v1"
archive.mkdir(parents=True, exist_ok=True)
(archive/"manifest.json").write_text(manifest_path.read_text(encoding="utf-8"), encoding="utf-8")
corrected = []
for case in manifest["cases"]:
    if case["family"] not in {"tax_basis_absent", "currency_absent", "ambiguity_addendum"}:
        continue
    path = ROOT/"datasets"/case["annotation"]
    data = json.loads(path.read_text(encoding="utf-8"))
    (archive/(case["id"]+"-annotations.json")).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    for offer in data["offers"]:
        if case["family"] != "ambiguity_addendum":
            offer["expected"]["service_total_minor"] = None
        else:
            offer["expected"]["evidence_annotations"] = {"participants": "Potwierdzamy odpowiedniość oferowanego nagłośnienia dla konferencji 120 osób.", "microphones": "W zestawie są 4 mikrofony bezprzewodowe.", "ready_at": "Gotowość sprzętu: 10.10.2026 o 08:30.", "service_start": "Technik jest dostępny i obecny przez cały okres 09:00-17:00.", "service_end": "Technik jest dostępny i obecny przez cały okres 09:00-17:00.", "price": "Łącznie: 4800 PLN brutto." if offer["id"] == "A" else "Pełna cena usługi: 5500 PLN brutto."}
    data["annotation_correction"] = "Development v1.1: unknown currency/tax cannot establish comparable gross cost; ambiguity evidence quotes corrected to actual demo source. Original retained in annotation-history/v1."
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    case["hashes"][case["annotation"]] = hashlib.sha256(path.read_bytes()).hexdigest()
    corrected.append(case["id"])
manifest["dataset_version"] = "synthetic-av-v1.1"
manifest["development_annotation_correction"] = {"at": datetime.now(timezone.utc).isoformat(), "cases": corrected, "frozen_split_changed": False, "reason": "Correct annotation mistakes discovered during development, not model outputs."}
manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps({"corrected_development_annotations": corrected, "frozen_changed": False}))
