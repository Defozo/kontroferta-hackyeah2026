import copy
import hashlib
import json
import os
import re
import shutil
from decimal import Decimal, InvalidOperation
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import delete, select

from .config import settings
from .db import Case, Invitation, Job, Member, Revision, Tombstone, Usage, User, digest, now, uid


def fail(code, message, status=422, **extra):
    raise HTTPException(status, {"code": code, "message": message, **extra})


def get_case(db, case_id, user, write=False, owner=False):
    case = db.get(Case, case_id)
    if not case:
        fail("not_found", "Nie znaleziono sprawy.", 404)
    role = "owner" if case.owner_id == user.id else db.scalar(
        select(Member.role).where(Member.case_id == case_id, Member.user_id == user.id))
    if not role:
        fail("not_found", "Nie znaleziono sprawy.", 404)
    if owner and role != "owner" or write and role == "observer":
        fail("forbidden", "Ta rola nie pozwala wykonać operacji.", 403)
    return case, role


def expect(case, revision):
    if case.revision != revision:
        fail("revision_conflict", "Sprawa zmieniła się. Sprawdź różnice i ponów zapis.", 409,
             currentRevision=case.revision, expectedRevision=revision)


def snapshot(db, case, author, action):
    db.add(Revision(case_id=case.id, revision=case.revision, data=copy.deepcopy(case.data),
                    author=author, action=action))


def save(db, case, data, author, action):
    case.revision += 1
    case.updated_at = now()
    case.title = data.get("title", case.title)
    case.data = copy.deepcopy(data)
    snapshot(db, case, author, action)
    db.flush()


REQ_KEYS = {"participants", "microphones", "ready_by", "service_start", "service_end", "scope_required", "description", "confirmed"}


def normalize_requirements(req):
    value = copy.deepcopy(req)
    aliases = {"readyBy": "ready_by", "serviceStart": "service_start", "serviceEnd": "service_end",
               "budgetMinor": "budget_minor", "scopeRequired": "scope_required"}
    for old, new in aliases.items():
        if old in value:
            value[new] = value.pop(old)
    value.setdefault("currency", "PLN")
    value.setdefault("timezone", "Europe/Warsaw")
    try:
        ZoneInfo(value["timezone"])
    except (ZoneInfoNotFoundError, TypeError):
        fail("invalid_timezone", "Wybierz poprawną strefę czasową IANA.")
    for key in ("ready_by", "service_start", "service_end"):
        if value.get(key):
            try:
                moment = datetime.fromisoformat(value[key])
                if not moment.tzinfo:
                    fail("ambiguous_time", "Data musi zawierać strefę lub przesunięcie UTC.")
            except (ValueError, TypeError):
                fail("invalid_time", "Podaj pełną datę, godzinę i przesunięcie UTC.")
    if value.get("service_start") and value.get("service_end"):
        if datetime.fromisoformat(value["service_start"]) >= datetime.fromisoformat(value["service_end"]):
            fail("invalid_interval", "Koniec obsługi musi nastąpić po jej początku.")
    from packages.domain.models import Requirements
    try:
        Requirements.model_validate({k: v for k, v in value.items() if k in REQ_KEYS})
        if value.get("budget_minor") is not None and (type(value["budget_minor"]) is not int or value["budget_minor"] < 0):
            raise ValueError("budget")
        if not isinstance(value["currency"], str) or len(value["currency"]) != 3:
            raise ValueError("currency")
    except ValueError:
        fail("invalid_requirements", "Sprawdź kwoty i liczby w wymaganiach.")
    return value


def model_requirements(data):
    req = data["requirements"]
    model = data["model"]
    model["requirements"] = {k: v for k, v in req.items() if k in REQ_KEYS}
    model["currency"] = req.get("currency", "PLN")
    model["budget_minor"] = req.get("budget_minor")
    model["timezone"] = req.get("timezone", "Europe/Warsaw")
    model["max_scenarios"] = settings.max_scenarios


def empty_data(title, requirements):
    data = {"title": title, "requirements": normalize_requirements(requirements),
            "model": {"offers": [], "variables": [], "constraints": [], "issues": []},
            "documents": [], "facts": [], "questions": [], "decisions": [], "analysis": None,
            "approval": None, "impact": [], "pendingAnalysis": False}
    model_requirements(data)
    return data


