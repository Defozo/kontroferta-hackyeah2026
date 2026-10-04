"""Independent retention and daily consistent backup service. No AI secrets needed."""
import json
import logging
import signal
import threading
from datetime import datetime, timezone

from apps.api.config import settings
from apps.api.db import init_db, uid
from scripts.backup import backup, prune
from scripts.retention import run as retain_cases

STOP = threading.Event()
log = logging.getLogger("kontroferta.maintenance")


def run_once(at=None):
    current = at or datetime.now(timezone.utc)
    root = settings.backup_path.resolve()
    if root.is_relative_to(settings.file_storage.resolve()):
        raise ValueError("Backups must be outside private file storage")
    root.mkdir(parents=True, exist_ok=True)
    retention = retain_cases(dry_run=False, at=current)
    expired = prune(root, dry_run=False, at=current)
    existing_today = False
    for candidate in root.iterdir():
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        try:
            manifest = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
            created = datetime.fromisoformat(manifest["createdAt"])
            if manifest.get("application") == "KontrOferta" and manifest.get("kind") == "backup" and created.tzinfo and created.astimezone(timezone.utc).date() == current.astimezone(timezone.utc).date():
                existing_today = True
                break
        except (OSError, ValueError, KeyError):
            continue
    created_backup = None
    if not existing_today:
        destination = root / ("backup-" + current.strftime("%Y%m%dT%H%M%SZ") + "-" + uid()[:8])
        manifest = backup(destination)
        created_backup = {"directory": destination.name, "files": len(manifest["files"]),
                          "bytes": sum(record["bytes"] for record in manifest["files"])}
    return {"checkedAt": current.isoformat(), "retention": retention, "backups": expired,
            "createdBackup": created_backup, "dailyBackupPresent": True}


def main():
    if settings.maintenance_interval_seconds < 60:
        raise ValueError("Maintenance interval must be at least 60 seconds")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    init_db()
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    while not STOP.is_set():
        try:
            log.info("maintenance_complete %s", json.dumps(run_once()))
        except Exception as error:
            # Keep serving saved cases and retry at the next scheduled check.
            log.error("maintenance_failed type=%s", type(error).__name__)
        STOP.wait(settings.maintenance_interval_seconds)


if __name__ == "__main__":
    main()
