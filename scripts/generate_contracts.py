import json
from pathlib import Path
from apps.api.main import app

target = Path("packages/contracts")
target.mkdir(parents=True, exist_ok=True)
(target / "openapi.json").write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding="utf-8")
print("OpenAPI written: packages/contracts/openapi.json")