def _review_question(question, reason):
    question["status"] = "answer_added" if question.get("answers") else "prepared"
    question["needsReview"] = True
    question["reviewReason"] = reason
    for answer in question.get("answers", []):
        if answer.get("confirmed"):
            answer["needsReview"] = True
            answer["reviewReason"] = reason


def variable_offer_dependencies(data):
    dependencies = {}
    def visit(value, offer_id):
        if isinstance(value, dict):
            if value.get("op") == "var" and value.get("name"):
                dependencies.setdefault(value["name"], set()).add(offer_id)
            for child in value.values():
                visit(child, offer_id)
        elif isinstance(value, list):
            for child in value:
                visit(child, offer_id)
    for offer in data["model"].get("offers", []):
        visit(offer, offer["id"])
    return dependencies


def invalidate(data, reason, offer_id=None, all_facts=False):
    affected = []
    dependent_facts = set()
    dependent_variables = set()
    offer_dependencies = variable_offer_dependencies(data)
    for fact in data["facts"]:
        if all_facts:
            fact.pop("pendingSourceReviewFingerprint", None)
        fact_variables = {t["variable_id"] for t in fact.get("targets", [])
                          if t.get("kind") == "variable" and t.get("variable_id")}
        depends_on_offer = offer_id and (fact.get("offer_id") == offer_id
            or offer_id in fact.get("dependent_offer_ids", [])
            or any(offer_id in offer_dependencies.get(v, set()) for v in fact_variables))
        if all_facts or depends_on_offer:
            dependent_facts.add(fact["id"])
            dependent_variables.update(fact_variables)
            if fact.get("confirmation") == "confirmed":
                if offer_id and not all_facts and fact.get("origin") != "human":
                    fact["pendingSourceReviewFingerprint"] = fact_fingerprint(fact)
                fact["confirmation"] = "needs_review"
                affected.append(fact["id"])
    for variable in data["model"].get("variables", []):
        if dependent_facts.intersection(variable.get("evidence_ids", [])):
            dependent_variables.add(variable["id"])
    dependent_variables.update(v for v, offers in offer_dependencies.items() if offer_id in offers)
    for question in data["questions"]:
        variable_ids = question.get("variable_ids") or [question.get("variable_id", question.get("variable", question["id"]))]
        if all_facts or (offer_id and (question.get("offer_id") == offer_id
                or question.get("issue", {}).get("offer_id") == offer_id
                or dependent_variables.intersection(variable_ids))):
            _review_question(question, reason)
    if data.get("approval"):
        data["approval"]["current"] = False
    for decision in data["decisions"]:
        decision["current"] = False
        decision["reviewReason"] = reason
    data["impact"] = [{"reason": reason, "factIds": affected, "offerId": offer_id,
                        "decisionIds": [x["id"] for x in data["decisions"]]}]


def compute(data):
    from packages.domain import evaluate
    model_requirements(data)
    analysis = evaluate(data["model"])
    old = {q["id"]: q for q in data["questions"]}
    questions = []
    for question in analysis.get("questions", []):
        question = dict(question)
        question.setdefault("id", question.get("variable_id", question.get("variable", "")))
        prior = old.get(question["id"], {})
        for key in ("status", "assignee", "dueAt", "answers", "needsReview", "reviewReason"):
            question[key] = prior.get(key, [] if key == "answers" else "prepared" if key == "status" else None)
        if prior.get("status") == "resolved":
            _review_question(question, "Aktualny model ponownie wymaga wyjaśnienia tej niewiadomej.")
        questions.append(question)
    # Preserve answered questions in the audit-visible workflow.
    questions.extend(q for q in data["questions"] if q["id"] not in {x["id"] for x in questions} and q.get("answers"))
    data["questions"] = questions
    data["analysis"] = analysis
    return analysis


def fact_fingerprint(fact):
    return digest({k: fact.get(k) for k in ("key", "value", "unit", "condition", "scope", "evidence", "target", "targets")})


