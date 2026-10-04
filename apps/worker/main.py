"""Durable jobs with leases, resumable parser/extractor stages and fenced commits."""
import copy
import json
import logging
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import select

from apps.api.config import settings
from apps.api.db import Case, Job, Usage, digest, init_db, now, transaction, uid
from apps.api.service import affected_offer_ids, apply_fact, compute, extraction_cache_key, fact_fingerprint, save

log = logging.getLogger("kontroferta.worker")
STOP = threading.Event()
LEASE_SECONDS = 120
AI_SLOTS = threading.BoundedSemaphore(max(1, int(os.getenv("AI_MAX_CONCURRENCY", "2"))))


def settle_usage(usage_id, traces, *, job_id=None, worker_id=None, claim_attempt=None):
    input_tokens = output_tokens = thinking_tokens = 0
    known = True
    for trace in traces:
        if trace.get("usage_complete") is False:
            known = False
        attempts = trace.get("attempts", [])
        if not attempts:
            attempts = [{"usage": trace.get("usage", {})}]
        for attempt in attempts:
            usage = attempt.get("usage", {})
            if not usage:
                known = False
            input_tokens += usage.get("input_tokens", 0) or 0
            output_tokens += usage.get("output_tokens", 0) or 0
            thinking_tokens += usage.get("thinking_tokens", 0) or 0
    with transaction(write=True) as db:
        row = db.get(Usage, usage_id)
        if row:
            job = db.get(Job, job_id) if job_id else None
            if job_id and (not job or job.lease_owner != worker_id or job.attempts != claim_attempt):
                return  # A late worker cannot overwrite the new lease owner's settlement.
            if job and job.data.get("recoveredExtractionUsageUnknown"):
                known = False  # The interrupted provider call may still have been billed.
            row.actual = (input_tokens * settings.input_price + (output_tokens + thinking_tokens) * settings.output_price) / 1_000_000 if known else None
            row.details = {**row.details, "input_tokens": input_tokens, "output_tokens": output_tokens,
                           "thinking_tokens": thinking_tokens, "usage_complete": known, "cost_type": "provider_usage_times_published_rates",
                           "attempt_count": sum(len(t.get("attempts", [])) for t in traces)}


def claim_job(worker_id):
    with transaction(write=True) as db:
        job = db.scalar(select(Job).where(
            (Job.status == "queued") | ((Job.status == "running") & (Job.lease_until < time.time()))
        ).order_by(Job.created_at).limit(1))
        if not job:
            return None
        if job.cancelled:
            job.status = "cancelled"
            return None
        if job.status == "running" and job.stage == "extracting":
            job.data = {**job.data, "recoveredExtractionUsageUnknown": True}
        job.lease_owner, job.lease_until = worker_id, time.time() + LEASE_SECONDS
        job.status, job.stage = "running", "reading"
        job.attempts += 1
        job.updated_at = now()
        return job.id


def update_job(job_id, worker_id, stage=None, update=None):
    with transaction(write=True) as db:
        job = db.get(Job, job_id)
        if not job or job.lease_owner != worker_id or job.cancelled or job.status != "running":
            raise InterruptedError("Job is cancelled, replaced or lease lost")
        if stage:
            job.stage = stage
        if update:
            job.data = {**job.data, **update}
        job.lease_until = time.time() + LEASE_SECONDS
        job.updated_at = now()


