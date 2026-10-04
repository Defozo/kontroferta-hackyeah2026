import asyncio
import copy
import errno
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import select

from .auth import current_user, is_guest
from .config import ROOT, settings
from .db import Case, DocumentTombstone, Invitation, Job, Member, Revision, WebSession, digest, now, transaction, uid
from .schemas import (AnalysisInput, AnswerInput, ApprovalInput, CaseDetail, CreateCase, CreateOffer,
    DecisionInput, DeleteInput, ExcludeInput, InvitationInput, ModelInput, QuestionInput,
    Recalculate, RequirementsProposal, UndoInput, UpdateCase, UpdateFact, Write)
from .service import (apply_fact, compute, delete_case, detail, empty_data, expect, fact_fingerprint,
    extraction_cache_key, fail, get_case, invalidate, job_public, normalize_requirements, purge_source, reserve_usage, save, snapshot,
        validate_fact_confirmation, variable_offer_dependencies, release_unstarted_usage, affected_offer_ids)

router = APIRouter(prefix="/api", tags=["Cases"])


@router.get("/cases")
def list_cases(request: Request):
    user = current_user(request)
    with transaction() as db:
        memberships = {m.case_id: m.role for m in db.scalars(select(Member).where(Member.user_id == user.id))}
        cases = db.scalars(select(Case).where((Case.owner_id == user.id) | Case.id.in_(memberships)).order_by(Case.updated_at.desc()))
        return {"cases": [{"id": c.id, "title": c.title, "revision": c.revision, "updatedAt": c.updated_at,
                           "status": "pending_analysis" if c.data.get("pendingAnalysis") else (c.data.get("analysis") or {}).get("status", "draft"),
                           "role": "owner" if c.owner_id == user.id else memberships[c.id]} for c in cases]}


@router.post("/cases", response_model=CaseDetail)
def create_case(body: CreateCase, request: Request):
    user = current_user(request)
    if is_guest(user):
        fail("guest_demo_only", "W publicznym demo użyj importu dokumentów demonstracyjnych.", 403)
    if body.expectedRevision != 0:
        fail("invalid_revision", "Nowa sprawa wymaga wersji 0.", 409)
    with transaction(write=True) as db:
        case = Case(id=uid(), owner_id=user.id, title=body.title, revision=1, data=empty_data(body.title, body.requirements))
        db.add(case)
        snapshot(db, case, user.id, "case_created")
        db.flush()
        return detail(db, case, "owner")


@router.post("/cases/demo", response_model=CaseDetail)
def clone_demo(request: Request):
    from .demo import demo_data
    user = current_user(request)
    if is_guest(user):
        return fresh_demo(request)
    with transaction(write=True) as db:
        data = demo_data()
        data.pop("recordedDemo", None)
        data["requirements"]["confirmed"] = False
        for fact in data["facts"]:
            fact["confirmation"] = "proposed"
            fact.pop("confirmedBy", None)
        data["approval"] = None
        case_id = uid()
        target = settings.file_storage / case_id
        target.mkdir(parents=True, exist_ok=True)
        for doc in data["documents"]:
            import shutil
            destination = target / (doc["id"] + Path(doc["name"]).suffix)
            shutil.copyfile(doc["storagePath"], destination)
            doc["storagePath"] = str(destination)
        data["title"] = "Forum organizatorów · przykład AV"
        case = Case(id=case_id, owner_id=user.id, title=data["title"], revision=1, data=data, demo=True)
        db.add(case)
        snapshot(db, case, user.id, "synthetic_demo_copied")
        db.flush()
        return detail(db, case, "owner")


@router.post("/cases/demo-fresh", response_model=CaseDetail)
def fresh_demo(request: Request):
    from .demo import demo_data
    import shutil
    user = current_user(request)
    with transaction(write=True) as db:
        if is_guest(user) and len(list(db.scalars(select(Case.id).where(Case.owner_id == user.id)))) >= settings.guest_max_cases:
            fail("guest_case_limit", "W tej sesji możesz mieć dwie sprawy demonstracyjne. Usuń jedną, aby zacząć ponownie.", 429)
        template = demo_data()
        data = empty_data("Forum organizatorów, analiza demonstracyjna", template["requirements"])
        data["requirements"]["confirmed"] = False
        data["model"]["offers"] = [{"id": offer["id"], "name": offer["name"], "cost_items": []}
                                    for offer in template["model"]["offers"]]
        data["pendingAnalysis"] = True
        identifier = uid()
        target = settings.file_storage / identifier
        try:
            target.mkdir(parents=True, exist_ok=True)
            for source in template["documents"]:
                doc = {key: copy.deepcopy(value) for key, value in source.items()
                       if key in {"id", "offerId", "name", "mime", "sha256", "bytes", "author", "documentDate",
                                  "version", "relation", "relationConfirmed", "active"}}
                destination = target / (doc["id"] + Path(doc["name"]).suffix)
                shutil.copyfile(source["storagePath"], destination)
                doc.update({"storagePath": str(destination), "addedBy": user.id, "addedAt": now(),
                            "status": "pending", "pages": []})
                data["documents"].append(doc)
            case = Case(id=identifier, owner_id=user.id, title=data["title"], revision=1, data=data, demo=True)
            db.add(case)
            snapshot(db, case, user.id, "synthetic_sources_imported")
            db.flush()
            return detail(db, case, "owner")
        except Exception:
            if target.exists() and target.parent.resolve() == settings.file_storage.resolve():
                shutil.rmtree(target)
            raise