def extraction_cache_key(documents, requirements):
    from .ai import PROMPT_VERSION, SCHEMA_VERSION, NORMALIZER_VERSION
    from .extraction import parser_cache_key
    semantic_requirements = {key: value for key, value in requirements.items() if key != "confirmed"}
    return digest([[(d["id"], d["sha256"], d.get("relation"), d.get("replacesId"),
                     d.get("relationConfirmed"), d.get("documentDate")) for d in documents], semantic_requirements,
                   settings.ai_model, os.getenv("AI_THINKING_LEVEL", "low"), parser_cache_key(),
                   PROMPT_VERSION, SCHEMA_VERSION, NORMALIZER_VERSION, os.getenv("OCR_LANGUAGES", "pol+eng")])


def affected_offer_ids(data):
    documents = [d for d in data["documents"] if d.get("active", True)]
    groups = {identifier: [d for d in documents if d["offerId"] == identifier]
              for identifier in dict.fromkeys(d["offerId"] for d in documents)}
    affected = {identifier for identifier, group in groups.items()
                if any(d.get("status") in {"pending", "needs_review"}
                       or d.get("extractionCacheKey") != extraction_cache_key(group, data["requirements"]) for d in group)}
    return affected or set(groups)


def validate_fact_confirmation(fact):
    if fact.get("conflict") or fact.get("condition_unresolved"):
        fail("unverified_fact", "Rozstrzygnij konflikt lub warunek przed potwierdzeniem.")
    if fact.get("origin") == "human":
        if not fact.get("author") or not fact.get("reason"):
            fail("missing_provenance", "Własne ustalenie wymaga autora i uzasadnienia.")
    elif not fact.get("evidence") or any(not e.get("quote_validated") for e in fact["evidence"]):
        fail("unverified_fact", "Sprawdź istniejący cytat lub dodaj własne ustalenie z uzasadnieniem.")


def purge_source(payload, document_id, offer_id):
    """Erase source-derived content and its dependency closure, also in history.

    The source-to-model mapping can be incomplete after manual edits. The entire
    affected offer and saved comparison decisions therefore require rebuilding.
    Unrelated source files and offer confirmations remain available.
    """
    payload = copy.deepcopy(payload)
    def references(value, identifiers):
        if isinstance(value, dict):
            return any(references(v, identifiers) for v in value.values())
        if isinstance(value, list):
            return any(references(v, identifiers) for v in value)
        return isinstance(value, str) and value in identifiers
    # The deletion audit marker is not source content. Replaying it against a
    # later backup must preserve a model rebuilt from the remaining documents.
    if not references({k: v for k, v in payload.items() if k != "sourceDeletion"}, {document_id}):
        return payload
    facts = payload.get("facts", [])
    removed_facts = {f["id"] for f in facts if f.get("offer_id") == offer_id or offer_id in f.get("dependent_offer_ids", []) or f.get("key") == "manual_model"
                     or any(e.get("source_id") == document_id for e in f.get("evidence", []))}
    model = payload["model"]
    removed_variables = {v["id"] for v in model.get("variables", [])
                         if v["id"].startswith(offer_id + ":") or set(v.get("evidence_ids", [])) & removed_facts}
    removed_variables.update(v for v, offers in variable_offer_dependencies(payload).items() if offer_id in offers)
    # Some authored models use shared, unprefixed variable names.
    for offer in model.get("offers", []):
        if offer["id"] == offer_id:
            offer.clear()
            offer.update(id=offer_id, name="Oferta " + offer_id, cost_items=[], scope_confirmed=None)
    dependencies = {document_id} | removed_facts | removed_variables
    payload["documents"] = [d for d in payload.get("documents", []) if d["id"] != document_id]
    for document in payload["documents"]:
        if document.get("replacesId") == document_id:
            document.pop("replacesId", None)
    payload["facts"] = [f for f in facts if f["id"] not in removed_facts and not references(f, dependencies)]
    model["variables"] = [v for v in model.get("variables", []) if v["id"] not in removed_variables]
    model["constraints"] = [c for c in model.get("constraints", []) if not references(c, dependencies)]
    model["issues"] = [i for i in model.get("issues", []) if i.get("offer_id") != offer_id and not references(i, dependencies)]
    model["issues"].append({"code": "source_removed", "message": "Usunięto źródło. Odtwórz model tej oferty z zachowanych materiałów.",
                            "offer_id": offer_id, "blocking": True})
    payload["questions"] = [q for q in payload.get("questions", []) if not references(q, dependencies | {offer_id})]
    payload["analysis"] = None
    payload["decisions"] = []
    payload["approval"] = None
    payload["impact"] = []
    payload.pop("analysisProvenance", None)
    payload["sourceDeletion"] = {"id": document_id, "at": now()}
    payload["pendingAnalysis"] = True
    for document in payload["documents"]:
        if document.get("offerId") == offer_id and document.get("active", True):
            document["status"] = "pending"
    return payload


