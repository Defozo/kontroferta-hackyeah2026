"""SQLite transactions, versioned immutable snapshots, and server-side sessions."""
import ctypes
import os
from pathlib import Path

# Windows Python can ship an older SQLite. Load our verified private DLL first.
_dll = Path(__file__).resolve().parents[2] / ".runtime" / "sqlite3.dll"
if os.name == "nt" and _dll.exists():
    _sqlite_library = ctypes.WinDLL(str(_dll))
import sqlite3
import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from .config import settings


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return str(uuid4())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    issuer: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String, default="")
    __table_args__ = (UniqueConstraint("issuer", "subject"),)


class WebSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    expires: Mapped[float] = mapped_column(Float)


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[str] = mapped_column(String, default=now)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)


class Revision(Base):
    __tablename__ = "revisions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(String, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON)
    author: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=now)
    __table_args__ = (UniqueConstraint("case_id", "revision"),)


class Member(Base):
    __tablename__ = "members"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)
    __table_args__ = (UniqueConstraint("case_id", "user_id"),)


class Invitation(Base):
    __tablename__ = "invitations"
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)
    expires: Mapped[float] = mapped_column(Float)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String)
    input_revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String, default="analysis")
    key: Mapped[str] = mapped_column(String, unique=True)
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    stage: Mapped[str] = mapped_column(String, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=now)
    updated_at: Mapped[str] = mapped_column(String, default=now)


class Usage(Base):
    __tablename__ = "usage"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    job_id: Mapped[str] = mapped_column(String)
    day: Mapped[str] = mapped_column(String, index=True)
    reserved: Mapped[float] = mapped_column(Float)
    actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class Tombstone(Base):
    __tablename__ = "deletions"
    case_id: Mapped[str] = mapped_column(String, primary_key=True)
    deleted_at: Mapped[str] = mapped_column(String, default=now)


class DocumentTombstone(Base):
    __tablename__ = "source_deletions"
    case_id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, primary_key=True)
    offer_id: Mapped[str] = mapped_column(String)
    deleted_at: Mapped[str] = mapped_column(String, default=now)


def make_engine(url):
    if url.startswith("sqlite:///"):
        path = url.removeprefix("sqlite:///")
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    from sqlalchemy.pool import StaticPool
    kwargs = {"poolclass": StaticPool} if ":memory:" in url else {}
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30}, **kwargs)

    @event.listens_for(engine, "connect")
    def configure(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        # Unsafe old WAL is never enabled. Deployment check requires fixed SQLite.
        version = tuple(map(int, sqlite3.sqlite_version.split(".")))
        safe = version >= (3, 51, 3) or (3, 50, 7) <= version < (3, 51, 0) or (3, 44, 6) <= version < (3, 45, 0)
        cursor.execute("PRAGMA journal_mode=" + ("WAL" if safe else "DELETE"))
        cursor.execute("PRAGMA synchronous=FULL")
        cursor.close()
    return engine


engine = make_engine(settings.database_url)


def init_db():
    settings.file_storage.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)


@contextmanager
def transaction(write=False):
    with Session(engine, expire_on_commit=False) as session:
        if write:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