@router.get("/cases/{case_id}", response_model=CaseDetail)
def read_case(case_id: str, request: Request):
    with transaction() as db:
        case, role = get_case(db, case_id, current_user(request))
        return detail(db, case, role)


@router.patch("/cases/{case_id}", response_model=CaseDetail)
def update_case(case_id: str, body: UpdateCase, request: Request):
    user = current_user(request)
    with transaction(write=True) as db:
        case, role = get_case(db, case_id, user, write=True)
        expect(case, body.expectedRevision)
        data = copy.deepcopy(case.data)
        if body.title is not None:
            data["title"] = body.title
        if body.requirements is not None:
            data["requirements"] = normalize_requirements(body.requirements)
            data["requirements"]["confirmed"] = False
            invalidate(data, "Zmieniono wymagania wydarzenia.", all_facts=True)
            compute(data)
        save(db, case, data, user.id, "requirements_updated" if body.requirements else "case_renamed")
        return detail(db, case, role)


@router.delete("/cases/{case_id}")
def remove_case(case_id: str, body: DeleteInput, request: Request):
    user = current_user(request)
    with transaction(write=True) as db:
        case, _ = get_case(db, case_id, user, owner=True)
        expect(case, body.expectedRevision)
        delete_case(db, case)
    return {"deleted": True}


@router.post("/cases/{case_id}/offers", response_model=CaseDetail)
def create_offer(case_id: str, body: CreateOffer, request: Request):
    user = current_user(request)
    with transaction(write=True) as db:
        case, role = get_case(db, case_id, user, write=True)
        expect(case, body.expectedRevision)
        data = copy.deepcopy(case.data)
        data["model"]["offers"].append({"id": uid(), "name": body.name, "cost_items": []})
        invalidate(data, "Dodano ofertę do porównania.")
        compute(data)
        save(db, case, data, user.id, "offer_created")
        return detail(db, case, role)


@router.patch("/cases/{case_id}/offers/{offer_id}/exclusion", response_model=CaseDetail)
def exclude_offer(case_id: str, offer_id: str, body: ExcludeInput, request: Request):
    user = current_user(request)
    with transaction(write=True) as db:
        case, role = get_case(db, case_id, user, write=True)
        expect(case, body.expectedRevision)
        data = copy.deepcopy(case.data)
        offer = next((o for o in data["model"]["offers"] if o["id"] == offer_id), None)
        if not offer:
            fail("not_found", "Nie znaleziono oferty.", 404)
        offer["excluded_reason"] = body.reason if body.excluded else None
        invalidate(data, "Zmieniono zakres porównania.")
        compute(data)
        save(db, case, data, user.id, "offer_exclusion_changed")
        return detail(db, case, role)