def resolve_money_representation(data, fact):
    """A reviewed currency representation does not answer a scope question.

    Validate its economic amount against the unchanged typed model and its exact
    source quote. This also handles stated totals intentionally absent from the
    additive model. Only this fact's unit issue is removed.
    """
    model = data["model"]
    key = str(fact.get("key") or "")
    if not (key in {"price", "cost", "deposit", "payment", "cancellation"} or key.startswith(("price_", "cost:", "variable:"))):
        fail("invalid_money_unit", "Jednostkę waluty można poprawić tylko dla ustalenia kwotowego.")
    offer = next((item for item in model["offers"] if item["id"] == fact.get("offer_id")), {})
    currency = offer.get("currency") or model.get("currency")
    factor = Decimal(10) ** model.get("minor_unit", 2)
    unit = str(fact.get("unit") or "").strip().lower()
    try:
        if isinstance(fact.get("value"), bool):
            raise ValueError()
        amount = Decimal(str(fact["value"]).replace(",", "."))
        if unit in {"major", str(currency).lower()} or currency == "PLN" and unit in {"zl", "zł"}:
            amount *= factor
        elif unit not in {"minor", "grosz", "grosze", "gr", "cent", "cents"}:
            raise ValueError()
        if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
            raise ValueError()
    except (InvalidOperation, ValueError, TypeError):
        fail("invalid_money", "Podaj poprawną kwotę i jednoznaczną jednostkę waluty.")
    evidence = fact.get("evidence") or []
    if not evidence or not all(item.get("quote_validated") for item in evidence):
        fail("unverified_fact", "Najpierw sprawdź cytat źródłowy tej kwoty.")
    currency_names = [str(currency)] + (["zł", "zl"] if currency == "PLN" else [])
    number_pattern = r"(?<![\w])[-+]?\d{1,3}(?:[ \u00a0,.]\d{3})+(?:[,.]\d{1,2})?|(?<![\w])[-+]?\d+(?:[,.]\d{1,2})?"
    price_pattern = r"(" + number_pattern + r")\s*(?:" + "|".join(re.escape(name) for name in currency_names) + r")(?!\w)"
    quoted = set()
    for item in evidence:
        for raw in re.findall(price_pattern, item["quote"], flags=re.IGNORECASE):
            token = raw.replace(" ", "").replace("\u00a0", "")
            decimal = re.search(r"[,.](\d{1,2})$", token)
            token = (token[:decimal.start()].replace(",", "").replace(".", "") + "." + decimal.group(1)
                     if decimal else token.replace(",", "").replace(".", ""))
            quoted.add(Decimal(token) * factor)
    if amount not in quoted:
        fail("unit_correction_not_supported", "Poprawiona jednostka i kwota nie odpowiadają kwocie w cytacie. Sprawdź źródło.")

    known = set()
    def monetary_values(expression):
        if expression.get("op") == "literal":
            known.add(Decimal(str(expression["value"])))
        elif expression.get("op") == "var":
            variable = next((v for v in model.get("variables", []) if v["id"] == expression["name"]), {})
            for raw in [*variable.get("values", []), variable.get("lower"), variable.get("upper")]:
                if raw is not None and not isinstance(raw, bool):
                    known.add(Decimal(str(raw)))
        elif expression.get("op") == "mul":
            monetary_values(expression["args"][0])  # The second argument is quantity.
        elif expression.get("op") == "sum":
            for child in expression["args"]:
                monetary_values(child)
    for target in fact.get("targets", []):
        if target.get("kind") == "variable":
            monetary_values({"op": "var", "name": target["variable_id"]})
        elif target.get("kind") == "cost":
            target_offer = next((o for o in model["offers"] if o["id"] == target.get("offer_id", fact.get("offer_id"))), {})
            item = next((c for c in target_offer.get("cost_items", []) if c["id"] == target.get("cost_id")), None)
            if item:
                monetary_values(item["amount"])
    proof = {"amountMinor": int(amount), "evidenceHash": digest(evidence)}
    if known and amount not in known and fact.get("representationProof") != proof:
        fail("unit_correction_changes_cost", "Ta zmiana zmienia również kwotę w rachunku. Popraw odpowiedni składnik modelu lub dodaj nowe ustalenie.")
    # A later supplier answer may legitimately narrow a variable to zero. The
    # earlier reviewed representation of its quoted nonzero possibility remains
    # valid and must neither reopen nor overwrite that answer.
    fact["representationProof"] = proof
    resolved = [issue for issue in model.get("issues", [])
                if issue.get("message") == "conflict:money_unit:" + fact["id"]
                and issue.get("offer_id") == fact.get("offer_id")]
    if resolved:
        fact.setdefault("resolvedIssues", []).extend(resolved)
        model["issues"] = [issue for issue in model["issues"] if issue not in resolved]
    fact["conflict"] = False
    fact.pop("review_reason", None)


