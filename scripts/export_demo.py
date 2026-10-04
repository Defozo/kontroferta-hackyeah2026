"""Build the read-only recorded example from verified fictional sources."""
import json
import shutil
from pathlib import Path
from apps.api.config import ROOT
from apps.api.demo import demo_data, read_demo
from apps.api.reports import render_pdf
from apps.api.db import now

data = demo_data()
for document in data["documents"]:
    document.pop("storagePath", None)
(ROOT / "fixtures/demo/recorded.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
public = ROOT / "apps/web/public"
public.mkdir(exist_ok=True)
sources = public / "demo-documents"
sources.mkdir(exist_ok=True)
result = read_demo()
for doc in result["documents"]:
    doc["fileUrl"] = "/demo-documents/" + doc["name"]
    shutil.copyfile(ROOT / "fixtures/demo" / doc["name"], sources / doc["name"])
result["export"] = {"at": now(), "by": "DEFOZO SOFTWARE HOUSE / Michał Kiełtyka", "version": 1, "historical": False,
                    "snapshot": True, "recordedExample": True, "formatVersion": "1.0"}
(public / "demo-data.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
(public / "demo-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
(public / "demo-report.pdf").write_bytes(render_pdf(result))
print(json.dumps({"documents": len(result["documents"]), "facts": len(result["facts"]), "public": str(public), "recorded": True}))