@router.post("/cases/{case_id}/documents", response_model=CaseDetail)
async def upload_document(case_id: str, request: Request,
    expectedRevision: Annotated[int, Form()], offerId: Annotated[str, Form()],
    file: Annotated[UploadFile | None, File()] = None, text: Annotated[str | None, Form()] = None,
    author: Annotated[str, Form()] = "", documentDate: Annotated[str, Form()] = "",
    relation: Annotated[str, Form()] = "offer", replacesId: Annotated[str | None, Form()] = None,
    relationConfirmed: Annotated[str, Form()] = "false"):
    user = current_user(request)
    if relation not in {"offer", "annex", "replacement", "answer"}:
        fail("invalid_relation", "Nieznana relacja dokumentu.")
    if relation in {"annex", "replacement"} and relationConfirmed != "true":
        fail("relation_confirmation", "Potwierdź powiązanie aneksu lub zastąpienie wersji.")
    with transaction() as db:
        case, _ = get_case(db, case_id, user, write=True)
        expect(case, expectedRevision)
    if file:
        content = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
        name = Path(file.filename or "document").name
        mime = file.content_type
    elif text and text.strip():
        content, name, mime = text.encode(), "odpowiedz.txt", "text/plain"
    else:
        fail("empty_document", "Dodaj plik lub tekst.")
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        fail("upload_limit", f"Plik przekracza limit {settings.max_upload_mb} MB.", 413)
    if len(name) > 240:
        name = name[:200] + Path(name).suffix
    source_hash = hashlib.sha256(content).hexdigest()
    if is_guest(user):
        allowed_hashes = {hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / "fixtures/demo").glob("*.pdf")}
        if source_hash not in allowed_hashes:
            fail("guest_synthetic_only", "Publiczne demo przyjmuje tylko udostępnione syntetyczne pliki PDF. Pobierz je z zapisanego przykładu.", 403)
    with transaction(write=True) as db:
        case, role = get_case(db, case_id, user, write=True)
        expect(case, expectedRevision)
        data = copy.deepcopy(case.data)
        if not any(o["id"] == offerId for o in data["model"]["offers"]):
            fail("unknown_offer", "Wybierz ofertę przypisaną do tej sprawy.")
        if any(d["sha256"] == source_hash and d["offerId"] == offerId for d in data["documents"]):
            return detail(db, case, role)
        if relation == "replacement":
            previous = next((d for d in data["documents"] if d["id"] == replacesId and d["offerId"] == offerId), None)
            if not previous:
                fail("unknown_source", "Wybierz dokument tej oferty do zastąpienia.")
            previous["active"] = False
        identifier = uid()
        destination = settings.file_storage / case.id / (identifier + Path(name).suffix.lower())
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        except OSError as exc:
            # Only this new upload may be incomplete. Its metadata and any
            # replacement flags remain inside the rolled-back transaction.
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
            if exc.errno in {errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)} or getattr(exc, "winerror", None) == 112:
                fail("storage_full", "Brak miejsca na zapis dokumentu. Wcześniejsze dane pozostają zapisane. Zwolnij miejsce i ponów import.", 507)
            fail("storage_unavailable", "Nie można teraz zapisać dokumentu. Wcześniejsze dane pozostają zapisane. Sprawdź dostęp do miejsca na pliki i ponów import.", 503)
        from .extraction import DocumentError, detect_mime
        try:
            actual_mime = detect_mime(destination, mime, settings.max_upload_mb)
        except DocumentError as exc:
            destination.unlink(missing_ok=True)
            fail(exc.code, str(exc), 415)
        data["documents"].append({"id": identifier, "offerId": offerId, "name": name, "mime": actual_mime,
            "sha256": source_hash, "bytes": len(content), "author": author, "addedBy": user.id,
            "documentDate": documentDate or None, "addedAt": now(), "version": 1 + sum(d["offerId"] == offerId for d in data["documents"]),
            "relation": relation, "replacesId": replacesId, "relationConfirmed": relationConfirmed == "true",
            "storagePath": str(destination), "status": "pending", "pages": [], "active": True})
        data["pendingAnalysis"] = True
        invalidate(data, "Dodano nowe źródło. Wynik wymaga analizy zmian.", offer_id=offerId)
        save(db, case, data, user.id, "document_imported")
        return detail(db, case, role)


@router.get("/cases/{case_id}/documents/{document_id}/file")
def read_file(case_id: str, document_id: str, request: Request):
    with transaction() as db:
        case, _ = get_case(db, case_id, current_user(request))
        document = next((d for d in case.data["documents"] if d["id"] == document_id), None)
        if not document or not Path(document["storagePath"]).exists():
            fail("not_found", "Nie znaleziono dokumentu.", 404)
        return FileResponse(document["storagePath"], media_type=document["mime"], filename=document["name"],
                            content_disposition_type="inline", headers={"Cache-Control": "private, no-store"})


@router.delete("/cases/{case_id}/documents/{document_id}", response_model=CaseDetail)
def remove_document(case_id: str, document_id: str, body: DeleteInput, request: Request):
    user = current_user(request)
    with transaction(write=True) as db:
        case, role = get_case(db, case_id, user, write=True)
        expect(case, body.expectedRevision)
        data = copy.deepcopy(case.data)
        document = next((d for d in data["documents"] if d["id"] == document_id), None)
        if not document:
            fail("not_found", "Nie znaleziono dokumentu.", 404)
        offer_id = document["offerId"]
        db.merge(DocumentTombstone(case_id=case_id, document_id=document_id, offer_id=offer_id))
        Path(document["storagePath"]).unlink(missing_ok=True)
        # Purge the dependency closure from every snapshot, not just visible facts.
        data = purge_source(data, document_id, offer_id)
        for revision in db.scalars(select(Revision).where(Revision.case_id == case_id)):
            revision.data = purge_source(revision.data, document_id, offer_id)
        for job in db.scalars(select(Job).where(Job.case_id == case_id)):
            job.data = {}
            job.error = None
            if job.status in {"queued", "running"}:
                release_unstarted_usage(db, job)
                job.cancelled = True
                job.status = "cancelled"
        data["pendingAnalysis"] = True
        invalidate(data, "Usunięto źródło. Oparte na nim ustalenia nie są już dostępne.", offer_id=offer_id)
        save(db, case, data, user.id, "source_deleted")
        return detail(db, case, role)


