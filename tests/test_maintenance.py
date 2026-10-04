import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from apps.api import db
from apps.api.config import settings
from apps.api.service import empty_data
from scripts.backup import backup, prune
from scripts.maintenance import run_once


@pytest.fixture
def maintenance_store(tmp_path, monkeypatch):
    engine = db.make_engine("sqlite:///" + str(tmp_path / "cases.sqlite"))
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(settings, "file_storage", tmp_path / "files")
    monkeypatch.setattr(settings, "backup_path", tmp_path / "backups")
    monkeypatch.setattr(settings, "demo_retention_hours", 2)
    monkeypatch.setattr(settings, "retention_days", 4)
    monkeypatch.setattr(settings, "backup_retention_days", 7)
    db.init_db()
    yield tmp_path
    engine.dispose()


def test_maintenance_respects_configured_periods_keeps_daily_backup_and_bounds_deletions(maintenance_store):
    current = datetime.now(timezone.utc)
    records = [("expired-demo", True, timedelta(hours=3)), ("kept-demo", True, timedelta(hours=1)),
               ("expired-case", False, timedelta(days=5)), ("kept-case", False, timedelta(days=3))]
    with db.transaction(write=True) as session:
        for identifier, demo, age in records:
            session.add(db.Case(id=identifier, owner_id="owner", title=identifier, demo=demo, revision=1,
                                updated_at=(current-age).isoformat(), data=empty_data(identifier, {})))
            folder = settings.file_storage / identifier
            folder.mkdir()
            (folder / "original.txt").write_text(identifier)
    root = settings.backup_path
    root.mkdir()
    for name, kind in (("expired-archive", "backup"), ("restored-working-copy", "restored_instance"), ("expired-partial", "incomplete_backup")):
        directory = root / name
        directory.mkdir()
        filename = ".incomplete.json" if kind == "incomplete_backup" else "manifest.json"
        (directory / filename).write_text(json.dumps({"application": "KontrOferta", "kind": kind,
            "createdAt": (current-timedelta(days=8)).isoformat()}))
        (directory / "private-content.txt").write_text("content")
    unrelated = root / "unrecognized-user-folder"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("user file")
    outside = maintenance_store / "outside-backup-directory"
    outside.mkdir()
    (outside / "keep.txt").write_text("user file")
    first = run_once(current)
    assert set(first["retention"]["expiredCaseIds"]) == {"expired-demo", "expired-case"}
    assert set(first["backups"]["expiredBackups"]) == {"expired-archive", "expired-partial"}
    assert first["createdBackup"] and first["dailyBackupPresent"]
    archive = root / first["createdBackup"]["directory"]
    manifest = json.loads((archive / "manifest.json").read_text())
    assert manifest["retentionDays"] == 7 and manifest["kind"] == "backup"
    assert not (archive / ".incomplete.json").exists()
    with sqlite3.connect(archive / "database.sqlite") as connection:
        assert {r[0] for r in connection.execute("SELECT id FROM cases")} == {"kept-demo", "kept-case"}
        assert {r[0] for r in connection.execute("SELECT case_id FROM deletions")} == {"expired-demo", "expired-case"}
    assert not (settings.file_storage / "expired-demo").exists()
    assert (settings.file_storage / "kept-demo" / "original.txt").exists()
    assert (root / "restored-working-copy" / "private-content.txt").exists()
    assert (unrelated / "keep.txt").exists() and (outside / "keep.txt").exists()
    second = run_once(current)
    assert second["createdBackup"] is None and second["retention"]["expiredCaseIds"] == []
    with pytest.raises(ValueError, match="dedicated"):
        prune(settings.file_storage, dry_run=False)
    with pytest.raises(ValueError, match="outside"):
        backup(settings.file_storage / "recursive-backup")
