"""Run periodically on the same host. This deletes expired cases and all derivatives."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, delete
from apps.api.config import settings
from apps.api.db import Case, WebSession, transaction, init_db
from apps.api.service import delete_case
import time


def run(dry_run=True, at=None):
    if settings.retention_days <= 0 or settings.demo_retention_hours <= 0:
        raise ValueError("Retention periods must be positive")
    current = at or datetime.now(timezone.utc)
    expired = []
    with transaction(write=not dry_run) as db:
        for case in db.scalars(select(Case)):
            retention = timedelta(hours=settings.demo_retention_hours) if case.demo else timedelta(days=settings.retention_days)
            if datetime.fromisoformat(case.updated_at) < current - retention:
                expired.append(case.id)
                if not dry_run:
                    delete_case(db, case)
        if not dry_run:
            db.execute(delete(WebSession).where(WebSession.expires < time.time()))
    return {"dryRun": dry_run, "expiredCaseIds": expired}


if __name__ == "__main__":
    import argparse, json
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    init_db()
    print(json.dumps(run(not args.apply)))
