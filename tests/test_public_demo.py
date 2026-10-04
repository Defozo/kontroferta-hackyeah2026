"""Public guest access stays isolated and never starts from recorded answers."""
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api import db
from apps.api.auth import GUEST_ISSUER
from apps.api.config import ROOT, settings
from tests.test_api import api, ok


def guest(client):
    auth = ok(client.get("/api/auth/me"))
    client.headers.update({"x-csrf-token": auth["csrfToken"], "origin": settings.base_url})
    return client.post("/api/auth/guest")


def enable(monkeypatch):
    monkeypatch.setattr(settings, "guest_enabled", True)
    monkeypatch.setattr(settings, "session_secret", "guest-test-secret-with-at-least-32-characters")


def test_guest_is_disabled_by_default_and_requires_csrf(api, monkeypatch):
    monkeypatch.setattr(settings, "guest_enabled", False)
    assert guest(api.anonymous).status_code == 404
    enable(monkeypatch)
    assert api.anonymous.post("/api/auth/guest", headers={"x-csrf-token": "wrong"}).status_code == 403
    assert api.anonymous.post("/api/auth/guest", headers={"origin": "https://foreign.test"}).status_code == 403


def test_guest_secure_cookie_rotation_isolation_and_logout(api, monkeypatch):
    enable(monkeypatch)
    monkeypatch.setattr(settings, "base_url", "https://demo.test")
    from apps.api.main import app
    with TestClient(app, base_url=settings.base_url) as first, TestClient(app, base_url=settings.base_url) as second:
        ok(first.get("/api/auth/me"))
        old_cookie = first.cookies.get("kontroferta_session")
        response = guest(first)
        identity = ok(response)["user"]
        cookie = response.headers["set-cookie"]
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
        assert first.cookies.get("kontroferta_session") != old_cookie
        assert ok(guest(first))["user"] == identity
        assert ok(guest(second))["user"]["id"] != identity["id"]
        fresh = ok(first.post("/api/cases/demo-fresh"))
        assert second.get(f"/api/cases/{fresh['id']}").status_code == 404
        assert second.get(f"/api/cases/{fresh['id']}/documents/A-offer/file").status_code == 404
        ok(first.post("/api/auth/logout"))
        assert first.get(f"/api/cases/{fresh['id']}").status_code == 401


def test_fresh_guest_sources_are_unparsed_unanalysed_and_case_limit(api, monkeypatch):
    enable(monkeypatch)
    ok(guest(api.anonymous))
    fresh = ok(api.anonymous.post("/api/cases/demo-fresh"))
    assert fresh["pendingAnalysis"] and fresh["analysis"] is None
    assert fresh["facts"] == fresh["questions"] == fresh["decisions"] == []
    assert fresh["model"]["variables"] == []
    assert len(fresh["offers"]) == 3 and len(fresh["documents"]) == 4
    assert all(not offer["cost_items"] for offer in fresh["offers"])
    assert all(doc["status"] == "pending" and doc["pages"] == [] for doc in fresh["documents"])
    assert not fresh["requirements"]["confirmed"]
    assert api.anonymous.post("/api/cases", json={"expectedRevision": 0, "title": "Custom"}).status_code == 403
    ok(api.anonymous.post("/api/cases/demo"))
    assert api.anonymous.post("/api/cases/demo-fresh").status_code == 429
    assert api.anonymous.post(f"/api/cases/{fresh['id']}/documents", data={
        "expectedRevision": fresh["revision"], "offerId": "A", "text": "not a demo source"}).status_code == 403
    assert api.anonymous.post(f"/api/cases/{fresh['id']}/analysis", json={
        "expectedRevision": fresh["revision"], "consent": False}).status_code in {400, 422}


def test_public_cost_limit_survives_case_deletion(api, monkeypatch):
    enable(monkeypatch)
    identity = ok(guest(api.anonymous))["user"]
    fresh = ok(api.anonymous.post("/api/cases/demo-fresh"))
    with db.transaction(write=True) as session:
        session.add(db.Usage(case_id=fresh["id"], user_id=identity["id"], job_id="spent", day=db.now()[:10],
                             reserved=4, actual=4, details={"sensitive": "must disappear"}))
    ok(api.anonymous.request("DELETE", f"/api/cases/{fresh['id']}", json={"expectedRevision": fresh["revision"]}))
    with db.transaction() as session:
        usage = session.scalar(select(db.Usage))
        assert usage.actual == 4 and usage.case_id == "" and usage.job_id == ""
        assert "sensitive" not in usage.details
    monkeypatch.setattr(settings, "daily_budget", 4)
    next_case = ok(api.anonymous.post("/api/cases/demo-fresh"))
    assert api.anonymous.post(f"/api/cases/{next_case['id']}/analysis", json={
        "expectedRevision": next_case["revision"], "consent": True}).status_code == 429


def test_materials_allowlist_and_guest_session_cap(api, monkeypatch, tmp_path):
    enable(monkeypatch)
    monkeypatch.setattr(settings, "materials_path", tmp_path)
    (tmp_path / "materials.html").write_text("public material")
    (tmp_path / "private.zip").write_bytes(b"private")
    assert api.anonymous.get("/materials/").text == "public material"
    assert api.anonymous.get("/materials/private.zip").status_code == 404
    for name in ("KontrOferta-source.zip", "KontrOferta-source.sha256"):
        assert api.anonymous.get("/materials/" + name).status_code == 404
        (tmp_path / name).write_bytes(b"verified public source")
        assert api.anonymous.get("/materials/" + name).content == b"verified public source"
    assert api.anonymous.get("/materials/%2e%2e/private.zip").status_code == 404
    monkeypatch.setattr(settings, "guest_max_sessions", 0)
    assert guest(api.anonymous).status_code == 429


def test_public_reads_cannot_overwrite_initial_auth_session(api, monkeypatch):
    enable(monkeypatch)
    for path in ("/api/health", "/api/demo", "/api/demo/documents/A-offer/file"):
        response = api.anonymous.get(path)
        assert response.status_code == 200
        assert "set-cookie" not in response.headers
    assert not api.anonymous.cookies.get("kontroferta_session")
    auth = ok(api.anonymous.get("/api/auth/me"))
    token = api.anonymous.cookies.get("kontroferta_session")
    api.anonymous.get("/api/demo")
    assert api.anonymous.cookies.get("kontroferta_session") == token
    assert api.anonymous.post("/api/auth/guest", headers={"x-csrf-token": auth["csrfToken"],
                                                        "origin": settings.base_url}).status_code == 200