@router.post("/cases/{case_id}/analysis", response_model=CaseDetail)
def start_analysis(case_id: str, body: AnalysisInput, request: Request):
    user = current_user(request)
    if not body.consent:
        fail("consent_required", "Potwierdź przekazanie treści dokumentów do Google Gemini.")
    with transaction(write=True) as db:
        case, role = get_case(db, case_id, user, write=True)
        expect(case, body.expectedRevision)
        documents = [d for d in case.data["documents"] if d.get("active", True)]
        if not documents:
            fail("no_documents", "Najpierw dodaj dokumenty.")
        groups = {offer_id: [d for d in documents if d["offerId"] == offer_id] for offer_id in dict.fromkeys(d["offerId"] for d in documents)}
        group_keys = {offer_id: extraction_cache_key(group, case.data["requirements"]) for offer_id, group in groups.items()}
        key = digest([case.id, list(group_keys.items())])
        previous = db.scalar(select(Job).where(Job.key == key))
        if previous and previous.status in {"queued", "running", "completed"}:
            return detail(db, case, role)
        if previous:
            previous.key = key + ":" + previous.id
        cached = copy.deepcopy(previous.data) if previous else {}
        parsed = {identifier: value for identifier, value in cached.get("parsed", {}).items()
                  if identifier in {d["id"] for d in documents} and value.get("complete")}
        extracted = {identifier: value for identifier, value in cached.get("extracted", {}).items()
                     if identifier in set(group_keys.values())}
        affected = affected_offer_ids(case.data)
        missing = {offer_id for offer_id in affected if group_keys[offer_id] not in extracted}
        missing_documents = [document for offer_id in missing for document in groups[offer_id]]
        job_id = uid()
        estimated_input = min(settings.max_tokens, max(1000, sum(d["bytes"] for d in missing_documents) // 2)) if missing else 0
        offer_count = len(missing)
        estimated = (estimated_input * settings.input_price + offer_count * settings.max_output_tokens * settings.output_price) / 1_000_000 * 3
        reserve_usage(db, case.id, user.id, job_id, estimated)
        data = copy.deepcopy(case.data)
        data["pendingAnalysis"] = True
        save(db, case, data, user.id, "analysis_requested")
        db.add(Job(id=job_id, case_id=case.id, user_id=user.id, input_revision=case.revision,
                   key=key, data={"filesTotal": len(documents), "consentAt": now(), "parsed": parsed,
                                  "extracted": extracted, "prepaidGroupKeys": sorted(extracted),
                                  "resumedFromJob": previous.id if previous else None}))
        db.flush()
        return detail(db, case, role)


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request):
    user = current_user(request)
    session_token = request.cookies.get("kontroferta_session", "")
    session_key = hmac.new(settings.session_secret.encode(), session_token.encode(), hashlib.sha256).hexdigest()
    with transaction() as db:
        job = db.get(Job, job_id)
        if not job:
            fail("not_found", "Nie znaleziono zadania.", 404)
        get_case(db, job.case_id, user)
    async def events():
        last = None
        for _ in range(600):
            if await request.is_disconnected():
                return
            with transaction() as db:
                live_session = db.get(WebSession, session_key)
                if not live_session or live_session.expires <= time.time() or live_session.user_id != user.id:
                    return
                job = db.get(Job, job_id)
                if not job:
                    return
                try:
                    get_case(db, job.case_id, user)
                except Exception:
                    return
                payload = job_public(job)
            encoded = json.dumps(payload, ensure_ascii=False)
            if encoded != last:
                yield f"event: job\ndata: {encoded}\n\n"
                last = encoded
            if payload["status"] in {"completed", "failed", "cancelled", "superseded"}:
                return
            await asyncio.sleep(1)
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/jobs/{job_id}/cancel", response_model=CaseDetail)
def cancel_job(job_id: str, body: Write, request: Request):
    user = current_user(request)
    with transaction(write=True) as db:
        job = db.get(Job, job_id)
        if not job:
            fail("not_found", "Nie znaleziono zadania.", 404)
        case, role = get_case(db, job.case_id, user, write=True)
        expect(case, body.expectedRevision)
        if job.status == "cancelled":
            return detail(db, case, role)
        if job.status not in {"queued", "running"}:
            fail("job_already_finished", "Zadanie już się zakończyło. Nie można anulować zapisanego wyniku.", 409)
        release_unstarted_usage(db, job)
        job.cancelled = True
        job.status = "cancelled"
        job.updated_at = now()
        save(db, case, case.data, user.id, "analysis_cancelled")
        return detail(db, case, role)


@router.patch("/cases/{case_id}/facts/{fact_id}", response_model=CaseDetail)
def update_fact(case_id: str, fact_id: str, body: UpdateFact, request: Request):
    user = current_user(request)
    with transaction(write=True) as db:
        case, role = get_case(db, case_id, user, write=True)
        expect(case, body.expectedRevision)
        data = copy.deepcopy(case.data)
        fact = next((f for f in data["facts"] if f["id"] == fact_id), None)
        if not fact:
            fail("not_found", "Nie znaleziono ustalenia.", 404)
        value_changed = "value" in body.model_fields_set and body.value != fact.get("value")
        unit_changed = "unit" in body.model_fields_set and body.unit != fact.get("unit")
        if unit_changed and body.unit is None:
            fail("invalid_money_unit", "Wybierz jawną jednostkę kwoty.")
        if value_changed or unit_changed:
            money_issue = any(issue.get("message") == "conflict:money_unit:" + fact["id"]
                              and issue.get("offer_id") == fact.get("offer_id") for issue in data["model"].get("issues", []))
            fact.setdefault("previousValues", []).append({"value": fact["value"], "unit": fact.get("unit"),
                "origin": fact.get("origin"), "confirmation": fact.get("confirmation"), "at": now(), "author": user.id,
                "reason": body.reason})
            if value_changed:
                fact["value"] = body.value
            if unit_changed:
                fact["unit"] = body.unit
            fact["origin"] = "human"
            fact["author"] = user.id
            fact["reason"] = body.reason
            if money_issue or unit_changed and not value_changed:
                fact["correctionKind"] = "money_representation"
                fact.pop("representationProof", None)
            else:
                fact.pop("correctionKind", None)
                fact["conflict"] = False
                fact["condition_unresolved"] = False
            apply_fact(data, fact)
            invalidate(data, "Poprawiono interpretację ustalenia.")
        if body.confirmation == "confirmed":
            validate_fact_confirmation(fact)
            if fact.get("origin") == "human":
                apply_fact(data, fact)
        fact.update(confirmation=body.confirmation, confirmedBy=user.id, confirmedAt=now(), reason=body.reason)
        fact["dependencyHash"] = fact_fingerprint(fact)
        compute(data)
        save(db, case, data, user.id, "fact_reviewed")
        return detail(db, case, role)


@router.post("/cases/{case_id}/approvals", response_model=CaseDetail)
def approve(case_id: str, body: ApprovalInput, request: Request):
    user = current_user(request)
    with transaction(write=True) as db:
        case, role = get_case(db, case_id, user, write=True)
        expect(case, body.expectedRevision)
        data = copy.deepcopy(case.data)
        if data.get("pendingAnalysis"):
            fail("pending_analysis", "Najpierw przeanalizuj zmienione źródła.")
        wanted = set(body.factIds)
        if not wanted.issubset({f["id"] for f in data["facts"]}):
            fail("unknown_fact", "Nieznane ustalenie.")
        for fact in data["facts"]:
            if fact["id"] in wanted:
                if fact.get("confirmation") == "superseded":
                    continue
                validate_fact_confirmation(fact)
                if fact.get("origin") == "human":
                    apply_fact(data, fact)
                fact.update(confirmation="confirmed", confirmedBy=user.id, confirmedAt=now(), dependencyHash=fact_fingerprint(fact))
        if body.requirementsConfirmed:
            data["requirements"]["confirmed"] = True
        data["approval"] = {"id": uid(), "author": user.id, "revision": case.revision + 1,
                            "requirementsHash": digest(data["requirements"]), "current": True,
                            "factHashes": {f["id"]: fact_fingerprint(f) for f in data["facts"] if f.get("confirmation") == "confirmed"}, "at": now()}
        compute(data)
        save(db, case, data, user.id, "critical_fields_approved")
        return detail(db, case, role)


@router.post("/cases/{case_id}/recalculate")
def recalculate(case_id: str, body: Recalculate, request: Request):
    user = current_user(request)
    with transaction(write=body.assignments is None) as db:
        case, role = get_case(db, case_id, user, write=body.assignments is None)
        expect(case, body.expectedRevision)
        data = copy.deepcopy(case.data)
        if body.assignments is not None:
            return preview(data, body.assignments)
        compute(data)
        save(db, case, data, user.id, "recalculated")
        return detail(db, case, role)


def preview(data, assignments):
    from packages.domain import evaluate
    model = copy.deepcopy(data["model"])
    if not set(assignments).issubset({v["id"] for v in model["variables"]}):
        fail("unknown_variable", "Nieznana niewiadoma.")
    for variable in model["variables"]:
        if variable["id"] in assignments:
            variable.update(kind="enum", values=[assignments[variable["id"]]], complete=True)
            variable.pop("lower", None)
            variable.pop("upper", None)
            variable["assumption"] = "Podgląd przy jawnie zadanej wartości. Nie stanowi odpowiedzi wykonawcy."
    return {**evaluate(model), "preview": True}


@router.patch("/cases/{case_id}/questions/{question_id}", response_model=CaseDetail)
def update_question(case_id: str, question_id: str, body: QuestionInput, request: Request):
    user = current_user(request)
    with transaction(write=True) as db:
        case, role = get_case(db, case_id, user, write=True)
        expect(case, body.expectedRevision)
        data = copy.deepcopy(case.data)
        question = next((q for q in data["questions"] if q["id"] == question_id), None)
        if not question:
            fail("not_found", "Nie znaleziono pytania.", 404)
        if body.status == "resolved" and not any(a.get("confirmed") and a.get("kind") == "value" for a in question.get("answers", [])):
            fail("unresolved", "Najpierw dodaj i sprawdź konkretną odpowiedź.")
        for key in ("status", "assignee", "dueAt", "difficulty"):
            if key in body.model_fields_set:
                question[key] = getattr(body, key)
        if body.difficulty is not None:
            for variable in data["model"]["variables"]:
                if variable["id"] in (question.get("variable_ids") or [question_id, question.get("variable_id")]):
                    variable["difficulty"] = body.difficulty
            compute(data)
        save(db, case, data, user.id, "question_updated")
        return detail(db, case, role)


@router.post("/cases/{case_id}/questions/{question_id}/answers", response_model=CaseDetail)
def add_answer(case_id: str, question_id: str, body: AnswerInput, request: Request):
    user = current_user(request)
    with transaction(write=True) as db:
        case, role = get_case(db, case_id, user, write=True)
        expect(case, body.expectedRevision)
        data = copy.deepcopy(case.data)
        question = next((q for q in data["questions"] if q["id"] == question_id), None)
        if not question:
            fail("not_found", "Nie znaleziono pytania.", 404)
        variable_ids = question.get("variable_ids") or [question.get("variable_id", question.get("variable", question_id))]
        variables = [v for v in data["model"]["variables"] if v["id"] in variable_ids]
        answer = {"id": uid(), "text": body.text, "kind": body.kind, "value": body.value,
                  "confirmed": body.confirmed, "author": user.id, "at": now(), "origin": "human_entered_supplier_response"}
        question.setdefault("answers", []).append(answer)
        question["status"] = "answer_added"
        if body.kind == "value" and body.confirmed:
            if not variables:
                fail("model_correction_required", "To pytanie dotyczy brakującego źródła lub modelu. Dodaj materiał albo popraw ustalenie lub model.")
            if len(variables) != len(variable_ids) or body.value is None:
                fail("invalid_answer", "Podaj wartości odpowiadające niewiadomym tego pytania.")
            if len(variables) > 1:
                if not isinstance(body.value, dict) or set(body.value) != set(variable_ids):
                    fail("invalid_answer", "Para pytań wymaga obiektu z wartością każdej wskazanej niewiadomej.", variableIds=variable_ids)
                assignments = body.value
            else:
                assignments = {variables[0]["id"]: body.value}
            outside = {}
            offer_dependencies = variable_offer_dependencies(data)
            for variable in variables:
                variable_id = variable["id"]
                value = assignments[variable_id]
                if value is None or isinstance(value, (list, dict)):
                    fail("invalid_answer", "Każda niewiadoma wymaga pojedynczej wartości.")
                if variable.get("unit") == "minor" and (type(value) is not int or value < 0):
                    fail("invalid_money", "Kwota musi być nieujemną liczbą najmniejszych jednostek waluty (dla PLN: groszy).")
                if variable.get("kind") == "interval":
                    from decimal import Decimal, InvalidOperation
                    try:
                        number = Decimal(str(value))
                        lower, upper = Decimal(str(variable["lower"])), Decimal(str(variable["upper"]))
                        outside[variable_id] = not number.is_finite() or not lower <= number <= upper
                        if variable.get("step") and not outside[variable_id]:
                            outside[variable_id] = (number - lower) % Decimal(str(variable["step"])) != 0
                    except (InvalidOperation, ValueError):
                        fail("invalid_answer", "Przedział liczbowy wymaga poprawnej liczby.")
                else:
                    outside[variable_id] = value not in variable.get("values", [])
                variable.update(kind="enum", values=[value], complete=True, source=f"answer:{answer['id']}")
                for bound in ("lower", "upper", "step"):
                    variable.pop(bound, None)
                matching_fact = next((f for f in data["facts"] if f["id"] in variable.get("evidence_ids", [])), {})
                offer_id = question.get("offer_id") or matching_fact.get("offer_id")
                dependent_offers = offer_dependencies.get(variable_id, set()) | ({offer_id} if offer_id else set())
                if not offer_id and len(dependent_offers) == 1:
                    offer_id = next(iter(dependent_offers))
                data["facts"].append({"id": answer["id"] if len(variables) == 1 else answer["id"] + ":" + variable_id,
                    "key": "variable:" + variable_id, "value": value, "offer_id": offer_id,
                    "dependent_offer_ids": sorted(dependent_offers),
                    "targets": [{"kind": "variable", "variable_id": variable_id, "field": "values"}],
                    "unit": variable.get("unit"), "origin": "human", "author": user.id, "reason": body.text,
                    "confirmation": "confirmed", "confirmedBy": user.id, "confirmedAt": now(), "evidence": [], "critical": True})
            answer["outsideOriginalDomain"] = any(outside.values())
            answer["outsideOriginalDomains"] = outside
            question["status"] = "resolved"
            question["needsReview"] = False
            question.pop("reviewReason", None)
            invalidate(data, "Dodano sprawdzoną odpowiedź dotyczącą kosztu lub zakresu.")
        compute(data)
        save(db, case, data, user.id, "answer_added")
        return detail(db, case, role)


@router.post("/cases/{case_id}/decisions", response_model=CaseDetail)
def decide(case_id: str, body: DecisionInput, request: Request):
    user = current_user(request)
    with transaction(write=True) as db:
        case, role = get_case(db, case_id, user, owner=True)
        expect(case, body.expectedRevision)
        data = copy.deepcopy(case.data)
        analysis = compute(data)
        if not all((body.confirmCost, body.confirmScope, body.confirmDeadline)):
            fail("explicit_confirmation", "Potwierdź koszt, pełny zakres i termin wybranej oferty.")
        if body.offerId not in {o["id"] for o in data["model"]["offers"]}:
            fail("unknown_offer", "Wybierz ofertę tej sprawy.")
        excluded_offers = set(analysis.get("scope", {}).get("excluded_offer_ids", []))
        excluded_variables = set(analysis.get("scope", {}).get("excluded_variable_ids", []))
        active_evidence = set()
        for offer in data["model"]["offers"]:
            if offer["id"] not in excluded_offers:
                active_evidence.update(offer.get("evidence_ids", []))
                for item in offer["cost_items"]:
                    active_evidence.update(item.get("evidence_ids", []))
        for variable in data["model"]["variables"]:
            if variable["id"] not in excluded_variables:
                active_evidence.update(variable.get("evidence_ids", []))
        critical_facts = [f for f in data["facts"] if f.get("critical", True)
                          and (f.get("offer_id") not in excluded_offers or f["id"] in active_evidence)]
        unconfirmed = [f["id"] for f in critical_facts if f.get("confirmation") != "confirmed"]
        if body.kind == "final":
            if data["pendingAnalysis"] or not analysis.get("complete") or unconfirmed or not data["requirements"].get("confirmed"):
                fail("review_required", "Sprawdź źródła i potwierdź wymagania oraz krytyczne ustalenia.", 422, unconfirmedFactIds=unconfirmed)
            for fact in critical_facts:
                validate_fact_confirmation(fact)
            if body.offerId not in analysis.get("robust_feasible", []):
                fail("not_robust_feasible", "Wybrana oferta nie spełnia wymagań we wszystkich przyjętych scenariuszach.")
        elif not body.assumptions or not body.nextStep or not body.owner:
            fail("conditional_details", "Wybór warunkowy wymaga założenia, osoby odpowiedzialnej i kolejnego kroku.")
        for previous in data["decisions"]:
            previous["current"] = False
        costs = sorted({s["costs"].get(body.offerId) for s in analysis.get("scenarios", []) if s["costs"].get(body.offerId) is not None})
        data["decisions"].append({"id": uid(), "offerId": body.offerId, "kind": body.kind,
            "reason": body.reason, "assumptions": body.assumptions, "nextStep": body.nextStep, "owner": body.owner or user.id,
            "author": user.id, "at": now(), "revision": case.revision + 1, "inputRevision": case.revision,
            "dependencyHash": digest([data["model"], data["facts"], data["requirements"]]), "current": True,
            "costsMinor": costs, "isCommonCheapest": body.offerId in analysis.get("common_winners", []),
            "unresolvedAssumptions": analysis.get("issues", []), "unconfirmedFactIds": unconfirmed,
            "confirmedFields": ["cost", "scope", "deadline"]})
        save(db, case, data, user.id, "decision_approved")
        return detail(db, case, role)


@router.post("/cases/{case_id}/undo", response_model=CaseDetail)
def undo(case_id: str, body: UndoInput, request: Request):
    user = current_user(request)
    with transaction(write=True) as db:
        case, role = get_case(db, case_id, user, write=True)
        expect(case, body.expectedRevision)
        old = db.scalar(select(Revision).where(Revision.case_id == case.id, Revision.revision == body.targetRevision))
        if not old:
            fail("not_found", "Nie znaleziono wersji.", 404)
        data = copy.deepcopy(old.data)
        invalidate(data, "Przywrócono historyczną wersję jako nową rewizję.", all_facts=True)
        data["requirements"]["confirmed"] = False
        save(db, case, data, user.id, f"restored_revision:{body.targetRevision}")
        return detail(db, case, role)


@router.get("/cases/{case_id}/history/{revision}")
def history(case_id: str, revision: int, request: Request):
    with transaction() as db:
        get_case(db, case_id, current_user(request))
        row = db.scalar(select(Revision).where(Revision.case_id == case_id, Revision.revision == revision))
        if not row:
            fail("not_found", "Nie znaleziono wersji.", 404)
        data = copy.deepcopy(row.data)
        for document in data["documents"]:
            document.pop("storagePath", None)
            for page in document.get("pages", []):
                page.pop("source_image", None)
        return {"revision": revision, "snapshot": data, "historical": True}


@router.post("/cases/{case_id}/invitations")
def invite(case_id: str, body: InvitationInput, request: Request):
    user = current_user(request)
    with transaction(write=True) as db:
        case, role = get_case(db, case_id, user, owner=True)
        expect(case, body.expectedRevision)
        token = secrets.token_urlsafe(32)
        expires = time.time() + 86400
        db.add(Invitation(token_hash=hashlib.sha256(token.encode()).hexdigest(), case_id=case.id, role=body.role, expires=expires))
        save(db, case, case.data, user.id, "invitation_created")
        return {"url": settings.base_url + "/#/invite/" + token, "token": token, "expiresAt": expires, "case": detail(db, case, role)}


@router.post("/invitations/{token}/accept", response_model=CaseDetail)
def accept_invite(token: str, request: Request):
    user = current_user(request)
    with transaction(write=True) as db:
        invite = db.get(Invitation, hashlib.sha256(token.encode()).hexdigest())
        if not invite or invite.consumed or invite.expires < time.time():
            fail("invalid_invitation", "Zaproszenie wygasło lub zostało wykorzystane.", 410)
        case = db.get(Case, invite.case_id)
        if not case:
            fail("not_found", "Nie znaleziono sprawy.", 404)
        if case.owner_id == user.id:
            fail("already_owner", "Jesteś już właścicielem sprawy.")
        member = db.scalar(select(Member).where(Member.case_id == case.id, Member.user_id == user.id))
        if member:
            fail("already_member", "Masz już dostęp do sprawy.")
        db.add(Member(case_id=case.id, user_id=user.id, role=invite.role))
        invite.consumed = True
        save(db, case, case.data, user.id, "invitation_accepted")
        return detail(db, case, invite.role)


@router.delete("/cases/{case_id}/members/{member_id}", response_model=CaseDetail)
def remove_member(case_id: str, member_id: str, body: Write, request: Request):
    user = current_user(request)
    with transaction(write=True) as db:
        case, role = get_case(db, case_id, user, owner=True)
        expect(case, body.expectedRevision)
        member = db.scalar(select(Member).where(Member.case_id == case.id, Member.user_id == member_id))
        if not member:
            fail("not_found", "Nie znaleziono członka sprawy.", 404)
        db.delete(member)
        save(db, case, case.data, user.id, "member_removed")
        return detail(db, case, role)


@router.put("/cases/{case_id}/model", response_model=CaseDetail)
def edit_model(case_id: str, body: ModelInput, request: Request):
    from packages.domain.models import ComparisonModel
    try:
        parsed = ComparisonModel.model_validate(body.model).model_dump(mode="json", exclude_none=True, exclude_unset=True)
    except ValueError:
        fail("invalid_model", "Model nie spełnia zamkniętego schematu obliczeń.")
    user = current_user(request)
    with transaction(write=True) as db:
        case, role = get_case(db, case_id, user, write=True)
        expect(case, body.expectedRevision)
        data = copy.deepcopy(case.data)
        data["model"] = parsed
        data["facts"].append({"id": uid(), "key": "manual_model", "value": parsed,
                              "origin": "human", "author": user.id, "reason": body.reason,
                              "confirmation": "proposed", "evidence": [], "critical": True})
        invalidate(data, "Ręcznie zmieniono model obliczeń.", all_facts=True)
        data["pendingAnalysis"] = any(d.get("status") == "pending" for d in data["documents"])
        compute(data)
        save(db, case, data, user.id, "manual_model_updated")
        return detail(db, case, role)


@router.post("/cases/{case_id}/requirements/propose")
def propose_requirements(case_id: str, body: RequirementsProposal, request: Request):
    user = current_user(request)
    if not body.consent:
        fail("consent_required", "Potwierdź przekazanie opisu do Google Gemini.")
    with transaction(write=True) as db:
        case, _ = get_case(db, case_id, user, write=True)
        expect(case, body.expectedRevision)
        usage = reserve_usage(db, case.id, user.id, uid(), 0.12)
        usage_id = usage.id
    from .ai import AIError, propose_requirements as call_ai
    from apps.worker.main import settle_usage
    try:
        result = call_ai(body.text)
    except AIError as exc:
        # A rejected extraction can still have incurred a known provider charge.
        # If usage is absent, keep the reservation instead of recording zero.
        settle_usage(usage_id, [exc.trace or {"usage_complete": False}])
        fail(exc.code, str(exc), 502)
    settle_usage(usage_id, [result["trace"]])
    return result


@router.get("/cases/{case_id}/exports/{format}")
def export_case(case_id: str, format: str, request: Request, revision: int | None = None):
    user = current_user(request)
    with transaction() as db:
        case, role = get_case(db, case_id, user)
        result = detail(db, case, role)
        if revision is not None and revision != case.revision:
            old = db.scalar(select(Revision).where(Revision.case_id == case.id, Revision.revision == revision))
            if not old:
                fail("not_found", "Nie znaleziono wersji.", 404)
            result.update(copy.deepcopy(old.data))
            result["revision"] = revision
            result["updatedAt"] = old.created_at
            result["offers"] = result["model"].get("offers", [])
            result["status"] = "pending_analysis" if result.get("pendingAnalysis") else (result.get("analysis") or {}).get("status", "draft")
        for document in result["documents"]:
            document.pop("storagePath", None)
            for page in document.get("pages", []):
                page.pop("source_image", None)
        result["export"] = {"at": now(), "by": user.id, "version": result["revision"],
                            "historical": result["revision"] != case.revision,
                            "snapshot": True, "formatVersion": "1.0"}
    filename = f"kontrOferta-{case_id[:8]}-v{result['revision']}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}.{format}"', "Cache-Control": "private, no-store"}
    if format == "json":
        return Response(json.dumps(result, ensure_ascii=False, indent=2), media_type="application/json", headers=headers)
    if format == "pdf":
        from .reports import render_pdf
        return Response(render_pdf(result), media_type="application/pdf", headers=headers)
    fail("unknown_format", "Dostępne formaty: PDF i JSON.", 404)
