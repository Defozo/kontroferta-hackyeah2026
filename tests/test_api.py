"""Integration tests use real routes, sessions, SQL transactions and private files.

Only identity-provider login and model inference are replaced by controlled
fixtures. They have separate live verification; these tests make no live calls.
"""
import copy
import asyncio
import hashlib
import hmac
import json
import time
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api import db
from apps.api.config import settings


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def session_key(token):
    return hmac.new(settings.session_secret.encode(), token.encode(), hashlib.sha256).hexdigest()


@pytest.fixture
def api(tmp_path, monkeypatch):
    engine = db.make_engine("sqlite:///" + str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(settings, "file_storage", tmp_path / "private")
    monkeypatch.setattr(settings, "base_url", "http://localhost:8080")
    monkeypatch.setattr(settings, "oidc_issuer", "")
    monkeypatch.setattr(settings, "case_budget", 20)
    monkeypatch.setattr(settings, "daily_budget", 100)
    monkeypatch.setattr(settings, "account_budget", 100)
    db.init_db()
    from apps.api.main import app
    clients = {}
    with ExitStack() as stack:
        for name in ("owner", "stranger", "collaborator"):
            client = stack.enter_context(TestClient(app, base_url=settings.base_url))
            session = ok(client.get("/api/auth/me"))
            csrf = session["csrfToken"]
            cookie = client.cookies.get("kontroferta_session")
            with db.transaction(write=True) as session_db:
                session_db.add(db.User(id=name, issuer="https://identity.test", subject=name,
                                       name=name, email=f"{name}@test.invalid"))
                row = session_db.get(db.WebSession, session_key(cookie))
                row.user_id = name
                row.data = {**row.data, "user_id": name}
            client.headers.update({"x-csrf-token": csrf, "origin": settings.base_url})
            clients[name] = client
        clients["anonymous"] = stack.enter_context(TestClient(app, base_url=settings.base_url))
        yield SimpleNamespace(**clients)
    engine.dispose()


@pytest.fixture
def case(api):
    return ok(api.owner.post("/api/cases/demo"))


def refresh(client, case):
    return ok(client.get(f"/api/cases/{case['id']}"))


def approve(client, case):
    return ok(client.post(f"/api/cases/{case['id']}/approvals", json={
        "expectedRevision": case["revision"], "factIds": [f["id"] for f in case["facts"]],
        "requirementsConfirmed": True}))


def answer(client, case, value=0, kind="value", confirmed=True):
    return ok(client.post(f"/api/cases/{case['id']}/questions/technician_surcharge/answers", json={
        "expectedRevision": case["revision"], "kind": kind, "value": value,
        "confirmed": confirmed, "text": "Nie wiem" if kind == "unknown" else f"Potwierdzona dopłata: {value} groszy"}))


def decision_body(case, offer="A", **extra):
    return {"expectedRevision": case["revision"], "offerId": offer, "kind": "final",
            "reason": "Wybrano pełny zakres spełniający wymagania.",
            "confirmCost": True, "confirmScope": True, "confirmDeadline": True, **extra}


def upload(client, case, text="Nowa treść dokumentu", offer="A", **extra):
    return client.post(f"/api/cases/{case['id']}/documents", data={
        "expectedRevision": case["revision"], "offerId": offer, "text": text, **extra})


def invite(client, case, role):
    response = ok(client.post(f"/api/cases/{case['id']}/invitations", json={"expectedRevision": case["revision"], "role": role}))
    return response["token"], response["case"]


def add_job(case, status="completed"):
    identifier = db.uid()
    with db.transaction(write=True) as session:
        session.add(db.Job(id=identifier, case_id=case["id"], user_id="owner", input_revision=case["revision"],
                           key=identifier, status=status, stage=status, data={}))
    return identifier


def test_sessions_csrf_expiry_and_real_logout(api, case):
    assert api.anonymous.get("/api/cases").status_code == 401
    assert api.owner.get("/api/auth/me").json()["user"]["id"] == "owner"
    assert api.owner.patch(f"/api/cases/{case['id']}", json={"expectedRevision": case["revision"], "title": "X"},
                           headers={"x-csrf-token": "incorrect"}).status_code == 403
    assert api.owner.patch(f"/api/cases/{case['id']}", json={"expectedRevision": case["revision"], "title": "X"},
                           headers={"origin": "https://foreign.test"}).status_code == 403
    token = api.owner.cookies.get("kontroferta_session")
    csrf = api.owner.headers["x-csrf-token"]
    assert api.owner.post("/api/auth/logout").status_code == 200
    with db.transaction() as session:
        assert session.get(db.WebSession, session_key(token)) is None
    api.owner.cookies.set("kontroferta_session", token)
    api.owner.headers["x-csrf-token"] = csrf
    assert api.owner.get(f"/api/cases/{case['id']}").status_code == 401
    with db.transaction(write=True) as session:
        for row in session.scalars(select(db.WebSession).where(db.WebSession.user_id == "stranger")):
            row.expires = time.time() - 1
    assert api.stranger.get("/api/cases").status_code == 401


def test_two_users_cannot_cross_case_file_export_history_or_sse(api, case):
    other = ok(api.stranger.post("/api/cases/demo"))
    assert {c["id"] for c in ok(api.owner.get("/api/cases"))["cases"]} == {case["id"]}
    assert {c["id"] for c in ok(api.stranger.get("/api/cases"))["cases"]} == {other["id"]}
    identifier = add_job(case)
    paths = [f"/api/cases/{case['id']}", f"/api/cases/{case['id']}/documents/A-offer/file",
             f"/api/cases/{case['id']}/exports/json", f"/api/cases/{case['id']}/exports/pdf",
             f"/api/cases/{case['id']}/history/1", f"/api/jobs/{identifier}/events"]
    for path in paths:
        assert api.stranger.get(path).status_code == 404, path
        assert api.anonymous.get(path).status_code == 401, path
    source = api.owner.get(paths[1])
    assert source.status_code == 200 and source.content.startswith(b"%PDF")
    events = api.owner.get(f"/api/jobs/{identifier}/events")
    assert events.status_code == 200 and "event: job" in events.text
    report = ok(api.owner.get(paths[2]))
    assert report["export"]["snapshot"] and not report["export"]["historical"]
    assert "storagePath" not in json.dumps(report)


@pytest.mark.parametrize("role", ["observer", "editor"])
def test_collaboration_roles_and_single_use_invitation(api, case, role):
    token, case = invite(api.owner, case, role)
    joined = ok(api.collaborator.post(f"/api/invitations/{token}/accept"))
    assert joined["role"] == role
    assert api.stranger.post(f"/api/invitations/{token}/accept").status_code == 410
    assert api.collaborator.get(f"/api/cases/{case['id']}/documents/A-offer/file").status_code == 200
    changed = api.collaborator.patch(f"/api/cases/{case['id']}", json={"expectedRevision": joined["revision"], "title": "Wspólna sprawa"})
    assert changed.status_code == (403 if role == "observer" else 200)
    latest = refresh(api.owner, case)
    assert api.collaborator.post(f"/api/cases/{case['id']}/decisions", json=decision_body(latest)).status_code == 403
    assert api.collaborator.post(f"/api/cases/{case['id']}/invitations", json={"expectedRevision": latest["revision"], "role": "editor"}).status_code == 403
    assert api.collaborator.request("DELETE", f"/api/cases/{case['id']}", json={"expectedRevision": latest["revision"]}).status_code == 403
    if role == "observer":
        assert api.collaborator.post(f"/api/cases/{case['id']}/approvals", json={"expectedRevision": latest["revision"], "requirementsConfirmed": True}).status_code == 403
        preview = ok(api.collaborator.post(f"/api/cases/{case['id']}/recalculate", json={
            "expectedRevision": latest["revision"], "assignments": {"technician_surcharge": 0}}))
        assert preview["preview"] and preview["unique_winner"] == "A"
        assert refresh(api.owner, case)["revision"] == latest["revision"]
        assert api.collaborator.post(f"/api/cases/{case['id']}/recalculate", json={"expectedRevision": latest["revision"]}).status_code == 403
    removed = ok(api.owner.request("DELETE", f"/api/cases/{case['id']}/members/collaborator", json={"expectedRevision": latest["revision"]}))
    assert removed["revision"] == latest["revision"] + 1
    assert api.collaborator.get(f"/api/cases/{case['id']}").status_code == 404


def test_expired_invitation_and_forged_owner_role(api, case):
    token, case = invite(api.owner, case, "editor")
    with db.transaction(write=True) as session:
        session.get(db.Invitation, hashlib.sha256(token.encode()).hexdigest()).expires = time.time() - 1
    assert api.stranger.post(f"/api/invitations/{token}/accept").status_code == 410
    assert api.owner.post(f"/api/cases/{case['id']}/invitations", json={"expectedRevision": case["revision"], "role": "owner"}).status_code == 422


def test_optimistic_revision_conflict_does_not_overwrite(api, case):
    updated = ok(api.owner.patch(f"/api/cases/{case['id']}", json={"expectedRevision": case["revision"], "title": "Aktualny tytuł"}))
    stale = api.owner.patch(f"/api/cases/{case['id']}", json={"expectedRevision": case["revision"], "title": "Nieaktualny zapis"})
    assert stale.status_code == 409
    assert stale.json()["detail"]["currentRevision"] == updated["revision"]
    current = refresh(api.owner, case)
    assert current["title"] == "Aktualny tytuł"
    assert len(current["history"]) == len(updated["history"])


@pytest.mark.parametrize("value,winner,outside", [(0, "A", False), (120000, "B", False), (70100, "B", True)])
def test_confirmed_answers_recalculate_and_create_new_provenance(api, case, value, winner, outside):
    changed = answer(api.owner, case, value)
    assert changed["revision"] == case["revision"] + 1
    assert changed["analysis"]["unique_winner"] == winner
    question = next(q for q in changed["questions"] if q["id"] == "technician_surcharge")
    assert question["status"] == "resolved"
    assert question["answers"][-1]["outsideOriginalDomain"] == outside
    variable = changed["model"]["variables"][0]
    assert variable["values"] == [value] and variable["source"].startswith("answer:")
    human = next(f for f in changed["facts"] if f["id"] == question["answers"][-1]["id"])
    assert human["origin"] == "human" and human["evidence"] == []
    old = ok(api.owner.get(f"/api/cases/{case['id']}/history/1"))
    assert old["snapshot"]["model"]["variables"][0]["values"] == [0, 120000]


def test_unknown_or_unconfirmed_answer_does_not_collapse_domain(api, case):
    changed = answer(api.owner, case, None, "unknown", False)
    assert changed["analysis"]["status"] == "needs_clarification"
    assert changed["model"]["variables"][0]["values"] == [0, 120000]
    response = api.owner.patch(f"/api/cases/{case['id']}/questions/technician_surcharge", json={"expectedRevision": changed["revision"], "status": "resolved"})
    assert response.status_code == 422
    unconfirmed = answer(api.owner, changed, 0, confirmed=False)
    assert unconfirmed["model"]["variables"][0]["values"] == [0, 120000]


def test_preview_is_not_a_supplier_answer_and_does_not_change_revision(api, case):
    preview = ok(api.owner.post(f"/api/cases/{case['id']}/recalculate", json={"expectedRevision": case["revision"], "assignments": {"technician_surcharge": 0}}))
    assert preview["preview"] and preview["unique_winner"] == "A"
    current = refresh(api.owner, case)
    assert current["revision"] == case["revision"]
    assert current["model"]["variables"][0]["values"] == [0, 120000]
    assert not current["questions"][0]["answers"]


def test_final_decision_requires_evidence_requirements_and_explicit_fields(api, case):
    path = f"/api/cases/{case['id']}/decisions"
    assert api.owner.post(path, json=decision_body(case, "B")).status_code == 422
    case = approve(api.owner, case)
    assert api.owner.post(path, json=decision_body(case, "B", confirmScope=False)).status_code == 422
    assert api.owner.post(path, json=decision_body(case, "A")).status_code == 422
    decided = ok(api.owner.post(path, json=decision_body(case, "B")))
    decision = decided["decisions"][-1]
    assert decision["current"] and not decision["isCommonCheapest"]
    assert decision["costsMinor"] == [550000]
    assert decision["revision"] == decided["revision"]
    assert api.owner.post(path, json=decision_body(decided, "A", kind="conditional")).status_code == 422


@pytest.mark.parametrize("problem", ["invalid_citation", "conflict", "condition_unresolved"])
def test_invalid_citation_cannot_be_confirmed_through_individual_patch(api, case, problem):
    fact_id = case["facts"][0]["id"]
    with db.transaction(write=True) as session:
        row = session.get(db.Case, case["id"])
        data = copy.deepcopy(row.data)
        if problem == "invalid_citation":
            data["facts"][0]["evidence"][0]["quote_validated"] = False
        else:
            data["facts"][0][problem] = True
        row.data = data
    response = api.owner.patch(f"/api/cases/{case['id']}/facts/{fact_id}", json={
        "expectedRevision": case["revision"], "reason": "Sprawdzam cytat", "confirmation": "confirmed"})
    assert response.status_code == 422


def test_new_annex_invalidates_dependent_facts_and_decision_preserves_others(api, case):
    case = answer(api.owner, case, 0)
    # An unrelated answered question remains part of the audit workflow.
    with db.transaction(write=True) as session:
        stored = session.get(db.Case, case["id"])
        payload = copy.deepcopy(stored.data)
        payload["questions"].append({"id": "B-payment", "offer_id": "B", "status": "resolved",
            "answers": [{"id": "B-answer", "confirmed": True, "text": "Uzgodniono płatność."}]})
        stored.data = payload
    case = refresh(api.owner, case)
    case = approve(api.owner, case)
    case = ok(api.owner.post(f"/api/cases/{case['id']}/decisions", json=decision_body(case)))
    old_revision = case["revision"]
    updated = ok(upload(api.owner, case, "Nowy aneks zmienia cenę technika.", relation="annex", relationConfirmed="true"))
    assert updated["pendingAnalysis"]
    assert not updated["approval"]["current"]
    assert not updated["decisions"][-1]["current"]
    assert all(f["confirmation"] == "confirmed" for f in updated["facts"] if f.get("offer_id") == "B")
    assert any(f["confirmation"] == "needs_review" for f in updated["facts"] if f.get("offer_id") == "A")
    question = next(q for q in updated["questions"] if q["id"] == "technician_surcharge")
    assert question["status"] == "answer_added" and question["needsReview"]
    assert question["answers"][0]["confirmed"] and question["answers"][0]["needsReview"]
    unrelated = next(q for q in updated["questions"] if q["id"] == "B-payment")
    assert unrelated["status"] == "resolved" and not unrelated["answers"][0].get("needsReview")
    assert api.owner.post(f"/api/cases/{case['id']}/approvals", json={"expectedRevision": updated["revision"], "factIds": [], "requirementsConfirmed": True}).status_code == 422
    historical = ok(api.owner.get(f"/api/cases/{case['id']}/exports/json?revision={old_revision}"))
    assert historical["export"]["historical"] and historical["export"]["version"] == old_revision
    assert historical["status"] == "unique_winner"
    assert historical["offers"] == historical["model"]["offers"]


def test_reexpanded_model_reopens_answered_question_and_retains_answer_history(api, case):
    from apps.api.service import compute
    resolved = answer(api.owner, case, 0)
    data = copy.deepcopy(resolved)
    variable = next(v for v in data["model"]["variables"] if v["id"] == "technician_surcharge")
    variable.update(values=[0, 120000], source="new annex")
    compute(data)
    question = next(q for q in data["questions"] if q["id"] == "technician_surcharge")
    assert question["status"] == "answer_added" and question["needsReview"]
    assert question["answers"][0]["value"] == 0 and question["answers"][0]["needsReview"]
    with db.transaction(write=True) as session:
        stored = session.get(db.Case, case["id"])
        payload = copy.deepcopy(stored.data)
        payload["model"], payload["questions"] = data["model"], data["questions"]
        stored.data = payload
    renewed = answer(api.owner, refresh(api.owner, resolved), 120000)
    question = next(q for q in renewed["questions"] if q["id"] == "technician_surcharge")
    assert question["status"] == "resolved" and not question["needsReview"]
    assert len(question["answers"]) == 2 and question["answers"][0]["needsReview"]
    assert not question["answers"][1].get("needsReview")


@pytest.mark.parametrize("shared", [False, True])
def test_answer_tracks_offer_dependencies_without_variable_evidence(api, case, shared):
    with db.transaction(write=True) as session:
        stored = session.get(db.Case, case["id"])
        payload = copy.deepcopy(stored.data)
        variable = next(v for v in payload["model"]["variables"] if v["id"] == "technician_surcharge")
        variable["evidence_ids"] = []
        question = next(q for q in payload["questions"] if q["id"] == "technician_surcharge")
        question.pop("offer_id", None)
        if shared:
            offer = next(o for o in payload["model"]["offers"] if o["id"] == "B")
            item = offer["cost_items"][0]
            item["amount"] = {"op": "sum", "args": [item["amount"], {"op": "var", "name": variable["id"]}]}
        stored.data = payload
    resolved = answer(api.owner, refresh(api.owner, case), 0)
    human = next(f for f in resolved["facts"] if f.get("origin") == "human")
    assert human["dependent_offer_ids"] == (["A", "B"] if shared else ["A"])
    assert human["offer_id"] == (None if shared else "A")
    changed = ok(upload(api.owner, resolved, "Aneks aktualizuje warunki wspólnej dopłaty.", offer="B" if shared else "A"))
    assert next(f for f in changed["facts"] if f["id"] == human["id"])["confirmation"] == "needs_review"
    assert next(q for q in changed["questions"] if q["id"] == "technician_surcharge")["needsReview"]


def test_duplicate_upload_no_new_revision_and_relation_and_mime_validation(api, case):
    first = ok(upload(api.owner, case, "Jednorazowy dokument źródłowy."))
    again = ok(upload(api.owner, first, "Jednorazowy dokument źródłowy."))
    assert again["revision"] == first["revision"]
    assert len(again["documents"]) == len(first["documents"])
    assert upload(api.owner, again, "Niepotwierdzony aneks", relation="annex").status_code == 422
    wrong = api.owner.post(f"/api/cases/{case['id']}/documents", data={"expectedRevision": again["revision"], "offerId": "A"},
                           files={"file": ("fake.pdf", b"This is not a PDF", "application/pdf")})
    assert wrong.status_code == 415


def test_document_deletion_purges_original_history_cache_and_dependents(api, case):
    marker = "unique-private-source-marker-98271"
    case = ok(upload(api.owner, case, marker))
    document = case["documents"][-1]
    with db.transaction(write=True) as session:
        row = session.get(db.Case, case["id"])
        data = copy.deepcopy(row.data)
        data["documents"][-1]["pages"] = [{"text": marker}]
        data["facts"].append({"id": "secret-fact", "key": "note", "value": marker,
                              "offer_id": "A", "evidence": [{"source_id": document["id"], "quote": marker}]})
        # A cached question explanation is derived from the removed source.
        data["questions"].append({"id": "source-question", "text": marker, "source_ids": [document["id"]], "answers": []})
        data["questions"].append({"id": "nested-gap", "text": marker, "issue": {"offer_id": "A", "message": marker}, "answers": []})
        data["facts"].append({"id": "manual-copy", "key": "manual_model", "value": {"nested": marker},
                              "origin": "human", "evidence": [], "critical": True})
        data["model"]["variables"].append({"id": "A:derived", "label": marker, "kind": "open", "values": [], "complete": False})
        # An unprefixed variable may occur only in an offer condition.
        data["model"]["variables"].append({"id": "private-condition", "label": marker,
            "kind": "enum", "values": [False, True], "complete": True, "source": "human assumption"})
        next(o for o in data["model"]["offers"] if o["id"] == "A")["conditions"] = [{"op": "var", "name": "private-condition"}]
        data["facts"].append({"id": "shared-human", "key": "note", "value": marker, "origin": "human",
            "offer_id": None, "dependent_offer_ids": ["A", "B"], "evidence": []})
        row.data = data
        latest = session.scalar(select(db.Revision).where(db.Revision.case_id == case["id"], db.Revision.revision == case["revision"]))
        latest.data = copy.deepcopy(data)
        source_path = Path(data["documents"][-1]["storagePath"])
        identifier = db.uid()
        session.add(db.Job(id=identifier, case_id=case["id"], user_id="owner", input_revision=case["revision"], key=identifier,
                           status="queued", data={"parsed": marker, "extracted": marker}))
    deleted = ok(api.owner.request("DELETE", f"/api/cases/{case['id']}/documents/{document['id']}", json={"expectedRevision": case["revision"]}))
    assert not source_path.exists()
    assert api.owner.get(f"/api/cases/{case['id']}/documents/{document['id']}/file").status_code == 404
    assert marker not in json.dumps(deleted, ensure_ascii=False)
    with db.transaction() as session:
        assert all(marker not in json.dumps(r.data) for r in session.scalars(select(db.Revision).where(db.Revision.case_id == case["id"])))
        job = session.get(db.Job, identifier)
        assert job.cancelled and job.data == {}


def test_case_deletion_purges_all_private_records_and_files(api, case):
    token, case = invite(api.owner, case, "editor")
    identifier = add_job(case)
    path = settings.file_storage / case["id"]
    assert path.exists()
    ok(api.owner.request("DELETE", f"/api/cases/{case['id']}", json={"expectedRevision": case["revision"]}))
    assert not path.exists()
    assert api.owner.get(f"/api/cases/{case['id']}").status_code == 404
    assert api.stranger.post(f"/api/invitations/{token}/accept").status_code == 410
    with db.transaction() as session:
        assert session.get(db.Case, case["id"]) is None
        assert session.get(db.Tombstone, case["id"]) is not None
        assert session.get(db.Job, identifier) is None
        assert list(session.scalars(select(db.Revision).where(db.Revision.case_id == case["id"]))) == []


def test_analysis_consent_idempotency_cancel_and_lease_fencing(api, case):
    path = f"/api/cases/{case['id']}/analysis"
    assert api.owner.post(path, json={"expectedRevision": case["revision"], "consent": False}).status_code == 422
    started = ok(api.owner.post(path, json={"expectedRevision": case["revision"], "consent": True}))
    duplicated = ok(api.owner.post(path, json={"expectedRevision": started["revision"], "consent": True}))
    assert duplicated["revision"] == started["revision"] and len(duplicated["jobs"]) == 1
    identifier = started["jobs"][0]["id"]
    from apps.worker.main import claim_job, update_job
    assert claim_job("worker-one") == identifier
    with pytest.raises(InterruptedError):
        update_job(identifier, "wrong-worker", "saving")
    cancelled = ok(api.owner.post(f"/api/jobs/{identifier}/cancel", json={"expectedRevision": started["revision"]}))
    assert cancelled["jobs"][0]["status"] == "cancelled"
    with pytest.raises(InterruptedError):
        update_job(identifier, "worker-one", "saving")
    assert claim_job("worker-two") is None
    again = ok(api.owner.post(f"/api/jobs/{identifier}/cancel", json={"expectedRevision": cancelled["revision"]}))
    assert again["revision"] == cancelled["revision"]
    completed_id = add_job(cancelled)
    late = api.owner.post(f"/api/jobs/{completed_id}/cancel", json={"expectedRevision": cancelled["revision"]})
    assert late.status_code == 409
    assert next(j for j in refresh(api.owner, case)["jobs"] if j["id"] == completed_id)["status"] == "completed"


@pytest.mark.parametrize("interrupt", ["revision", "cancel"])
def test_worker_cannot_commit_late_model_results(api, case, monkeypatch, interrupt):
    from apps.api import ai, extraction
    from apps.api.service import save
    from apps.worker.main import claim_job, run_job
    case = ok(upload(api.owner, case, "Materiał wymagający nowej analizy.", relation="annex", relationConfirmed="true"))
    case = ok(api.owner.post(f"/api/cases/{case['id']}/analysis", json={"expectedRevision": case["revision"], "consent": True}))
    identifier = case["jobs"][0]["id"]
    assert claim_job("worker-test") == identifier

    def fake_parse(path, mime, source_id, **kwargs):
        return {"pages": [{"number": 1, "source_id": source_id, "text": "Synthetic text", "status": "read"}],
                "complete": True, "parser_version": "test", "issues": []}

    def fake_extract(pages, requirements, offer_id, **kwargs):
        with db.transaction(write=True) as session:
            row = session.get(db.Case, case["id"])
            if interrupt == "revision":
                data = copy.deepcopy(row.data)
                data["title"] = "Nowsza wersja użytkownika"
                save(session, row, data, "owner", "concurrent_user_change")
            else:
                job = session.get(db.Job, identifier)
                job.cancelled, job.status = True, "cancelled"
        return {"facts": [], "domain_offer": {"id": offer_id, "name": "Late replacement", "currency": "PLN", "tax_basis": "gross",
                 "cost_items": [{"id": "late", "amount": {"op": "literal", "value": 1}}]},
                "variables": [], "issues": [], "page_coverage": [], "trace": {"usage": {"input_tokens": 10, "output_tokens": 10}}}

    monkeypatch.setattr(extraction, "parse_document", fake_parse)
    monkeypatch.setattr(ai, "extract_offer", fake_extract)
    run_job(identifier, "worker-test")
    current = refresh(api.owner, case)
    assert all(o["name"] != "Late replacement" for o in current["offers"])
    assert current["jobs"][0]["status"] == ("superseded" if interrupt == "revision" else "cancelled")
    if interrupt == "revision":
        assert current["title"] == "Nowsza wersja użytkownika"


def test_expired_worker_lease_can_be_recovered(api, case):
    from apps.worker.main import claim_job, update_job
    identifier = add_job(case, "queued")
    assert claim_job("old-worker") == identifier
    with db.transaction(write=True) as session:
        session.get(db.Job, identifier).lease_until = time.time() - 1
    assert claim_job("new-worker") == identifier
    with pytest.raises(InterruptedError):
        update_job(identifier, "old-worker", "saving")
    update_job(identifier, "new-worker", "extracting")
    with db.transaction() as session:
        assert session.get(db.Job, identifier).attempts == 2


@pytest.mark.parametrize("completed_before_crash", [False, True])
def test_queued_job_superseded_before_execution_settles_only_completed_usage(api, case, monkeypatch, completed_before_crash):
    from apps.api import ai
    from apps.worker.main import claim_job, run_job
    started = ok(api.owner.post(f"/api/cases/{case['id']}/analysis", json={"expectedRevision": case["revision"], "consent": True}))
    identifier = started["jobs"][0]["id"]
    if completed_before_crash:
        assert claim_job("crashed-worker") == identifier
        with db.transaction(write=True) as session:
            job = session.get(db.Job, identifier)
            job.stage = "saving"
            job.lease_until = time.time() - 1
            job.data = {**job.data, "extracted": {"completed-group": {"trace": {
                "usage_complete": True, "usage": {"input_tokens": 100, "output_tokens": 20}}}}}
    ok(api.owner.patch(f"/api/cases/{case['id']}", json={"expectedRevision": started["revision"], "title": "Nowa wersja przed rozpoczęciem"}))
    monkeypatch.setattr(ai, "extract_offer", lambda *a, **k: pytest.fail("No provider call for stale input"))
    assert claim_job("stale-worker") == identifier
    run_job(identifier, "stale-worker")
    with db.transaction() as session:
        assert session.get(db.Job, identifier).status == "superseded"
        usage = session.scalar(select(db.Usage).where(db.Usage.job_id == identifier))
        assert usage.details["usage_complete"]
        assert usage.details["input_tokens"] == (100 if completed_before_crash else 0)
        assert usage.actual > 0 if completed_before_crash else usage.actual == 0


def test_reclaimed_extraction_retains_unknown_cost_and_rejects_late_settlement(api, case):
    from apps.worker.main import claim_job, settle_usage, update_job
    started = ok(api.owner.post(f"/api/cases/{case['id']}/analysis", json={"expectedRevision": case["revision"], "consent": True}))
    identifier = started["jobs"][0]["id"]
    assert claim_job("old-worker") == identifier
    update_job(identifier, "old-worker", "extracting")
    with db.transaction(write=True) as session:
        session.get(db.Job, identifier).lease_until = time.time() - 1
        usage = session.scalar(select(db.Usage).where(db.Usage.job_id == identifier))
        usage_id = usage.id
    assert claim_job("new-worker") == identifier
    trace = {"usage_complete": True, "usage": {"input_tokens": 100, "output_tokens": 20, "thinking_tokens": 10}}
    settle_usage(usage_id, [trace], job_id=identifier, worker_id="new-worker", claim_attempt=2)
    with db.transaction() as session:
        usage = session.get(db.Usage, usage_id)
        assert usage.actual is None and not usage.details["usage_complete"]
        assert usage.details["thinking_tokens"] == 10
        before = copy.deepcopy(usage.details)
    settle_usage(usage_id, [], job_id=identifier, worker_id="old-worker", claim_attempt=1)
    with db.transaction() as session:
        usage = session.get(db.Usage, usage_id)
        assert usage.actual is None and usage.details == before


@pytest.mark.parametrize("changed_component", ["parser", "ocr_languages"])
def test_worker_discards_persisted_parse_cache_from_an_old_parser(api, case, monkeypatch, changed_component):
    from apps.api import ai, extraction
    from apps.worker.main import claim_job, run_job
    started = ok(api.owner.post(f"/api/cases/{case['id']}/analysis", json={"expectedRevision": case["revision"], "consent": True}))
    identifier = started["jobs"][0]["id"]
    document_id = case["documents"][0]["id"]
    fingerprint = extraction.parser_cache_key()
    with db.transaction(write=True) as session:
        stored = session.get(db.Case, case["id"])
        data = copy.deepcopy(stored.data)
        version = "obsolete-parser" if changed_component == "parser" else extraction.PARSER_VERSION
        data["documents"][0]["parserVersion"] = version
        data["documents"][0]["parserFingerprint"] = fingerprint
        stored.data = data
        job = session.get(db.Job, identifier)
        job.data = {**job.data, "parsed": {document_id: {"pages": data["documents"][0]["pages"],
                    "complete": True, "parser_version": version, "parser_fingerprint": fingerprint, "issues": []}}}
    if changed_component == "ocr_languages":
        monkeypatch.setenv("OCR_LANGUAGES", "eng")
        assert extraction.parser_cache_key() != fingerprint
    calls = []
    def parse(*args, source_id, **kwargs):
        calls.append(source_id)
        raise extraction.DocumentError("test_parse_stop", "Parser was invoked on original source")
    monkeypatch.setattr(extraction, "parse_document", parse)
    monkeypatch.setattr(ai, "extract_offer", lambda *a, **k: pytest.fail("Obsolete cached pages must not reach inference"))
    assert claim_job("parser-worker") == identifier
    run_job(identifier, "parser-worker")
    assert calls == [document_id]
    with db.transaction() as session:
        assert session.get(db.Job, identifier).data["errorType"] == "DocumentError"


@pytest.mark.parametrize("new_blocker", [None, "conflict", "condition_unresolved", "requirements_changed"])
def test_analysis_restores_only_proven_unchanged_facts_after_same_offer_annex(api, case, monkeypatch, new_blocker):
    from apps.api import ai, extraction
    from apps.worker.main import claim_job, run_job
    case = approve(api.owner, case)
    from apps.api.service import affected_offer_ids, extraction_cache_key
    with db.transaction(write=True) as session:
        stored = session.get(db.Case, case["id"])
        seeded = copy.deepcopy(stored.data)
        for document in seeded["documents"]:
            group = [d for d in seeded["documents"] if d["offerId"] == document["offerId"]]
            document["extractionCacheKey"] = extraction_cache_key(group, seeded["requirements"])
        stored.data = seeded
    previous_facts = copy.deepcopy([f for f in case["facts"] if f.get("offer_id") == "A"])
    unchanged = next(f for f in previous_facts if f["key"] == "microphones")
    price = next(f for f in previous_facts if f["key"].startswith("cost:") and type(f["value"]) is int)
    changed = ok(upload(api.owner, case, "Nowa cena pakietu; liczba mikrofonów pozostaje bez zmian.", relation="annex", relationConfirmed="true"))
    assert next(f for f in changed["facts"] if f["id"] == unchanged["id"])["confirmation"] == "needs_review"
    if new_blocker == "requirements_changed":
        changed = ok(api.owner.patch(f"/api/cases/{case['id']}", json={"expectedRevision": changed["revision"],
            "requirements": {**changed["requirements"], "microphones": changed["requirements"]["microphones"] + 1}}))
        assert affected_offer_ids(changed) == {"A", "B", "C"}
    else:
        assert affected_offer_ids(changed) == {"A"}
    calls = []
    def parse(path, mime, source_id, **kwargs):
        return {"pages": [{"source_id": source_id, "number": 1, "text": "Aneks", "status": "read"}],
                "complete": True, "parser_version": extraction.PARSER_VERSION, "issues": []}
    def infer(pages, requirements, offer_id, **kwargs):
        calls.append(offer_id)
        facts = copy.deepcopy([f for f in case["facts"] if f.get("offer_id") == offer_id])
        for fact in facts:
            fact["confirmation"] = "unconfirmed"
            if fact["id"] == price["id"]:
                fact["value"] += 10000
            if fact["id"] == unchanged["id"] and new_blocker in {"conflict", "condition_unresolved"}:
                fact[new_blocker] = True
        return {"facts": facts, "domain_offer": copy.deepcopy(next(o for o in case["offers"] if o["id"] == offer_id)),
            "variables": [], "issues": [], "page_coverage": [{"source_id": p["source_id"], "page": p["number"], "analysis_status": "analyzed"} for p in pages],
            "trace": {"usage_complete": True, "usage": {"input_tokens": 100, "output_tokens": 20}}}
    monkeypatch.setattr(extraction, "parse_document", parse)
    monkeypatch.setattr(ai, "extract_offer", infer)
    started = ok(api.owner.post(f"/api/cases/{case['id']}/analysis", json={"expectedRevision": changed["revision"], "consent": True}))
    identifier = started["jobs"][0]["id"]
    assert claim_job("annex-worker") == identifier
    run_job(identifier, "annex-worker")
    result = refresh(api.owner, case)
    assert result["jobs"][0]["status"] == "completed"
    assert set(calls) == ({"A", "B", "C"} if new_blocker == "requirements_changed" else {"A"})
    restored = next(f for f in result["facts"] if f["id"] == unchanged["id"])
    assert restored["confirmation"] == ("confirmed" if new_blocker is None else "unconfirmed")
    if new_blocker is None:
        assert restored["confirmedBy"] == unchanged["confirmedBy"] and restored["confirmedAt"] == unchanged["confirmedAt"]
    assert next(f for f in result["facts"] if f["id"] == price["id"])["confirmation"] == "unconfirmed"


def test_cost_limit_stops_new_job_without_losing_sources(api, case, monkeypatch):
    monkeypatch.setattr(settings, "case_budget", 0.001)
    result = api.owner.post(f"/api/cases/{case['id']}/analysis", json={"expectedRevision": case["revision"], "consent": True})
    assert result.status_code == 429
    current = refresh(api.owner, case)
    assert current["revision"] == case["revision"]
    assert len(current["documents"]) == len(case["documents"])
    assert not current["jobs"]


def seed_case(case, transform):
    with db.transaction(write=True) as session:
        row = session.get(db.Case, case["id"])
        data = copy.deepcopy(row.data)
        transform(data)
        row.data = data


@pytest.mark.parametrize("quantity,old_price,new_price,expected_cost", [(1, "4200", "4300.01", 490001), (2, "2100", "2200", 500000)])
def test_price_correction_uses_extraction_targets_and_preserves_units_quantity(api, case, quantity, old_price, new_price, expected_cost):
    identifier = "demo-a-price"
    def seed(data):
        fact = next(f for f in data["facts"] if f["id"] == identifier)
        fact.update(key="price", value=old_price, unit="PLN", targets=[{"kind": "cost", "offer_id": "A", "cost_id": "a-set", "field": "amount"}])
        if quantity != 1:
            data["model"]["offers"][0]["cost_items"][0]["amount"] = {"op": "mul", "args": [{"op": "literal", "value": 210000}, {"op": "literal", "value": quantity}]}
    seed_case(case, seed)
    changed = ok(api.owner.patch(f"/api/cases/{case['id']}/facts/{identifier}", json={
        "expectedRevision": case["revision"], "value": new_price, "reason": "Sprawdzona cena jednostkowa w PLN", "confirmation": "confirmed"}))
    assert min(s["costs"]["A"] for s in changed["analysis"]["scenarios"]) == expected_cost
    fact = next(f for f in changed["facts"] if f["id"] == identifier)
    assert fact["origin"] == "human" and fact["author"] == "owner" and fact["evidence"]
    assert fact["previousValues"][-1]["value"] == old_price
    rejected = api.owner.patch(f"/api/cases/{case['id']}/facts/{identifier}", json={
        "expectedRevision": changed["revision"], "value": "-1", "reason": "Błędna kwota", "confirmation": "confirmed"})
    assert rejected.status_code == 422
    assert refresh(api.owner, case)["revision"] == changed["revision"]


def test_variable_and_cost_correction_preserves_dependency_formula(api, case):
    identifier = "demo-a-annex"
    def seed(data):
        fact = next(f for f in data["facts"] if f["id"] == identifier)
        fact.update(key="price", value="1200", unit="PLN", targets=[
            {"kind": "variable", "variable_id": "technician_surcharge", "field": "values"},
            {"kind": "cost", "offer_id": "A", "cost_id": "a-technician", "field": "amount"}])
    seed_case(case, seed)
    changed = ok(api.owner.patch(f"/api/cases/{case['id']}/facts/{identifier}", json={
        "expectedRevision": case["revision"], "value": "700.01", "reason": "Potwierdzona dopłata w PLN", "confirmation": "confirmed"}))
    assert changed["model"]["variables"][0]["values"] == [70001]
    assert changed["offers"][0]["cost_items"][2]["amount"] == {"op": "var", "name": "technician_surcharge"}
    assert changed["analysis"]["scenarios"][0]["costs"]["A"] == 550001
    assert changed["analysis"]["unique_winner"] == "B"


@pytest.mark.parametrize("correction", ["unit", "value"])
def test_real_public_money_representation_corrections_preserve_both_scenarios(api, case, correction):
    snapshot = json.loads((Path(__file__).resolve().parent / "fixtures/public-money-unit-conflicts.json").read_text(encoding="utf-8"))
    seed_case(case, lambda data: data.update({k: snapshot[k] for k in ("requirements", "model", "facts", "questions")}))
    current = refresh(api.owner, case)
    initial_offers = copy.deepcopy(current["model"]["offers"])
    initial_variables = copy.deepcopy(current["model"]["variables"])
    conflicts = [f for f in current["facts"] if f.get("conflict")]
    assert len(conflicts) == 6
    for index, fact in enumerate(conflicts):
        patch = {"unit": "minor"} if correction == "unit" else {"value": fact["value"] // 100}
        current = ok(api.owner.patch(f"/api/cases/{case['id']}/facts/{fact['id']}", json={
            "expectedRevision": current["revision"], "reason": "Sprawdzono kwotę i jednostkę w oryginalnym cytacie",
            "confirmation": "confirmed", **patch}))
        assert current["model"]["offers"] == initial_offers
        assert current["model"]["variables"] == initial_variables
        assert len(current["model"]["issues"]) == 5 - index
        saved = next(item for item in current["facts"] if item["id"] == fact["id"])
        assert saved["correctionKind"] == "money_representation" and saved["conflict"] is False
        assert saved["previousValues"][-1]["value"] == fact["value"]
        assert saved["previousValues"][-1]["unit"] == "PLN"
        assert saved["evidence"] == fact["evidence"] and saved["resolvedIssues"]
    assert current["analysis"]["complete"] and current["analysis"]["status"] == "needs_clarification"
    assert {scenario["costs"]["A"] for scenario in current["analysis"]["scenarios"]} == {480000, 600000}
    current = approve(api.owner, current)
    assert current["model"]["variables"] == initial_variables
    variable_id = initial_variables[0]["id"]
    current = ok(api.owner.post(f"/api/cases/{case['id']}/questions/{variable_id}/answers", json={
        "expectedRevision": current["revision"], "kind": "value", "value": 0, "confirmed": True,
        "text": "Osobna późniejsza odpowiedź wykonawcy: technik jest już w cenie"}))
    current = approve(api.owner, current)
    assert current["model"]["variables"][0]["values"] == [0]
    assert current["analysis"]["unique_winner"] == "A"


def test_unit_correction_rejects_unsupported_amount_and_preserves_other_gaps(api, case):
    identifier = "demo-a-price"
    def seed(data):
        fact = next(f for f in data["facts"] if f["id"] == identifier)
        fact.update(key="price", value=420000, unit="PLN", conflict=True,
                    targets=[{"kind": "cost", "offer_id": "A", "cost_id": "a-set", "field": "amount"}])
        data["model"]["issues"] = [{"code": "extraction_gap", "offer_id": "A", "message": "conflict:money_unit:" + identifier},
                                     {"code": "extraction_gap", "offer_id": "A", "message": "unrelated_gap"}]
    seed_case(case, seed)
    path = f"/api/cases/{case['id']}/facts/{identifier}"
    rejected = api.owner.patch(path, json={"expectedRevision": case["revision"], "unit": "major", "reason": "Niepoprawna jednostka"})
    assert rejected.status_code == 422
    assert refresh(api.owner, case)["revision"] == case["revision"]
    changed = ok(api.owner.patch(path, json={"expectedRevision": case["revision"], "unit": "minor", "reason": "Kwota źródłowa 4200 PLN"}))
    assert [issue["message"] for issue in changed["model"]["issues"]] == ["unrelated_gap"]
    assert changed["analysis"]["complete"] is False


@pytest.mark.parametrize("after_annex,legacy_duplicate", [(False, False), (True, False), (True, True)])
def test_reanalysis_keeps_one_active_fact_and_human_correction_provenance(api, case, monkeypatch, after_annex, legacy_duplicate):
    from apps.api import ai
    from apps.worker.main import claim_job, run_job
    original = json.loads((Path(__file__).resolve().parent / "fixtures/public-money-unit-conflicts.json").read_text(encoding="utf-8"))
    seed_case(case, lambda data: data.update({k: original[k] for k in ("requirements", "model", "facts", "questions")}))
    current = refresh(api.owner, case)
    corrected_ids = [fact["id"] for fact in current["facts"] if fact.get("conflict")]
    for identifier in corrected_ids:
        current = ok(api.owner.patch(f"/api/cases/{case['id']}/facts/{identifier}", json={
            "expectedRevision": current["revision"], "unit": "minor", "reason": "Sprawdzona reprezentacja kwoty ze źródła"}))
    initial_variables = copy.deepcopy(current["model"]["variables"])
    if legacy_duplicate:
        seed_case(case, lambda data: data["facts"].extend(copy.deepcopy([f for f in original["facts"] if f["id"] in corrected_ids])))
        current = refresh(api.owner, case)
    if after_annex:
        current = ok(upload(api.owner, current, "Nowy załącznik nie zmienia kwot.", relation="annex", relationConfirmed="true"))

    def replay(pages, requirements, offer_id, **kwargs):
        return {"facts": copy.deepcopy([fact for fact in original["facts"] if fact.get("offer_id") == offer_id]),
                "domain_offer": copy.deepcopy(next(offer for offer in original["model"]["offers"] if offer["id"] == offer_id)),
                "variables": copy.deepcopy([v for v in original["model"]["variables"] if v["id"].startswith(offer_id + ":")]),
                "issues": [issue["message"] for issue in original["model"]["issues"] if issue["offer_id"] == offer_id],
                "page_coverage": [{"source_id": page["source_id"], "page": page["number"], "analysis_status": "analyzed"} for page in pages],
                "trace": {"usage_complete": True, "usage": {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0}}}
    monkeypatch.setattr(ai, "extract_offer", replay)
    started = ok(api.owner.post(f"/api/cases/{case['id']}/analysis", json={"expectedRevision": current["revision"], "consent": True}))
    identifier = started["jobs"][0]["id"]
    assert claim_job("human-replay") == identifier
    run_job(identifier, "human-replay")
    current = refresh(api.owner, case)
    assert current["jobs"][0]["status"] == "completed", current["jobs"][0]
    ids = [fact["id"] for fact in current["facts"]]
    assert len(ids) == len(set(ids)) == len(original["facts"])
    for identifier in corrected_ids:
        fact = next(f for f in current["facts"] if f["id"] == identifier)
        assert fact["origin"] == "human" and fact["unit"] == "minor" and fact["author"] == "owner"
        assert fact["previousValues"][-1]["unit"] == "PLN"
        assert fact["latestSourceInterpretation"]["unit"] == "PLN"
        if fact["offer_id"] == "A":
            assert fact["confirmation"] == ("needs_review" if after_annex else "confirmed")
    if not after_annex:
        assert not current["model"]["issues"] and current["analysis"]["complete"]
    current = approve(api.owner, current)
    assert current["analysis"]["complete"]
    assert current["model"]["variables"] == initial_variables


def test_human_resolution_clears_only_matching_model_gap_and_validates_type(api, case):
    identifier = "demo-a-microphones"
    def seed(data):
        fact = next(f for f in data["facts"] if f["id"] == identifier)
        fact.update(value=3, conflict=True, targets=[{"kind": "offer", "offer_id": "A", "field": "microphones"}])
        data["model"]["offers"][0]["microphones"] = None
        data["model"]["issues"] = [{"code": "extraction_gap", "message": "conflict:microphones", "offer_id": "A"}]
    seed_case(case, seed)
    path = f"/api/cases/{case['id']}/facts/{identifier}"
    bad = api.owner.patch(path, json={"expectedRevision": case["revision"], "value": "four", "reason": "Błędny typ"})
    assert bad.status_code == 422
    changed = ok(api.owner.patch(path, json={"expectedRevision": case["revision"], "value": 4, "reason": "Wyjaśniony wariant czterech mikrofonów"}))
    assert changed["offers"][0]["microphones"] == 4
    assert not changed["model"]["issues"]
    assert changed["analysis"]["complete"]
    assert next(f for f in changed["facts"] if f["id"] == identifier)["resolvedIssues"]


def test_pair_question_answers_update_both_variables_atomically(api, case):
    def seed(data):
        variable = data["model"]["variables"][0]
        variable["values"] = [0, 120000]
        data["model"]["variables"].append({"id": "transport_surcharge", "kind": "enum", "values": [0, 10000], "complete": True, "unit": "minor"})
        data["model"]["offers"][0]["cost_items"].append({"id": "transport_extra", "amount": {"op": "var", "name": "transport_surcharge"}})
        data["questions"].append({"id": "technician_surcharge+transport_surcharge", "variable_ids": ["technician_surcharge", "transport_surcharge"],
                                  "kind": "pair", "text": "Dwie powiązane dopłaty", "answers": [], "status": "prepared"})
    seed_case(case, seed)
    path = f"/api/cases/{case['id']}/questions/technician_surcharge+transport_surcharge/answers"
    incomplete = api.owner.post(path, json={"expectedRevision": case["revision"], "text": "Niepełna para", "kind": "value", "confirmed": True,
                                          "value": {"technician_surcharge": 0}})
    assert incomplete.status_code == 422
    assert refresh(api.owner, case)["revision"] == case["revision"]
    changed = ok(api.owner.post(path, json={"expectedRevision": case["revision"], "text": "Technik i transport w cenie", "kind": "value", "confirmed": True,
                                          "value": {"technician_surcharge": 0, "transport_surcharge": 0}}))
    assert all(v["values"] == [0] for v in changed["model"]["variables"])
    assert changed["analysis"]["unique_winner"] == "A"
    assert len([f for f in changed["facts"] if f.get("origin") == "human"]) == 2
    assert next(q for q in changed["questions"] if q["id"].endswith("+transport_surcharge"))["status"] == "resolved"


def test_final_decision_revalidates_already_confirmed_source_evidence(api, case):
    case = approve(api.owner, case)
    def seed(data):
        data["facts"][0]["evidence"][0]["quote_validated"] = False
    seed_case(case, seed)
    response = api.owner.post(f"/api/cases/{case['id']}/decisions", json=decision_body(case, "B"))
    assert response.status_code == 422
    assert not refresh(api.owner, case)["decisions"]


@pytest.mark.parametrize("revocation", ["logout", "expiry"])
def test_open_sse_stream_stops_when_server_session_is_revoked(api, case, revocation):
    from starlette.requests import Request
    from apps.api.routes import job_events
    identifier = add_job(case, "running")
    cookie = api.owner.cookies.get("kontroferta_session")
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    async def exercise():
        request = Request({"type": "http", "method": "GET", "path": f"/api/jobs/{identifier}/events",
                           "headers": [(b"cookie", f"kontroferta_session={cookie}".encode())], "session": {"user_id": "owner"}}, receive)
        response = await job_events(identifier, request)
        assert "event: job" in await anext(response.body_iterator)
        with db.transaction(write=True) as session:
            row = session.get(db.WebSession, session_key(cookie))
            if revocation == "logout":
                session.delete(row)
            else:
                row.expires = time.time() - 1
        with pytest.raises(StopAsyncIteration):
            await anext(response.body_iterator)
    asyncio.run(exercise())


def test_explicit_offer_exclusion_limits_required_confirmations_and_can_be_undone(api, case):
    path = f"/api/cases/{case['id']}"
    excluded = ok(api.owner.patch(path + "/offers/A/exclusion", json={
        "expectedRevision": case["revision"], "excluded": True, "reason": "Wybieram spośród ofert B i C; brak wyjaśnienia A."}))
    assert excluded["analysis"]["unique_winner"] == "B"
    approved = ok(api.owner.post(path + "/approvals", json={"expectedRevision": excluded["revision"],
        "factIds": [f["id"] for f in excluded["facts"] if f.get("offer_id") != "A"], "requirementsConfirmed": True}))
    decided = ok(api.owner.post(path + "/decisions", json=decision_body(approved, "B")))
    assert decided["analysis"]["scope"]["limited"]
    assert decided["decisions"][-1]["current"]
    restored = ok(api.owner.patch(path + "/offers/A/exclusion", json={
        "expectedRevision": decided["revision"], "excluded": False, "reason": "Przywracam pełny zakres."}))
    assert not restored["decisions"][-1]["current"]
    assert restored["analysis"]["status"] == "needs_clarification"
    assert api.owner.post(path + "/decisions", json=decision_body(restored, "B")).status_code == 422


def test_consistent_backup_restore_reapplies_source_and_case_deletions(api, case, tmp_path):
    import sqlite3
    from scripts.backup import backup, restore
    marker = "deleted-source-backup-marker-782613"
    case = ok(upload(api.owner, case, marker))
    source_id = case["documents"][-1]["id"]
    discarded = ok(api.stranger.post("/api/cases/demo"))
    retained = ok(api.owner.post("/api/cases/demo"))
    retained = approve(api.owner, retained)
    retained = ok(api.owner.post(f"/api/cases/{retained['id']}/decisions", json=decision_body(retained, "B")))
    archive = tmp_path / "backup"
    manifest = backup(archive)
    assert manifest["files"] and manifest["schema"] == "0002"
    case = ok(api.owner.request("DELETE", f"/api/cases/{case['id']}/documents/{source_id}", json={"expectedRevision": case["revision"]}))
    ok(api.stranger.request("DELETE", f"/api/cases/{discarded['id']}", json={"expectedRevision": discarded["revision"]}))
    restored = tmp_path / "restored"
    result = restore(archive, restored, Path(db.engine.url.database))
    assert result["deletedCasesReapplied"] == 1 and result["deletedSourcesReapplied"] == 1
    assert not (restored / "files" / discarded["id"]).exists()
    assert not any(p.stem == source_id for p in (restored / "files" / case["id"]).iterdir())
    with sqlite3.connect(restored / "database.sqlite") as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM cases WHERE id=?", (discarded["id"],)).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM deletions WHERE case_id=?", (discarded["id"],)).fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM source_deletions WHERE document_id=?", (source_id,)).fetchone()[0] == 1
        data = json.loads(connection.execute("SELECT data FROM cases WHERE id=?", (case["id"],)).fetchone()[0])
        assert data["pendingAnalysis"] and source_id not in {d["id"] for d in data["documents"]}
        safe = json.loads(connection.execute("SELECT data FROM cases WHERE id=?", (retained["id"],)).fetchone()[0])
        assert safe["decisions"][-1]["current"] and safe["decisions"][-1]["offerId"] == "B"
        assert all(Path(d["storagePath"]).is_file() for d in safe["documents"])
        assert all(marker not in row[0] for row in connection.execute("SELECT data FROM revisions"))
    assert marker.encode() not in (restored / "database.sqlite").read_bytes()
    # Persisting the live registry in the restored database protects a second restore.
    second = tmp_path / "restored-again"
    again = restore(archive, second, restored / "database.sqlite")
    assert again["deletedCasesReapplied"] == 1 and again["deletedSourcesReapplied"] == 1
    # A backup made after deletion may contain a newly reviewed model. The
    # deletion marker alone must not invalidate that later work on restore.
    with db.transaction(write=True) as session:
        stored = session.get(db.Case, case["id"])
        data = copy.deepcopy(stored.data)
        rebuilt = next(o for o in data["model"]["offers"] if o["id"] == "A")
        rebuilt.update(name="Ponownie sprawdzona oferta A", scope_confirmed=True,
                       cost_items=[{"id": "new-price", "amount": {"op": "literal", "value": 1100000}}])
        data["pendingAnalysis"] = False
        data["decisions"] = [{"current": True, "offerId": "A", "reason": "Odtworzono z pozostałych źródeł."}]
        stored.data = data
    recent_archive = tmp_path / "backup-after-deletion"
    backup(recent_archive)
    recent = tmp_path / "restore-rebuilt-model"
    recent_result = restore(recent_archive, recent, Path(db.engine.url.database))
    assert recent_result["sourceCasesRevised"] == 0
    with sqlite3.connect(recent / "database.sqlite") as connection:
        data = json.loads(connection.execute("SELECT data FROM cases WHERE id=?", (case["id"],)).fetchone()[0])
        assert not data["pendingAnalysis"] and data["decisions"][-1]["current"]
        assert next(o for o in data["model"]["offers"] if o["id"] == "A")["cost_items"][0]["amount"]["value"] == 1100000


@pytest.mark.parametrize("failure", ["parser", "provider_unknown_usage"])
def test_worker_settles_failed_preprocessing_but_preserves_unknown_provider_cost(api, case, monkeypatch, failure):
    from apps.api import ai, extraction
    from apps.worker.main import claim_job, run_job
    case = ok(upload(api.owner, case, "Nowy dokument do weryfikacji kosztów błędu."))
    def seed(data):
        for document in data["documents"]:
            document["pages"] = []
    seed_case(case, seed)
    case = ok(api.owner.post(f"/api/cases/{case['id']}/analysis", json={"expectedRevision": case["revision"], "consent": True}))
    identifier = case["jobs"][0]["id"]
    assert claim_job("billing-worker") == identifier
    def fake_parse(path, mime, source_id, **kwargs):
        if failure == "parser":
            raise extraction.DocumentError("parser_timeout", "Przekroczono czas lokalnego odczytu.")
        return {"pages": [{"number": 1, "source_id": source_id, "text": "Synthetic text", "status": "read"}],
                "complete": True, "parser_version": "test", "issues": []}
    def fake_extract(*args, **kwargs):
        if failure == "parser":
            pytest.fail("Local parser failure must stop before a provider call")
        raise ai.AIError("timeout", "Brak odpowiedzi po wysłaniu żądania.", trace={
            "usage_complete": False, "usage": {"input_tokens": 0, "output_tokens": 0},
            "attempts": [{"status": "timeout"}]})
    monkeypatch.setattr(extraction, "parse_document", fake_parse)
    monkeypatch.setattr(ai, "extract_offer", fake_extract)
    run_job(identifier, "billing-worker")
    with db.transaction() as session:
        usage = session.scalar(select(db.Usage).where(db.Usage.job_id == identifier))
        assert usage.actual == 0 if failure == "parser" else usage.actual is None
        assert usage.reserved > 0
    current = refresh(api.owner, case)
    assert current["jobs"][0]["status"] == "failed"
    assert current["pendingAnalysis"] and len(current["documents"]) == len(case["documents"])


def test_worker_extracts_offer_groups_with_bounded_parallelism(api, case, monkeypatch):
    import threading
    from apps.api import ai
    from apps.worker import main as worker
    monkeypatch.setenv("AI_MAX_CONCURRENCY", "2")
    monkeypatch.setattr(worker, "AI_SLOTS", threading.BoundedSemaphore(2))
    gate, lock = threading.Event(), threading.Lock()
    calls = {"active": 0, "peak": 0, "offers": []}
    def fake_extract(pages, requirements, offer_id, **kwargs):
        with lock:
            calls["active"] += 1
            calls["peak"] = max(calls["peak"], calls["active"])
            calls["offers"].append(offer_id)
            if calls["active"] == 2:
                gate.set()
        gate.wait(3)
        time.sleep(0.05)
        with lock:
            calls["active"] -= 1
        domain_offer = copy.deepcopy(next(o for o in case["offers"] if o["id"] == offer_id))
        facts = copy.deepcopy([f for f in case["facts"] if f.get("offer_id") == offer_id])
        return {"facts": facts, "domain_offer": domain_offer, "variables": [], "issues": [],
                "page_coverage": [{"source_id": p["source_id"], "page": p["number"], "analysis_status": "analyzed"} for p in pages],
                "trace": {"usage_complete": True, "usage": {"input_tokens": 10, "output_tokens": 10}}}
    monkeypatch.setattr(ai, "extract_offer", fake_extract)
    started = ok(api.owner.post(f"/api/cases/{case['id']}/analysis", json={"expectedRevision": case["revision"], "consent": True}))
    identifier = started["jobs"][0]["id"]
    assert worker.claim_job("parallel-test") == identifier
    worker.run_job(identifier, "parallel-test")
    current = refresh(api.owner, case)
    assert calls["peak"] == 2 and set(calls["offers"]) == {"A", "B", "C"}
    assert current["jobs"][0]["status"] == "completed"
    assert not current["pendingAnalysis"]
    with db.transaction() as session:
        usage = session.scalar(select(db.Usage).where(db.Usage.job_id == identifier))
        assert usage.actual is not None and usage.details["input_tokens"] == 30


@pytest.mark.parametrize("trigger", ["cancel", "delete_source"])
def test_queued_cancellation_releases_reservation_before_any_worker_attempt(api, case, trigger):
    started = ok(api.owner.post(f"/api/cases/{case['id']}/analysis", json={"expectedRevision": case["revision"], "consent": True}))
    identifier = started["jobs"][0]["id"]
    if trigger == "cancel":
        ok(api.owner.post(f"/api/jobs/{identifier}/cancel", json={"expectedRevision": started["revision"]}))
    else:
        ok(api.owner.request("DELETE", f"/api/cases/{case['id']}/documents/{case['documents'][0]['id']}",
                             json={"expectedRevision": started["revision"]}))
    with db.transaction() as session:
        usage = session.scalar(select(db.Usage).where(db.Usage.job_id == identifier))
        assert usage.reserved > 0 and usage.actual == 0
        assert usage.details["cost_type"] == "cancelled_before_execution"


def test_retry_reuses_completed_groups_and_reserves_and_bills_only_missing_offer(api, case, monkeypatch):
    from apps.api import ai, extraction
    from apps.worker import main as worker
    from apps.api.service import extraction_cache_key
    calls = []
    failed_once = {"B": False}
    def fake_extract(pages, requirements, offer_id, **kwargs):
        calls.append(offer_id)
        if offer_id == "B" and not failed_once["B"]:
            failed_once["B"] = True
            raise ai.AIError("temporary_failure", "Przejściowy błąd jednej oferty", trace={"usage_complete": True,
                "attempts": [{"status": "error", "usage": {"input_tokens": 0, "output_tokens": 0}}]})
        return {"facts": copy.deepcopy([f for f in case["facts"] if f.get("offer_id") == offer_id]),
                "domain_offer": copy.deepcopy(next(o for o in case["offers"] if o["id"] == offer_id)),
                "variables": [], "issues": [],
                "page_coverage": [{"source_id": p["source_id"], "page": p["number"], "analysis_status": "analyzed"} for p in pages],
                "trace": {"usage_complete": True, "usage": {"input_tokens": 100, "output_tokens": 20}}}
    monkeypatch.setattr(ai, "extract_offer", fake_extract)
    started = ok(api.owner.post(f"/api/cases/{case['id']}/analysis", json={"expectedRevision": case["revision"], "consent": True}))
    first_id = started["jobs"][0]["id"]
    assert worker.claim_job("cache-worker") == first_id
    worker.run_job(first_id, "cache-worker")
    failed = refresh(api.owner, case)
    assert failed["jobs"][0]["status"] == "failed" and set(calls) == {"A", "B", "C"}
    retried = ok(api.owner.post(f"/api/cases/{case['id']}/analysis", json={"expectedRevision": failed["revision"], "consent": True}))
    second_id = retried["jobs"][0]["id"]
    with db.transaction() as session:
        first_usage = session.scalar(select(db.Usage).where(db.Usage.job_id == first_id))
        second_usage = session.scalar(select(db.Usage).where(db.Usage.job_id == second_id))
        assert first_usage.actual is not None and first_usage.details["input_tokens"] == 200
        assert 0 < second_usage.reserved < first_usage.reserved
        job = session.get(db.Job, second_id)
        assert len(job.data["parsed"]) == 4
        assert len(job.data["prepaidGroupKeys"]) == len(job.data["extracted"]) == 2
        assert job.data["resumedFromJob"] == first_id
        documents = session.get(db.Case, case["id"]).data["documents"]
        assert extraction_cache_key([d for d in documents if d["offerId"] == "A"], case["requirements"]) in job.data["prepaidGroupKeys"]
    monkeypatch.setattr(extraction, "parse_document", lambda *a, **k: pytest.fail("Completed parsed documents must survive retry"))
    assert worker.claim_job("cache-worker") == second_id
    worker.run_job(second_id, "cache-worker")
    assert calls.count("A") == 1 and calls.count("C") == 1 and calls.count("B") == 2
    assert refresh(api.owner, case)["jobs"][0]["status"] == "completed"
    with db.transaction() as session:
        usage = session.scalar(select(db.Usage).where(db.Usage.job_id == second_id))
        assert usage.actual is not None and usage.details["input_tokens"] == 100


@pytest.mark.parametrize("error_number,status,code", [(28, 507, "storage_full"), (13, 503, "storage_unavailable")])
def test_failed_upload_removes_partial_file_preserves_approved_revision_and_allows_retry(api, case, monkeypatch, error_number, status, code):
    case = approve(api.owner, answer(api.owner, case, 0))
    case = ok(api.owner.post(f"/api/cases/{case['id']}/decisions", json=decision_body(case)))
    original = next(document for document in case["documents"] if document["offerId"] == "A")
    folder = settings.file_storage / case["id"]
    existing_files = {file.name: file.read_bytes() for file in folder.iterdir() if file.is_file()}
    original_write = Path.write_bytes

    def fail_after_partial_write(path, content):
        if path.parent == folder:
            original_write(path, content[:3])
            raise OSError(error_number, "simulated private filesystem failure")
        return original_write(path, content)

    monkeypatch.setattr(Path, "write_bytes", fail_after_partial_write)
    failed = upload(api.owner, case, "Nowa cena zastępuje dokument.", relation="replacement", replacesId=original["id"], relationConfirmed="true")
    assert failed.status_code == status
    assert failed.json()["detail"]["code"] == code
    unchanged = refresh(api.owner, case)
    assert unchanged["revision"] == case["revision"]
    assert unchanged["documents"] == case["documents"]
    assert unchanged["facts"] == case["facts"]
    assert unchanged["decisions"] == case["decisions"]
    assert unchanged["decisions"][-1]["current"] is True
    assert {file.name: file.read_bytes() for file in folder.iterdir() if file.is_file()} == existing_files

    monkeypatch.setattr(Path, "write_bytes", original_write)
    retried = ok(upload(api.owner, unchanged, "Nowa cena zastępuje dokument.", relation="replacement", replacesId=original["id"], relationConfirmed="true"))
    assert retried["revision"] == case["revision"] + 1
    assert next(document for document in retried["documents"] if document["id"] == original["id"])["active"] is False
    assert retried["pendingAnalysis"] is True


@pytest.mark.parametrize("usage_known", [True, False])
def test_requirement_proposal_failure_settles_known_usage_and_keeps_unknown_cost_reserved(api, case, monkeypatch, usage_known):
    from apps.api import ai

    def fail_proposal(description):
        trace = {"usage_complete": True, "usage": {"input_tokens": 100, "output_tokens": 50, "thinking_tokens": 0}}
        raise ai.AIError("invalid_schema", "Niepoprawny wynik propozycji wymagań.", trace=trace if usage_known else None)

    monkeypatch.setattr(ai, "propose_requirements", fail_proposal)
    response = api.owner.post(f"/api/cases/{case['id']}/requirements/propose", json={
        "expectedRevision": case["revision"], "text": "Konferencja dla 120 uczestników.", "consent": True})
    assert response.status_code == 502 and response.json()["detail"]["code"] == "invalid_schema"
    unchanged = refresh(api.owner, case)
    assert unchanged["revision"] == case["revision"]
    assert unchanged["requirements"] == case["requirements"]
    with db.transaction() as session:
        usage = session.scalar(select(db.Usage).where(db.Usage.case_id == case["id"]))
        assert usage.details["usage_complete"] is usage_known
        if usage_known:
            assert usage.actual == pytest.approx((100 * settings.input_price + 50 * settings.output_price) / 1_000_000)
        else:
            assert usage.actual is None and usage.reserved == .12
