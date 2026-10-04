"""Consistent SQLite backup plus private files under a writer lock."""
import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath
from apps.api import db
from apps.api.config import settings


def backup(destination: Path):
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("Choose a new backup destination")
    if destination.is_relative_to(settings.file_storage.resolve()):
        raise ValueError("Backup destination must be outside private file storage")
    if settings.backup_retention_days <= 0:
        raise ValueError("Backup retention must be positive")
    destination.mkdir(parents=True)
    incomplete = destination / ".incomplete.json"
    incomplete.write_text(json.dumps({"application": "KontrOferta", "kind": "incomplete_backup", "createdAt": db.now()}), encoding="utf-8")
    source = Path(db.engine.url.database)
    # Lock new writes while backing up from a separate reader and copying immutable originals.
    with db.engine.connect() as lock:
        lock.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            with sqlite3.connect(source) as reader, sqlite3.connect(destination / "database.sqlite") as target:
                reader.backup(target)
            if settings.file_storage.exists():
                shutil.copytree(settings.file_storage, destination / "files")
            manifest = {"application": "KontrOferta", "kind": "backup", "schema": "0002", "createdAt": db.now(), "sqlite": db.sqlite3.sqlite_version,
                        "retentionDays": settings.backup_retention_days, "files": []}
            for path in destination.rglob("*"):
                if path.is_file() and path != incomplete:
                    manifest["files"].append({"path": str(path.relative_to(destination)).replace("\\", "/"),
                                               "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size})
            (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            incomplete.unlink()
        finally:
            lock.rollback()
    return manifest


def restore(source: Path, destination: Path, deletion_registry: Path | None = None):
    source, destination = source.resolve(), destination.resolve()
    if destination.exists():
        raise ValueError("Restore into a new empty directory, never over a running application")
    if deletion_registry and not deletion_registry.is_file():
        raise ValueError("The current deletion registry does not exist")
    manifest = json.loads((source / "manifest.json").read_text())
    for record in manifest["files"]:
        path = (source / record["path"]).resolve()
        if not path.is_relative_to(source) or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("Backup checksum mismatch or unsafe path")
    shutil.copytree(source, destination)
    restored_db = destination / "database.sqlite"
    from apps.api.service import purge_source

    def source_tombstones(connection):
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_deletions'").fetchone():
            return {}
        return {(case_id, document_id): (offer_id, deleted_at) for case_id, document_id, offer_id, deleted_at
                in connection.execute("SELECT case_id,document_id,offer_id,deleted_at FROM source_deletions")}

    def case_folder(case_id):
        folder = (destination / "files" / case_id).resolve()
        if folder.parent != (destination / "files").resolve():
            raise ValueError("Unsafe case storage path")
        return folder

    with sqlite3.connect(restored_db) as connection:
        connection.execute("PRAGMA secure_delete=ON")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Restored database integrity failure")
        deleted = dict(connection.execute("SELECT case_id,deleted_at FROM deletions"))
        deleted_sources = source_tombstones(connection)
        if deletion_registry:
            if not deletion_registry.is_file():
                raise ValueError("The current deletion registry does not exist")
            with sqlite3.connect(deletion_registry.resolve().as_uri() + "?mode=ro", uri=True) as registry:
                deleted.update(dict(registry.execute("SELECT case_id,deleted_at FROM deletions")))
                deleted_sources.update(source_tombstones(registry))
        connection.execute("CREATE TABLE IF NOT EXISTS source_deletions (case_id TEXT NOT NULL, document_id TEXT NOT NULL, offer_id TEXT NOT NULL, deleted_at TEXT NOT NULL, PRIMARY KEY (case_id,document_id))")
        for case_id, deleted_at in deleted.items():
            connection.execute("INSERT OR REPLACE INTO deletions(case_id,deleted_at) VALUES (?,?)", (case_id, deleted_at))
            for table in ("cases", "revisions", "members", "invitations", "jobs", "usage"):
                connection.execute(f"DELETE FROM {table} WHERE {'id' if table == 'cases' else 'case_id'}=?", (case_id,))
            folder = case_folder(case_id)
            if folder.exists():
                shutil.rmtree(folder)
        changed_cases = set()
        for (case_id, document_id), (offer_id, deleted_at) in deleted_sources.items():
            connection.execute("INSERT OR REPLACE INTO source_deletions(case_id,document_id,offer_id,deleted_at) VALUES (?,?,?,?)",
                               (case_id, document_id, offer_id, deleted_at))
            row = connection.execute("SELECT data FROM cases WHERE id=?", (case_id,)).fetchone()
            if row:
                original = json.loads(row[0])
                purged = purge_source(original, document_id, offer_id)
                if purged != original:
                    changed_cases.add(case_id)
                    connection.execute("UPDATE cases SET data=? WHERE id=?", (json.dumps(purged), case_id))
                for rev_id, encoded in connection.execute("SELECT id,data FROM revisions WHERE case_id=?", (case_id,)).fetchall():
                    connection.execute("UPDATE revisions SET data=? WHERE id=?",
                                       (json.dumps(purge_source(json.loads(encoded), document_id, offer_id)), rev_id))
                connection.execute("UPDATE jobs SET data='{}',error=NULL,cancelled=1,status='cancelled',stage='source_deleted' WHERE case_id=?", (case_id,))
            folder = case_folder(case_id)
            if folder.exists():
                for private_file in folder.iterdir():
                    if private_file.is_file() and private_file.stem == document_id:
                        private_file.unlink()
        for case_id, encoded in connection.execute("SELECT id,data FROM cases").fetchall():
            data = json.loads(encoded)
            for doc in data.get("documents", []):
                doc["storagePath"] = str(case_folder(case_id) / PureWindowsPath(Path(doc["storagePath"]).name).name)
                if not Path(doc["storagePath"]).is_file():
                    raise ValueError("Restored evidence file missing")
            connection.execute("UPDATE cases SET data=? WHERE id=?", (json.dumps(data), case_id))
        for rev_id, case_id, encoded in connection.execute("SELECT id,case_id,data FROM revisions").fetchall():
            data = json.loads(encoded)
            for doc in data.get("documents", []):
                doc["storagePath"] = str(case_folder(case_id) / PureWindowsPath(Path(doc["storagePath"]).name).name)
            connection.execute("UPDATE revisions SET data=? WHERE id=?", (json.dumps(data), rev_id))
        for case_id in changed_cases:
            encoded, revision = connection.execute("SELECT data,revision FROM cases WHERE id=?", (case_id,)).fetchone()
            restored_at = db.now()
            connection.execute("UPDATE cases SET revision=?,updated_at=? WHERE id=?", (revision + 1, restored_at, case_id))
            connection.execute("INSERT INTO revisions(id,case_id,revision,data,author,action,created_at) VALUES (?,?,?,?,?,?,?)",
                               (db.uid(), case_id, revision + 1, encoded, "system-restore", "source_deletions_reapplied", restored_at))
        # Sessions and outstanding jobs cannot be replayed after restore.
        connection.execute("DELETE FROM sessions")
        connection.execute("UPDATE jobs SET status='superseded',stage='restored' WHERE status IN ('queued','running')")
        connection.commit()
        # Purge old JSON fragments from freed database pages as well as live rows.
        connection.execute("VACUUM")
    result = {"restored": True, "schema": "0002", "deletedCasesReapplied": len(deleted),
              "deletedSourcesReapplied": len(deleted_sources), "sourceCasesRevised": len(changed_cases)}
    (destination / "manifest.json").write_text(json.dumps({**manifest, "kind": "restored_instance", "restore": result}, indent=2), encoding="utf-8")
    return result


def prune(root: Path, *, dry_run=True, at=None):
    """Expire only recognized direct-child archives, never restored instances."""
    root = root.resolve()
    if settings.backup_retention_days <= 0:
        raise ValueError("Backup retention must be positive")
    if root == settings.file_storage.resolve() or root == Path(db.engine.url.database).resolve().parent:
        raise ValueError("Choose a dedicated backup directory")
    if not root.exists():
        return {"dryRun": dry_run, "expiredBackups": []}
    cutoff = (at or datetime.now(timezone.utc)) - timedelta(days=settings.backup_retention_days)
    expired = []
    for candidate in root.iterdir():
        if candidate.is_symlink() or not candidate.is_dir() or candidate.resolve().parent != root:
            continue
        try:
            metadata = candidate / "manifest.json"
            if not metadata.is_file():
                metadata = candidate / ".incomplete.json"
            manifest = json.loads(metadata.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(manifest["createdAt"])
        except (OSError, ValueError, KeyError):
            continue
        if manifest.get("application") != "KontrOferta" or manifest.get("kind") not in {"backup", "incomplete_backup"} or created.tzinfo is None or created >= cutoff:
            continue
        expired.append(candidate.name)
        if not dry_run:
            shutil.rmtree(candidate.resolve())
    return {"dryRun": dry_run, "expiredBackups": expired}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("create")
    create.add_argument("destination", type=Path)
    recover = sub.add_parser("restore")
    recover.add_argument("source", type=Path)
    recover.add_argument("destination", type=Path)
    recover.add_argument("--deletion-registry", type=Path)
    expire = sub.add_parser("prune")
    expire.add_argument("directory", type=Path)
    expire.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = backup(args.destination) if args.action == "create" else restore(args.source, args.destination, args.deletion_registry) if args.action == "restore" else prune(args.directory, dry_run=not args.apply)
    print(json.dumps(result, indent=2))