def run_job(job_id, worker_id):
    from apps.api.ai import AIError, PROMPT_VERSION, SCHEMA_VERSION, extract_offer
    from apps.api.extraction import PARSER_VERSION, parse_document, parser_cache_key
    done = threading.Event()
    def heartbeat():
        while not done.wait(15):
            try:
                update_job(job_id, worker_id)
            except InterruptedError:
                return
    pulse = threading.Thread(target=heartbeat, daemon=True)
    pulse.start()
    traces = []
    usage_id = None
    claim_attempt = None
    try:
        with transaction() as db:
            job = db.get(Job, job_id)
            if not job or job.lease_owner != worker_id or job.status != "running":
                raise InterruptedError("Job lease lost before execution")
            claim_attempt = job.attempts
            usage_row = db.scalar(select(Usage).where(Usage.job_id == job_id))
            usage_id = usage_row.id if usage_row else None
            cached = copy.deepcopy(job.data)
            prepaid = set(cached.get("prepaidGroupKeys", []))
            billed_cached_keys = set(cached.get("extracted", {})) - prepaid
            traces.extend(cached["extracted"][key]["trace"] for key in billed_cached_keys)
            case = db.get(Case, job.case_id)
            if not case:
                raise InterruptedError("Case deleted")
            input_revision = job.input_revision
            if case.revision != input_revision:
                raise InterruptedError("Newer case revision")
            data = copy.deepcopy(case.data)
        documents = [d for d in data["documents"] if d.get("active", True)]
        affected_offers = affected_offer_ids(data)
        parser_fingerprint = parser_cache_key()
        parsed = {identifier: value for identifier, value in cached.get("parsed", {}).items()
                  if value.get("parser_version") == PARSER_VERSION and value.get("parser_fingerprint") == parser_fingerprint}
        for index, document in enumerate(documents):
            update_job(job_id, worker_id, "reading")
            if (document["id"] not in parsed and document.get("pages") and document.get("parserVersion") == PARSER_VERSION
                    and document.get("parserFingerprint") == parser_fingerprint):
                parsed[document["id"]] = {"pages": document["pages"], "complete": all(p["status"] == "read" for p in document["pages"]),
                                          "parser_version": document["parserVersion"], "parser_fingerprint": parser_fingerprint,
                                          "parser_runtime": document.get("parserRuntime", {}), "issues": document.get("issues", [])}
            if document["id"] not in parsed:
                parsed[document["id"]] = parse_document(document["storagePath"], document["mime"], source_id=document["id"], max_pages=settings.max_pages)
            document["pages"] = parsed[document["id"]]["pages"]
            if document["offerId"] in affected_offers:
                document["status"] = "read" if parsed[document["id"]]["complete"] else "needs_review"
            document["parserVersion"] = parsed[document["id"]]["parser_version"]
            document["parserFingerprint"] = parsed[document["id"]].get("parser_fingerprint")
            document["parserRuntime"] = parsed[document["id"]].get("parser_runtime", {})
            document["issues"] = parsed[document["id"]]["issues"]
            update_job(job_id, worker_id, update={"parsed": parsed, "filesRead": index + 1,
                       "pagesRead": sum(len(p["pages"]) for p in parsed.values()), "pagesTotal": sum(len(p["pages"]) for p in parsed.values())})
        characters = sum(len(p["text"]) for doc in documents for p in doc["pages"])
        # Conservative token reservation based on UTF-8 bytes; never truncate sources.
        if sum(len(p["text"].encode()) for doc in documents for p in doc["pages"]) > settings.max_tokens * 2:
            raise AIError("input_limit", "Materiały przekraczają limit wejścia. Podziel sprawę lub zmień limit konfiguracji.")
        results = cached.get("extracted", {})
        offer_ids = list(dict.fromkeys(d["offerId"] for d in documents if d["offerId"] in affected_offers))
        groups = {}
        for offer_id in offer_ids:
            relevant = [d for d in documents if d["offerId"] == offer_id]
            group_key = extraction_cache_key(relevant, data["requirements"])
            groups[offer_id] = (group_key, relevant)
        def infer(offer_id, relevant):
            with AI_SLOTS:
                update_job(job_id, worker_id, "extracting")
                return extract_offer([p for doc in relevant for p in doc["pages"]], data["requirements"], offer_id=offer_id,
                    existing_sources=[{"source_id": d["id"], "relation": d["relation"], "replacesId": d.get("replacesId"),
                                       "relationConfirmed": d.get("relationConfirmed"), "documentDate": d.get("documentDate")} for d in relevant])
        extraction_error = None
        with ThreadPoolExecutor(max_workers=max(1, int(os.getenv("AI_MAX_CONCURRENCY", "2")))) as extraction_pool:
            futures = {extraction_pool.submit(infer, offer_id, relevant): key
                       for offer_id, (key, relevant) in groups.items() if key not in results}
            for future in as_completed(futures):
                try:
                    result = future.result()
                    results[futures[future]] = result
                    # Persist completed groups independently; a retry reuses them.
                    update_job(job_id, worker_id, update={"extracted": results})
                except Exception as exc:
                    if getattr(exc, "trace", None):
                        traces.append(exc.trace)
                        exc.trace = None
                    extraction_error = extraction_error or exc
        traces.extend(results[key]["trace"] for key, _ in groups.values()
                      if key in results and key not in prepaid and key not in billed_cached_keys)
        if extraction_error:
            raise extraction_error
        for offer_id in offer_ids:
            update_job(job_id, worker_id, "extracting")
            group_key, relevant = groups[offer_id]
            result = results[group_key]
            previous_facts = {f["id"]: f for f in data["facts"] if f.get("offer_id") == offer_id}
            # Also recover a case saved by an older worker that had appended a
            # duplicate source proposal after its human correction.
            previous_facts.update({f["id"]: f for f in data["facts"]
                                   if f.get("offer_id") == offer_id and f.get("origin") == "human"})
            data["facts"] = [f for f in data["facts"] if f.get("offer_id") != offer_id or f.get("origin") == "human"]
            for fact in result["facts"]:
                fact["offer_id"] = offer_id
                fact.setdefault("critical", True)
                old = previous_facts.get(fact["id"])
                if old and old.get("origin") == "human":
                    # One active identity retains the reviewed human value and
                    # its author/history. Preserve the new source proposal as
                    # provenance, not a duplicate competing active fact.
                    old["latestSourceInterpretation"] = {**copy.deepcopy(fact), "checkedAt": now()}
                    continue
                fingerprint = fact_fingerprint(fact)
                evidence_valid = bool(fact.get("evidence")) and all(e.get("quote_validated") for e in fact["evidence"])
                eligible = old and (old.get("confirmation") == "confirmed" or
                    old.get("confirmation") == "needs_review" and old.get("pendingSourceReviewFingerprint") == fingerprint)
                if (eligible and old.get("origin") != "human" and fact_fingerprint(old) == fingerprint
                        and evidence_valid and not fact.get("conflict") and not fact.get("condition_unresolved")):
                    fact.update({k: old[k] for k in ("confirmedAt", "confirmedBy", "dependencyHash") if k in old})
                    fact["confirmation"] = "confirmed"
                data["facts"].append(fact)
            old_offer = next((o for o in data["model"]["offers"] if o["id"] == offer_id), {})
            data["model"]["offers"] = [o for o in data["model"]["offers"] if o["id"] != offer_id]
            replacement = result["domain_offer"]
            replacement["name"] = old_offer.get("name", replacement.get("name"))
            if old_offer.get("excluded_reason"):
                replacement["excluded_reason"] = old_offer["excluded_reason"]
            data["model"]["offers"].append(replacement)
            data["model"]["variables"] = [v for v in data["model"]["variables"] if not v["id"].startswith(offer_id + ":")]
            data["model"]["variables"].extend(result["variables"])
            data["model"]["issues"] = [i for i in data["model"].get("issues", []) if i.get("offer_id") != offer_id]
            data["model"]["issues"].extend({"code": "extraction_gap", "message": issue, "offer_id": offer_id, "blocking": True} for issue in result["issues"])
            for human in data["facts"]:
                if human.get("origin") == "human" and (human.get("offer_id") == offer_id or offer_id in human.get("dependent_offer_ids", [])) and human.get("confirmation") == "confirmed":
                    apply_fact(data, human)
            for document in relevant:
                document["extractionCacheKey"] = group_key
                document["analysisCoverage"] = [c for c in result["page_coverage"] if c["source_id"] == document["id"]]
                document["status"] = "analyzed" if all(c["analysis_status"] == "analyzed" for c in document["analysisCoverage"]) else "needs_review"
                document["trace"] = {k: result["trace"].get(k) for k in ("model", "prompt_version", "schema_version", "usage", "duration_ms")}
                document["trace"]["duration_ms"] = round(result["trace"].get("elapsed_seconds", 0) * 1000)
        update_job(job_id, worker_id, "validating")
        data["pendingAnalysis"] = False
        data["analysisProvenance"] = {"model": settings.ai_model, "traces": traces, "inputRevision": input_revision}
        compute(data)
        update_job(job_id, worker_id, "saving")
        with transaction(write=True) as db:
            job = db.get(Job, job_id)
            case = db.get(Case, job.case_id) if job else None
            if not job or not case or job.lease_owner != worker_id or job.cancelled or case.revision != input_revision:
                if job and job.status != "cancelled":
                    job.status = "superseded"
                    job.stage = "superseded"
                return
            save(db, case, data, job.user_id, "analysis_completed")
            job.status, job.stage = "completed", "completed"
            job.updated_at = now()
            job.lease_until = 0
    except InterruptedError:
        with transaction(write=True) as db:
            job = db.get(Job, job_id)
            if job and job.lease_owner == worker_id and job.status == "running":
                job.status = "superseded"
                job.stage = "superseded"
    except Exception as exc:
        if isinstance(exc, AIError) and getattr(exc, "trace", None):
            traces.append(exc.trace)
        with transaction(write=True) as db:
            job = db.get(Job, job_id)
            if job and job.lease_owner == worker_id and not job.cancelled:
                job.status, job.stage = "failed", "failed"
                safe = isinstance(exc, (AIError, ValueError))
                job.error = str(exc)[:500] if safe else "Błąd przetwarzania. Zapisane źródła pozostają dostępne; ponów analizę."
                job.updated_at = now()
                job.data = {**job.data, "errorType": type(exc).__name__}
        log.error("job_failed id=%s type=%s", job_id, type(exc).__name__)
    finally:
        done.set()
        if usage_id:
            settle_usage(usage_id, traces, job_id=job_id, worker_id=worker_id, claim_attempt=claim_attempt)


def main():
    from packages.domain import vectorized  # Keep cold imports out of job latency.
    init_db()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    concurrency = max(1, int(os.getenv("AI_MAX_CONCURRENCY", "2")))
    worker_id = uid()
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    active = set()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        while not STOP.is_set():
            active = {f for f in active if not f.done()}
            if len(active) < concurrency:
                job_id = claim_job(worker_id)
                if job_id:
                    active.add(pool.submit(run_job, job_id, worker_id))
                    continue
            STOP.wait(0.5)


if __name__ == "__main__":
    main()