def apply_fact(data, fact):
    """Only bounded JSON field updates, no evaluation of model-supplied paths."""
    if fact.get("correctionKind") == "money_representation":
        resolve_money_representation(data, fact)
        return
    from packages.domain.engine import money_to_minor
    from packages.domain.models import ComparisonModel
    model = data["model"]
    offer = next((x for x in model["offers"] if x["id"] == fact.get("offer_id")), None)
    key = fact.get("key")
    value = fact["value"]
    fields = {"participants", "microphones", "ready_at", "service_start", "service_end", "scope_confirmed", "currency", "tax_basis", "tax_rate", "tax_source"}
    targets = copy.deepcopy(fact.get("targets") or [])
    target = fact.get("target")
    if not targets:
        if key in fields:
            targets = [{"kind": "offer", "offer_id": fact.get("offer_id"), "field": key}]
        elif isinstance(target, dict):
            targets = [{**target, "cost_id": target.get("cost_id", target.get("id"))}]
        elif key and key.startswith("cost:"):
            targets = [{"kind": "cost", "offer_id": fact.get("offer_id"), "cost_id": key[5:]}]
        elif key and key.startswith("variable:"):
            targets = [{"kind": "variable", "variable_id": key[9:]}]
        elif key == "manual_model":
            try:
                data["model"] = ComparisonModel.model_validate(value).model_dump(mode="json", exclude_none=True, exclude_unset=True)
            except ValueError:
                fail("invalid_fact", "Model nie spełnia zamkniętego schematu obliczeń.")
            return
    if not targets and key in {"price", "deposit", "payment", "cancellation"}:
        fail("unmapped_cost_correction", "Ta kwota nie ma samodzielnego składnika w rachunku. Popraw powiązany składnik lub model, aby zachować zgodność sumy i zakresu.")

    def money(raw, chosen_offer):
        if isinstance(raw, bool):
            fail("invalid_money", "Kwota musi być liczbą, nie wartością logiczną.")
        try:
            amount = Decimal(str(raw).replace(",", "."))
            if not amount.is_finite() or amount < 0:
                raise InvalidOperation
            unit = str(fact.get("unit") or "").strip().lower()
            if unit in {"minor", "grosz", "grosze", "gr", "cent", "cents"}:
                if amount != amount.to_integral_value():
                    raise InvalidOperation
                return int(amount)
            currency = (chosen_offer or {}).get("currency") or model.get("currency")
            if unit in {str(currency).lower(), "major"} or currency == "PLN" and unit in {"zł", "zl"}:
                return money_to_minor(amount, (chosen_offer or {}).get("minor_unit", model.get("minor_unit", 2)))
        except (InvalidOperation, ValueError, TypeError):
            fail("invalid_money", "Podaj nieujemną kwotę w jednostce tego ustalenia.")
        fail("ambiguous_money_unit", "Ustalenie nie ma jednoznacznej jednostki kwoty. Popraw model z jawną jednostką.")

    variable_targets = {t.get("variable_id") for t in targets if t.get("kind") == "variable"}

    def expression_variables(expression):
        if isinstance(expression, dict):
            found = {expression["name"]} if expression.get("op") == "var" else set()
            return found | set().union(*(expression_variables(v) for v in expression.values()))
        if isinstance(expression, list):
            return set().union(*(expression_variables(v) for v in expression))
        return set()

    for mapping in targets:
        kind = mapping.get("kind")
        chosen = next((o for o in model["offers"] if o["id"] == mapping.get("offer_id", fact.get("offer_id"))), offer)
        if kind == "offer" and mapping.get("field") in fields and chosen:
            field = mapping["field"]
            if field in {"participants", "microphones"} and (type(value) is not int or value < 0):
                fail("invalid_fact", "Liczba musi być nieujemną liczbą całkowitą.")
            if field == "scope_confirmed" and type(value) is not bool:
                fail("invalid_fact", "Potwierdzenie zakresu musi mieć wartość true albo false.")
            chosen[field] = value
            # A human resolution replaces the active interpretation, not the source quote.
            resolved = [issue for issue in model.get("issues", []) if issue.get("offer_id") == chosen["id"]
                        and issue.get("message") in {"missing:" + field, "conflict:" + field}]
            if resolved:
                fact.setdefault("resolvedIssues", []).extend(resolved)
                model["issues"] = [issue for issue in model["issues"] if issue not in resolved]
            for other in data["facts"]:
                if other["id"] != fact["id"] and other.get("offer_id") == chosen["id"] and other.get("key") == field and other.get("conflict"):
                    other.update(overriddenBy=fact["id"], critical=False, confirmation="superseded")
        elif kind == "variable":
            variable = next((v for v in model["variables"] if v["id"] == mapping.get("variable_id")), None)
            if variable is None:
                fail("unknown_target", "Niewiadoma tego ustalenia nie istnieje w aktualnym modelu.")
            corrected = money(value, chosen) if variable.get("unit") == "minor" else value
            if corrected is None or isinstance(corrected, (list, dict)):
                fail("invalid_fact", "Podaj pojedynczą wartość tej niewiadomej.")
            variable.update(kind="enum", values=[corrected], complete=True, source="human:" + fact["id"])
            for bound in ("lower", "upper", "step"):
                variable.pop(bound, None)
        elif kind == "cost" and chosen:
            item = next((c for c in chosen["cost_items"] if c["id"] == mapping.get("cost_id")), None)
            if item is None:
                fail("unknown_target", "Składnik kosztu nie istnieje w aktualnym modelu.")
            expression = item["amount"]
            if expression_variables(expression) & variable_targets:
                continue
            # A corrected unit price keeps the documented quantity multiplier.
            if expression.get("op") == "mul" and expression["args"][0].get("op") == "literal":
                expression["args"][0]["value"] = money(value, chosen)
            elif expression.get("op") == "literal":
                expression["value"] = money(value, chosen)
            elif expression.get("op") == "var":
                variable = next((v for v in model["variables"] if v["id"] == expression["name"]), None)
                if variable is None:
                    fail("unknown_target", "Niewiadoma kosztu nie istnieje.")
                variable.update(kind="enum", values=[money(value, chosen)], complete=True, source="human:" + fact["id"])
                for bound in ("lower", "upper", "step"):
                    variable.pop(bound, None)
            else:
                fail("ambiguous_cost_correction", "Złożony rachunek wymaga poprawy odpowiedniej niewiadomej lub modelu.")
        else:
            fail("unknown_target", "Nie można przypisać poprawki do aktualnego modelu.")
    try:
        ComparisonModel.model_validate(data["model"])
    except ValueError:
        fail("invalid_fact", "Wartość nie odpowiada typowi pola w modelu obliczeń.")


