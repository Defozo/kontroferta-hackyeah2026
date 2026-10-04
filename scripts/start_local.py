"""Start the application and worker; secrets are supplied to this parent by psst."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
env = os.environ.copy()
env.setdefault("APP_BASE_URL", "http://localhost:8080")
env.setdefault("OIDC_ISSUER", "http://localhost:8081")
env.setdefault("OIDC_CLIENT_ID", "kontroferta-local")
env.setdefault("AI_INPUT_USD_PER_MILLION", "0.75")
env.setdefault("AI_OUTPUT_USD_PER_MILLION", "3.75")
if not env.get("KONTROFERTA_SESSION_SECRET"):
    raise SystemExit("Inject KONTROFERTA_SESSION_SECRET with psst. See README.")
logs = ROOT / ".runtime"
logs.mkdir(exist_ok=True)
children, handles = [], []
commands = [
    ("identity", ["node", "apps/auth/server.mjs"], {**{k: v for k, v in env.items() if k.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA"}}, "LOCAL_OIDC_ISSUER": env["OIDC_ISSUER"], "LOCAL_APP_BASE_URL": env["APP_BASE_URL"]}),
    ("worker", [sys.executable, "-m", "apps.worker.main"], {k: v for k, v in env.items() if k not in {"KONTROFERTA_SESSION_SECRET", "OIDC_ISSUER", "OIDC_CLIENT_SECRET"}}),
    ("maintenance", [sys.executable, "-m", "scripts.maintenance"], {k: v for k, v in env.items() if k.upper() in {
        "PATH", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "DATABASE_URL", "FILE_STORAGE_PATH",
        "BACKUP_PATH", "CASE_RETENTION_DAYS", "DEMO_RETENTION_HOURS", "BACKUP_RETENTION_DAYS", "MAINTENANCE_INTERVAL_SECONDS"}}),
    ("api", [sys.executable, "-m", "uvicorn", "apps.api.main:app", "--no-access-log", "--host", "127.0.0.1", "--port", str(urlparse(env["APP_BASE_URL"]).port or 8080)], env),
]
for name, command, child_env in commands:
    handle = (logs / f"{name}.log").open("a", encoding="utf-8")
    handles.append(handle)
    children.append(subprocess.Popen(command, cwd=ROOT, env=child_env, stdout=handle, stderr=subprocess.STDOUT,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
(logs / "processes.json").write_text(__import__("json").dumps({"parent": os.getpid(), "children": [p.pid for p in children]}))
(logs / "local-config.json").write_text(__import__("json").dumps({"baseUrl": env["APP_BASE_URL"], "oidcIssuer": env["OIDC_ISSUER"]}))
print("KontrOferta: " + env["APP_BASE_URL"], flush=True)
try:
    while all(p.poll() is None for p in children):
        time.sleep(1)
finally:
    for child in children:
        child.terminate()
    for child in children:
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
    for handle in handles:
        handle.close()
