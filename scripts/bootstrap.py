"""Prepare a private, checksum-verified SQLite runtime without exposing secrets."""
import hashlib
import os
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SQLITE_URL = "https://www.sqlite.org/2026/sqlite-dll-win-x64-3510300.zip"
SQLITE_SHA256 = "ea004f52ba873cc54d1cb908c2f7cf48c3064061d9ee3ded6a309284da5ff411"

if os.name == "nt":
    directory = ROOT / ".runtime"
    directory.mkdir(exist_ok=True)
    archive = directory / "sqlite.zip"
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != SQLITE_SHA256:
        urllib.request.urlretrieve(SQLITE_URL, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SQLITE_SHA256:
        raise SystemExit("SQLite archive checksum mismatch")
    with zipfile.ZipFile(archive) as source:
        dll = next(name for name in source.namelist() if name == "sqlite3.dll")
        (directory / dll).write_bytes(source.read(dll))
from apps.api.db import sqlite3
print("SQLite:", sqlite3.sqlite_version)
for name in ("GOOGLE_AI_STUDIO_API_KEY", "KONTROFERTA_SESSION_SECRET", "OIDC_ISSUER", "OIDC_CLIENT_ID"):
    print(name + ": " + ("configured" if os.getenv(name) else "not injected"))