def job_public(job):
    return {"id": job.id, "caseId": job.case_id, "inputRevision": job.input_revision,
            "status": job.status, "stage": job.stage, "attempts": job.attempts,
            "error": job.error, "createdAt": job.created_at, "updatedAt": job.updated_at,
            "pagesRead": job.data.get("pagesRead", 0), "pagesTotal": job.data.get("pagesTotal", 0),
            "filesRead": job.data.get("filesRead", 0), "filesTotal": job.data.get("filesTotal", 0)}


def detail(db, case, role):
    data = copy.deepcopy(case.data)
    documents = data.get("documents", [])
    for doc in documents:
        doc.pop("storagePath", None)
        for page in doc.get("pages", []):
            page.pop("source_image", None)
        doc["fileUrl"] = f"/api/cases/{case.id}/documents/{doc['id']}/file"
    members = [{"userId": case.owner_id, "role": "owner", "name": (db.get(User, case.owner_id).name if db.get(User, case.owner_id) else "Owner")}]
    for member in db.scalars(select(Member).where(Member.case_id == case.id)):
        user = db.get(User, member.user_id)
        members.append({"userId": member.user_id, "role": member.role, "name": user.name if user else member.user_id})
    history = [{"revision": rev.revision, "author": rev.author, "action": rev.action, "createdAt": rev.created_at}
               for rev in db.scalars(select(Revision).where(Revision.case_id == case.id).order_by(Revision.revision.desc()))]
    jobs = [job_public(j) for j in db.scalars(select(Job).where(Job.case_id == case.id).order_by(Job.created_at.desc()))]
    usage = list(db.scalars(select(Usage).where(Usage.case_id == case.id)))
    status = "pending_analysis" if data.get("pendingAnalysis") else data.get("analysis", {}).get("status", "draft") if data.get("analysis") else "draft"
    return {**data, "id": case.id, "title": case.title, "revision": case.revision, "updatedAt": case.updated_at,
            "status": status, "role": role, "offers": data["model"].get("offers", []), "documents": documents,
            "history": history, "members": members, "jobs": jobs,
            "retention": {"caseDays": settings.retention_days, "demoHours": settings.demo_retention_hours,
                          "backupDays": settings.backup_retention_days},
            "usage": {"estimatedUsd": sum(u.reserved for u in usage),
                      "measuredUsd": sum(u.actual or 0 for u in usage), "unsettledCalls": sum(u.actual is None for u in usage),
                      "priceDate": "2026-10-03", "priceSource": "https://ai.google.dev/gemini-api/docs/pricing",
                      "includes": "Model tokens only. OCR, storage and hosting excluded."}}


def delete_case(db, case):
    # Tombstone is also exported by backup; contains no customer content.
    db.merge(Tombstone(case_id=case.id))
    # Public demo deletion removes source content, while a content-free cost
    # ledger still enforces the same day's global/account budget after reset.
    if settings.guest_enabled:
        for usage in db.scalars(select(Usage).where(Usage.case_id == case.id)):
            usage.case_id = ""
            usage.job_id = ""
            usage.details = {"cost_type": "deleted_public_demo", "model": settings.ai_model}
    for table in (Revision, Member, Invitation, Job, Usage):
        db.execute(delete(table).where(table.case_id == case.id))
    path = (settings.file_storage / case.id).resolve()
    if path.parent != settings.file_storage.resolve():
        raise ValueError("Unsafe storage path")
    if path.exists():
        shutil.rmtree(path)
    db.delete(case)


def reserve_usage(db, case_id, user_id, job_id, estimated):
    day = now()[:10]
    rows = list(db.scalars(select(Usage)))
    effective = lambda row: row.actual if row.actual is not None else row.reserved
    total_case = sum(effective(r) for r in rows if r.case_id == case_id)
    total_day = sum(effective(r) for r in rows if r.day == day)
    total_account = sum(effective(r) for r in rows if r.day == day and r.user_id == user_id)
    if estimated > 0 and (total_case + estimated > settings.case_budget or total_day + estimated > settings.daily_budget or total_account + estimated > settings.account_budget):
        fail("budget_exceeded", "Osiągnięto limit kosztu analizy. Zapisane dane pozostają dostępne.", 429)
    usage = Usage(case_id=case_id, user_id=user_id, job_id=job_id, day=day, reserved=estimated,
                  actual=None, details={"model": settings.ai_model, "price_date": "2026-10-03"})
    db.add(usage)
    db.flush()
    return usage


def release_unstarted_usage(db, job):
    if job.status == "queued" and job.attempts == 0:
        for usage in db.scalars(select(Usage).where(Usage.job_id == job.id)):
            usage.actual = 0
            usage.details = {**usage.details, "usage_complete": True, "cost_type": "cancelled_before_execution",
                             "input_tokens": 0, "output_tokens": 0, "attempt_count": 0}
