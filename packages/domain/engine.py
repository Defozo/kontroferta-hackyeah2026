"""Exact finite comparison and a one-variable affine partition solver.

No text from a document is executed. Every witness is an evaluated admissible
scenario. Complete means exhaustive *within the explicitly supplied model*.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from fractions import Fraction
from itertools import combinations, product
from math import ceil, floor, prod
import re
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from .models import ComparisonModel, Expression, Offer

D = Decimal
ZERO = D(0)
ONE = D(1)


class ModelError(ValueError):
    pass


def number(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ModelError("Expected a number, received a boolean or missing value")
    try:
        result = value if isinstance(value, D) else D(value) if type(value) is int else D(str(value).replace(",", "."))
        if not result.is_finite():
            raise ModelError("Non-finite number")
        return result
    except InvalidOperation as exc:
        raise ModelError(f"Not a decimal number: {str(value)[:40]}") from exc


def scalar(value):
    if isinstance(value, Fraction):
        return value
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d+/[1-9]\d*", value):
        return Fraction(value)
    try:
        return number(value)
    except ModelError:
        return value


def serial(value):
    if isinstance(value, Fraction):
        if value.denominator == 1:
            return value.numerator
        decimal = D(value.numerator) / D(value.denominator)
        return serial(decimal) if Fraction(decimal) == value else str(value)
    if isinstance(value, D):
        return int(value) if value == value.to_integral_value() else format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: serial(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [serial(v) for v in value]
    return value


def money_to_minor(amount: str | Decimal | int, minor_unit: int = 2) -> int:
    """Parse a major-unit amount and round once, half away from zero."""
    return int((number(amount) * D(10) ** minor_unit).quantize(ONE, rounding=ROUND_HALF_UP))


def _numeric(value):
    return value if isinstance(value, Fraction) else number(value)


def _rounded_minor(raw, factor):
    if isinstance(raw, Fraction):
        # Analytic boundaries may be nonterminating rationals such as 1/3.
        # Keep these exact instead of inventing a nearby Decimal witness.
        exact = raw * Fraction(factor)
        sign = -1 if exact < 0 else 1
        whole, remainder = divmod(abs(exact.numerator), exact.denominator)
        return sign * (whole + (2 * remainder >= exact.denominator))
    return int((number(raw) * factor).quantize(ONE, rounding=ROUND_HALF_UP))


def parse_moment(value: str, zone: str = "Europe/Warsaw") -> datetime:
    """Reject relative, nonexistent and ambiguous local moments.

    Offset-bearing timestamps are unambiguous. Bare local times require a
    date and are localized only when exactly one UTC instant exists.
    """
    if "T" not in value and " " not in value:
        raise ModelError("A moment requires an explicit local date and time")
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        tz = ZoneInfo(zone)
    except (ValueError, KeyError) as exc:
        raise ModelError("Invalid date or time zone") from exc
    if moment.tzinfo:
        return moment.astimezone(timezone.utc)
    possible = set()
    for fold in (0, 1):
        candidate = moment.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc)
        if candidate.astimezone(tz).replace(tzinfo=None) == moment:
            possible.add(candidate)
    if len(possible) != 1:
        raise ModelError("Local time is ambiguous or nonexistent; provide an explicit UTC offset")
    return possible.pop()


def _boolean(value):
    if not isinstance(value, bool):
        raise ModelError("A logical operator requires boolean operands")
    return value


def evaluate_expression(expression: Expression | dict, assignment: dict, zone="Europe/Warsaw"):
    expr = Expression.model_validate(expression) if isinstance(expression, dict) else expression
    op = expr.op
    if op == "literal":
        return scalar(expr.value)
    if op == "var":
        if expr.name not in assignment:
            raise ModelError(f"Unknown variable: {expr.name}")
        return scalar(assignment[expr.name])
    if op == "date":
        return parse_moment(str(expr.value), expr.timezone or zone)
    ev = lambda e: evaluate_expression(e, assignment, zone)
    if op == "sum":
        values = [_numeric(ev(e)) for e in expr.args]
        return sum((Fraction(v) for v in values), Fraction(0)) if any(isinstance(v, Fraction) for v in values) else sum(values, ZERO)
    if op == "mul":
        a, b = _numeric(ev(expr.args[0])), _numeric(ev(expr.args[1]))
        return Fraction(a) * Fraction(b) if isinstance(a, Fraction) or isinstance(b, Fraction) else a * b
    if op == "if":
        return ev(expr.then if _boolean(ev(expr.condition)) else expr.otherwise)
    if op == "not":
        return not _boolean(ev(expr.arg))
    if op in ("and", "or"):
        values = [_boolean(ev(e)) for e in expr.args]
        return all(values) if op == "and" else any(values)
    left, right = ev(expr.left), ev(expr.right)
    if op in ("eq", "ne"):
        # Python considers True == 1; the typed AST intentionally does not.
        result = left == right and (isinstance(left, bool) == isinstance(right, bool))
        return result if op == "eq" else not result
    if isinstance(left, bool) or isinstance(right, bool) or left is None or right is None:
        raise ModelError("Order comparison requires comparable numbers, dates or text")
    try:
        return {"lt": lambda: left < right, "lte": lambda: left <= right,
                "gt": lambda: left > right, "gte": lambda: left >= right}[op]()
    except (TypeError, KeyError) as exc:
        raise ModelError("Unsupported comparison operands") from exc


def _issue(code, message, **kwargs):
    return {"code": code, "message": message, **kwargs}


def _factor(offer: Offer, model: ComparisonModel) -> Decimal:
    if not offer.currency:
        raise ModelError("Unknown currency")
    factor = D(10) ** (model.minor_unit - offer.minor_unit)
    if offer.currency != model.currency:
        rate = offer.exchange_rate
        if not rate or rate.from_currency != offer.currency or rate.to_currency != model.currency:
            raise ModelError("Currency conversion requires a matching exchange rate, date and source")
        try:
            datetime.fromisoformat(rate.as_of)
        except ValueError as exc:
            raise ModelError("Exchange rate requires an explicit date") from exc
        factor *= rate.rate
    if offer.tax_basis == "unknown":
        raise ModelError("Unknown net/gross price basis")
    if offer.tax_basis == "net":
        if offer.tax_rate is None or not offer.tax_source:
            raise ModelError("Net price requires an explicit tax rate and its source")
        factor *= ONE + offer.tax_rate
    return factor


def _static_checks(offer, model):
    reasons, issues = [], []
    req = model.requirements
    if offer.excluded_reason:
        return [_issue("excluded_by_user", offer.excluded_reason)], []
    for key in ("participants", "microphones"):
        required, actual = getattr(req, key), getattr(offer, key)
        if required is not None:
            if actual is None:
                issues.append(_issue("missing_requirement", f"Unknown {key}", offer_id=offer.id, field=key))
                reasons.append(_issue("unknown_" + key, f"Brak potwierdzenia: {key}"))
            elif actual < required:
                reasons.append(_issue(key, f"{key}: {actual} < {required}"))
    for requirement, field, direction in (("ready_by", "ready_at", "before"),
                                         ("service_start", "service_start", "before"),
                                         ("service_end", "service_end", "after")):
        required = getattr(req, requirement)
        if required:
            actual = getattr(offer, field)
            if actual is None:
                issues.append(_issue("missing_time", f"Unknown {field}", offer_id=offer.id, field=field))
                reasons.append(_issue("unknown_" + field, f"Brak terminu: {field}"))
            else:
                try:
                    a, b = parse_moment(actual, model.timezone), parse_moment(required, model.timezone)
                    if (direction == "before" and a > b) or (direction == "after" and a < b):
                        reasons.append(_issue(field, f"{actual} nie spełnia wymaganego terminu {required}"))
                except ModelError as exc:
                    issues.append(_issue("invalid_time", str(exc), offer_id=offer.id, field=field))
                    reasons.append(_issue("invalid_time", str(exc)))
    if offer.service_start and offer.service_end:
        try:
            if parse_moment(offer.service_end, model.timezone) < parse_moment(offer.service_start, model.timezone):
                issues.append(_issue("invalid_service_interval", "Service ends before it starts", offer_id=offer.id))
        except ModelError as exc:
            issues.append(_issue("invalid_time", str(exc), offer_id=offer.id))
    if req.scope_required and offer.scope_confirmed is not True:
        reasons.append(_issue("scope", "Zakres techniczny wymaga osobnego potwierdzenia"))
        if offer.scope_confirmed is None:
            issues.append(_issue("missing_scope", "Technical scope has not been established", offer_id=offer.id))
    if not any(item.category == "service" for item in offer.cost_items):
        issues.append(_issue("missing_price", "No full service price", offer_id=offer.id))
    try:
        _factor(offer, model)
    except ModelError as exc:
        issues.append(_issue("missing_price_basis", str(exc), offer_id=offer.id))
    return reasons, issues


def _scenario(model, assignment, static, identifier):
    ev = lambda e: evaluate_expression(e, assignment, model.timezone)
    if not all(_boolean(ev(c)) for c in model.constraints):
        return None
    costs, extras, exclusions, breakdown, feasible = {}, {}, {}, {}, []
    for offer in model.offers:
        reasons, invalid = static[offer.id]
        reasons = list(reasons)
        breakdown[offer.id] = []
        total, ancillary = 0, {"deposit": 0, "payment": 0, "cancellation": 0}
        if not offer.excluded_reason and not invalid:
            factor = _factor(offer, model)
            for item in offer.cost_items:
                if item.when is not None and not _boolean(ev(item.when)):
                    continue
                raw = _numeric(ev(item.amount))
                # Refundable deposits are not sales and do not receive service VAT.
                item_factor = factor
                if item.category == "deposit" and offer.tax_basis == "net":
                    item_factor /= ONE + offer.tax_rate
                amount = _rounded_minor(raw, item_factor)
                if amount < 0:
                    raise ModelError(f"Negative cost item {offer.id}/{item.id}; model a discount explicitly in the total")
                if item.category == "service":
                    total += amount
                else:
                    ancillary[item.category] += amount
                breakdown[offer.id].append({"id": item.id, "label": item.label,
                    "category": item.category, "amount_minor": amount, "unit": item.unit,
                    "evidence_ids": item.evidence_ids, "due_at": item.due_at})
            costs[offer.id] = total
            if model.budget_minor is not None and total > model.budget_minor:
                reasons.append(_issue("budget", "Przekroczony budżet", excess_minor=total - model.budget_minor))
            for index, condition in enumerate(offer.constraints):
                if not _boolean(ev(condition)):
                    reasons.append(_issue("condition", "Niespełniony warunek zakresu", condition_index=index))
            if not reasons:
                feasible.append(offer.id)
        else:
            costs[offer.id] = None
            reasons.extend(_issue("incomplete", i["message"]) for i in invalid)
        exclusions[offer.id] = reasons
        extras[offer.id] = ancillary
    minimum = min((costs[o] for o in feasible), default=None)
    winners = sorted(o for o in feasible if costs[o] == minimum)
    return {"id": identifier, "assignment": serial(assignment), "costs": costs,
            "feasible": sorted(feasible), "winners": winners, "exclusions": exclusions,
            "breakdown": breakdown, "ancillary": extras,
            "status": "no_feasible_offer" if not feasible else "tie" if len(winners) > 1 else "winner"}


def _intersection(scenarios, key):
    if not scenarios:
        return set()
    result = set(scenarios[0][key])
    for scenario in scenarios[1:]:
        result.intersection_update(scenario[key])
    return result


def decision_diversity(scenarios):
    """D(T) from the approved plan, including common co-winners and empty F."""
    if not scenarios or _intersection(scenarios, "winners"):
        return 0
    outcomes = {tuple(s["winners"]) for s in scenarios}
    return max(0, len(outcomes) - 1)


def _changed(a, b):
    return sorted(k for k in a["assignment"] if a["assignment"].get(k) != b["assignment"].get(k))


def _witness(scenarios, variable_ids=None):
    # Representative reduction is only a search preference, never a claim of
    # globally minimum differences. Keep separate answers for question witnesses.
    representatives = {}
    for s in scenarios:
        answers = tuple(repr(s["assignment"].get(k)) for k in (variable_ids or []))
        representatives.setdefault((tuple(s["winners"]), answers), s)
    groups = defaultdict(list)
    for s in representatives.values():
        groups[tuple(s["winners"])].append(s)
    best, best_rank = None, None
    outcome_groups = list(groups.values())
    for ga, gb in combinations(outcome_groups, 2):
        # Looking for differing answers can be done without quadratic products.
        candidates = [(ga[0], b) for b in gb] + [(a, gb[0]) for a in ga[1:]]
        for a, b in candidates:
            changed = _changed(a, b)
            if variable_ids and not any(k in changed for k in variable_ids):
                continue
            aw, bw = set(a["winners"]), set(b["winners"])
            kind = "winner_change" if aw and bw and aw.isdisjoint(bw) else "feasibility_change" if bool(aw) != bool(bw) else "tie_change"
            rank = (0 if kind == "winner_change" else 1 if kind == "feasibility_change" else 2, len(changed), a["id"], b["id"])
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best = {"kind": kind, "scenarios": [a, b], "changed_variables": changed,
                        "other_changed_variables": [k for k in changed if k not in (variable_ids or [])],
                        "minimality_proven": False}
    if variable_ids or (best and best["kind"] in ("winner_change", "feasibility_change")):
        return best
    if scenarios and not _intersection(scenarios, "winners") and all(s["winners"] for s in scenarios):
        # Pairwise intersecting winners may have empty overall intersection.
        selected, common = [], None
        for group in outcome_groups:
            s = group[0]
            next_common = set(s["winners"]) if common is None else common & set(s["winners"])
            if common is None or next_common != common:
                selected.append(s)
                common = next_common
            if not common:
                break
        return {"kind": "no_common_winner", "scenarios": selected,
                "changed_variables": sorted({k for a, b in combinations(selected, 2) for k in _changed(a, b)}),
                "minimality_proven": False}
    return best


def rank_questions(scenarios: list[dict], variables: list[dict] | list, complete=True):
    """Rank informative answer branches; unknown answers keep the same set S."""
    variables = [v.model_dump() if hasattr(v, "model_dump") else v for v in variables]
    diversity, ranked = decision_diversity(scenarios), []

    def question(items):
        keys = [v["id"] for v in items]
        groups = defaultdict(list)
        for s in scenarios:
            groups[tuple(repr(s["assignment"].get(k)) for k in keys)].append(s)
        branches = []
        for group in groups.values():
            branches.append({"answers": {k: group[0]["assignment"].get(k) for k in keys},
                             "scenario_count": len(group), "diversity": decision_diversity(group),
                             "common_winners": sorted(_intersection(group, "winners")),
                             "all_infeasible": all(not s["winners"] for s in group)})
        score = max((b["diversity"] for b in branches), default=None)
        return {"id": "+".join(keys), "variable_ids": keys,
                "text": " ".join(v.get("question") or f"Proszę wyjaśnić: {v.get('label') or v['id']}." for v in items),
                "score": score if complete else None, "difficulty": sum(v.get("difficulty", 0) for v in items),
                "needed": bool(diversity) or not complete, "branches": branches,
                "witness": _witness(scenarios, keys), "unknown_answer_reduces_scenarios": False,
                "heuristic": True, "kind": "pair" if len(keys) > 1 else "variable"}

    available = []
    for v in variables:
        answers = {repr(s["assignment"].get(v["id"])) for s in scenarios}
        if v.get("kind") == "open" or not v.get("complete", False):
            q = question([v])
            q.update(kind="model_gap", score=None, needed=True, witness=None,
                     reason="Najpierw trzeba określić pełną dziedzinę i jej źródło.")
            ranked.append(q)
        elif len(answers) > 1:
            available.append(v)
            ranked.append(question([v]))
    numeric_scores = [q["score"] for q in ranked if q["score"] is not None]
    if complete and diversity > 0 and numeric_scores and min(numeric_scores) >= diversity:
        for pair in combinations(available, 2):
            candidate = question(pair)
            if candidate["score"] < diversity:
                ranked.append(candidate)
    ranked.sort(key=lambda q: (0 if q["kind"] == "model_gap" else 1,
                               q["score"] if q["score"] is not None else 10**9,
                               q["difficulty"], q["id"]))
    return ranked


def _affine(expr, variable_id, assignment):
    """Return exact a,b for a*x+b; reject nonlinear or variable conditions."""
    if expr.op == "var" and expr.name == variable_id:
        return Fraction(1), Fraction(0)
    if expr.op in ("literal", "var"):
        return Fraction(0), Fraction(_numeric(evaluate_expression(expr, assignment)))
    if expr.op == "sum":
        parts = [_affine(e, variable_id, assignment) for e in expr.args]
        return sum((a for a, _ in parts), Fraction(0)), sum((b for _, b in parts), Fraction(0))
    if expr.op == "mul":
        a, b = _affine(expr.args[0], variable_id, assignment)
        c, d = _affine(expr.args[1], variable_id, assignment)
        if a and c:
            raise ModelError("Nonlinear interval expression requires a verified solver or clarification")
        return a * d + c * b, b * d
    if expr.op == "if":
        try:
            condition = evaluate_expression(expr.condition, assignment)
        except ModelError as exc:
            raise ModelError("An interval-dependent conditional cost requires clarification") from exc
        return _affine(expr.then if _boolean(condition) else expr.otherwise, variable_id, assignment)
    raise ModelError("Unsupported affine operator")


def _roots(expr, var, assignment):
    try:
        _boolean(evaluate_expression(expr, assignment))
        return []
    except ModelError:
        pass
    if expr.op in ("and", "or"):
        return [r for e in expr.args for r in _roots(e, var, assignment)]
    if expr.op == "not":
        return _roots(expr.arg, var, assignment)
    if expr.op in ("eq", "ne", "lt", "lte", "gt", "gte"):
        a, b = _affine(expr.left, var, assignment)
        c, d = _affine(expr.right, var, assignment)
        return [(d - b) / (a - c)] if a != c else []
    if expr.op == "literal" and isinstance(expr.value, bool):
        return []
    # Conditions independent of the continuous variable remain legal.
    _boolean(evaluate_expression(expr, assignment))
    return []


def _interval_assignments(model, interval, fixed, remaining_limit):
    lo, hi = Fraction(interval.lower), Fraction(interval.upper)
    step = Fraction(interval.step) if interval.step is not None else None
    # A money variable is integer-valued in its declared smallest units.
    if step is None and interval.unit == "minor":
        step = Fraction(1)
    points, thresholds, lines = {lo, hi}, [], {}
    item_lines = []
    for offer in model.offers:
        if offer.excluded_reason:
            continue
        factor = Fraction(_factor(offer, model))
        total_a, total_b = Fraction(0), Fraction(0)
        for item in offer.cost_items:
            if item.category != "service":
                continue
            if item.when:
                # Piecewise affine conditions are intentionally explicit gaps.
                if not _boolean(evaluate_expression(item.when, fixed)):
                    continue
            a, b = _affine(item.amount, interval.id, fixed)
            a, b = a * factor, b * factor
            item_lines.append((a, b))
            total_a, total_b = total_a + a, total_b + b
        lines[offer.id] = total_a, total_b
        if model.budget_minor is not None and total_a:
            root = (Fraction(model.budget_minor) - total_b) / total_a
            if lo <= root <= hi:
                points.add(root)
                thresholds.append({"variable_id": interval.id, "value": serial(root), "kind": "budget", "offer_ids": [offer.id]})
        for condition in offer.constraints:
            for root in _roots(condition, interval.id, fixed):
                if lo <= root <= hi:
                    points.add(root)
                    thresholds.append({"variable_id": interval.id, "value": serial(root), "kind": "constraint", "offer_ids": [offer.id]})
    for left, right in combinations(lines, 2):
        a, b = lines[left]
        c, d = lines[right]
        if a != c:
            root = (d - b) / (a - c)
            if lo <= root <= hi:
                points.add(root)
                thresholds.append({"variable_id": interval.id, "value": serial(root), "kind": "tie", "offer_ids": sorted([left, right])})
    for condition in model.constraints:
        for root in _roots(condition, interval.id, fixed):
            if lo <= root <= hi:
                points.add(root)

    integral_grid = step is not None and all((a * step).denominator == 1 and (a * lo + b).denominator == 1 for a, b in item_lines)
    if not integral_grid:
        # Rounding can create narrow tie bands or alternate ties when slopes are
        # equal. All half-minor-unit transitions must be included for a proof.
        for a, b in item_lines:
            if not a:
                continue
            low, high = sorted([a * lo + b, a * hi + b])
            first = ceil(low - Fraction(1, 2))
            last = floor(high - Fraction(1, 2))
            if last - first + len(points) > remaining_limit:
                raise ModelError("Interval rounding partitions exceed scenario limit; narrow the domain or raise the limit")
            for n in range(first, last + 1):
                root = (Fraction(n) + Fraction(1, 2) - b) / a
                if lo <= root <= hi:
                    points.add(root)
    sorted_points = sorted(points)
    representatives = set()
    regions = []
    if step:
        max_index = floor((hi - lo) / step)
        for point in sorted_points:
            index = (point - lo) / step
            lower_index = floor(index)
            for i in (lower_index - 1, lower_index, lower_index + 1):
                if 0 <= i <= max_index:
                    representatives.add(lo + step * i)
        # Every truth value is constant on each remaining integer-grid segment.
        for start, end in zip(sorted_points, sorted_points[1:]):
            i = floor((start - lo) / step) + 1
            j = ceil((end - lo) / step) - 1
            if i <= j:
                representatives.add(lo + i * step)
                regions.append({"from": serial(lo + i * step), "to": serial(lo + j * step), "step": serial(step)})
    else:
        representatives.update(sorted_points)
        for start, end in zip(sorted_points, sorted_points[1:]):
            representatives.add((start + end) / 2)
            regions.append({"from": serial(start), "to": serial(end), "bounds": "open"})
    return [{**fixed, interval.id: p} for p in sorted(representatives)], thresholds, regions


def evaluate(model: dict | ComparisonModel, *, accelerated: bool = True) -> dict:
    started = perf_counter()
    try:
        model = ComparisonModel.model_validate(model) if isinstance(model, dict) else model
    except ValidationError as exc:
        return {"status": "incomplete", "complete": False, "scenario_count": 0,
                "scenarios": [], "offers": [], "questions": [], "witnesses": [], "thresholds": [],
                "robust_feasible": [], "common_winners": [], "unique_winner": None,
                "issues": [_issue("invalid_model", e["msg"], path=list(e["loc"])) for e in exc.errors()],
                "duration_ms": round((perf_counter() - started) * 1000, 3)}
    excluded_offers = {offer.id for offer in model.offers if offer.excluded_reason}
    excluded_variables = set()
    if excluded_offers:
        def referenced_variables(value):
            if isinstance(value, dict):
                found = {value["name"]} if value.get("op") == "var" and value.get("name") else set()
                return found | set().union(*(referenced_variables(v) for v in value.values()))
            if isinstance(value, list):
                return set().union(*(referenced_variables(v) for v in value))
            return set()
        active_references = referenced_variables([c.model_dump() for c in model.constraints])
        excluded_references = set()
        for offer in model.offers:
            references = referenced_variables(offer.model_dump())
            if offer.id in excluded_offers:
                excluded_references.update(references)
            else:
                active_references.update(references)
        excluded_references.update(v.id for v in model.variables if any(v.id.startswith(identifier + ":") for identifier in excluded_offers))
        excluded_variables = excluded_references - active_references
        model = model.model_copy(update={
            "variables": [v for v in model.variables if v.id not in excluded_variables],
            "issues": [issue for issue in model.issues if issue.get("offer_id") not in excluded_offers
                       and issue.get("variable_id") not in excluded_variables]})
    issues = [{"code": issue.get("code", "input_issue"),
               "message": str(issue.get("message", "Unresolved input issue")), **issue} for issue in model.issues]
    for v in model.variables:
        if v.kind == "open" or not v.complete:
            issues.append(_issue("open_domain", "Dziedzina wymaga doprecyzowania", variable_id=v.id))
        if not v.source and not v.assumption:
            issues.append(_issue("domain_without_source", "Domain requires a source or explicit user assumption", variable_id=v.id))
    static = {o.id: _static_checks(o, model) for o in model.offers}
    for _, offer_issues in static.values():
        issues.extend(offer_issues)
    if accelerated and not issues and prod(len(v.values) for v in model.variables) >= 1000:
        from .vectorized import evaluate_integer_model
        optimized = evaluate_integer_model(model, static,
            {"limited": bool(excluded_offers), "excluded_offer_ids": sorted(excluded_offers),
             "excluded_variable_ids": sorted(excluded_variables)}, started)
        if optimized is not None:
            return optimized
    scenarios, thresholds, regions = [], [], []
    intervals = [v for v in model.variables if v.kind == "interval"]
    finite = [v for v in model.variables if v.kind != "interval"]
    domains = []
    for v in finite:
        # Decimal-normalized numbers eliminate duplicated textual encodings.
        unique = {}
        for value in v.values:
            normalized = scalar(value)
            unique.setdefault((type(normalized).__name__, repr(normalized.normalize()) if isinstance(normalized, D) else repr(normalized)), normalized)
        domains.append(list(unique.values()))
    checked, capped, solver_error = 0, False, False
    if len(intervals) > 1:
        issues.append(_issue("unsupported_multidimensional_interval", "Wielowymiarowe przedziały wymagają solvera lub doprecyzowania"))
    else:
        try:
            for values in product(*domains):
                fixed = dict(zip((v.id for v in finite), values))
                assignments = [fixed]
                if intervals:
                    assignments, new_thresholds, new_regions = _interval_assignments(model, intervals[0], fixed, model.max_scenarios - checked)
                    thresholds.extend(new_thresholds)
                    regions.extend(new_regions)
                for assignment in assignments:
                    if checked >= model.max_scenarios:
                        capped = True
                        break
                    checked += 1
                    scenario = _scenario(model, assignment, static, f"s{checked}")
                    if scenario:
                        scenarios.append(scenario)
                if capped:
                    break
        except (ModelError, InvalidOperation, TypeError, ValueError) as exc:
            solver_error = True
            issues.append(_issue("unsupported_calculation", str(exc)))
    if capped:
        issues.append(_issue("scenario_limit", "Osiągnięto limit scenariuszy. Doprecyzuj dziedziny lub zwiększ zakres obliczeń."))
    complete = not issues and not capped and not solver_error
    common = sorted(_intersection(scenarios, "winners"))
    robust = sorted(_intersection(scenarios, "feasible"))
    unique = common[0] if len(common) == 1 and all(len(s["winners"]) == 1 for s in scenarios) else None
    if not complete:
        status = "incomplete"
    elif not scenarios:
        status = "inconsistent"
    elif all(not s["feasible"] for s in scenarios):
        status = "no_feasible_offer"
    elif unique:
        status = "unique_winner"
    elif common:
        status = "common_winner"
    else:
        status = "needs_clarification"
    summary = []
    for o in model.offers:
        prices = [s["costs"][o.id] for s in scenarios if s["costs"][o.id] is not None]
        reason_map = {}
        for s in scenarios:
            for reason in s["exclusions"][o.id]:
                reason_map.setdefault(reason["code"], reason)
        summary.append({"id": o.id, "name": o.name or o.id,
                        "min_cost_minor": min(prices, default=None), "max_cost_minor": max(prices, default=None),
                        "always_feasible": complete and bool(scenarios) and o.id in robust,
                        "sometimes_feasible": any(o.id in s["feasible"] for s in scenarios),
                        "possible_winner": any(o.id in s["winners"] for s in scenarios),
                        "common_winner": complete and o.id in common, "exclusions": list(reason_map.values()),
                        "evidence_ids": o.evidence_ids, "scope_confirmed": o.scope_confirmed})
    questions = rank_questions(scenarios, model.variables, complete=complete) if not intervals else []
    if intervals:
        for variable in model.variables:
            if variable.kind != "interval":
                continue
            questions.append({"id": variable.id, "variable_ids": [variable.id],
                              "text": variable.question or f"Proszę wyjaśnić: {variable.label or variable.id}.",
                              "score": None, "difficulty": variable.difficulty,
                              "needed": bool(decision_diversity(scenarios)) or not complete,
                              "branches": [], "witness": _witness(scenarios, [variable.id]),
                              "thresholds": [t for t in thresholds if t["variable_id"] == variable.id],
                              "unknown_answer_reduces_scenarios": False,
                              "heuristic": False, "kind": "interval",
                              "reason": "Przedział jest opisany granicami analitycznymi; ranking skończonych odpowiedzi nie ma zastosowania."})
    domain_question_ids = {q["id"] for q in questions}
    gap_questions = []
    for i, issue in enumerate(issues):
        variable_id = issue.get("variable_id")
        if variable_id in domain_question_ids:
            continue
        gap_questions.append({"id": f"gap-{issue.get('offer_id', variable_id or 'model')}-{issue.get('field', issue['code'])}-{i}",
                              "variable_ids": [variable_id] if variable_id else [],
                              "text": "Proszę uzupełnić lub wyjaśnić: " + issue["message"],
                              "score": None, "difficulty": 0, "needed": True,
                              "branches": [], "witness": None,
                              "unknown_answer_reduces_scenarios": False,
                              "heuristic": False, "kind": "model_gap", "issue": issue})
    questions = gap_questions + questions
    witness = _witness(scenarios)
    # Never expose provisional intersections as proved robust/common claims.
    return {"schema_version": "1.0", "status": status, "complete": complete,
            "scope": {"limited": bool(excluded_offers), "excluded_offer_ids": sorted(excluded_offers),
                      "excluded_variable_ids": sorted(excluded_variables)},
            "currency": model.currency, "minor_unit": model.minor_unit,
            "rounding": "ROUND_HALF_UP, each cost item after explicit tax and currency conversion",
            "scenario_count": len(scenarios), "checked_count": checked,
            "scenarios": scenarios[:model.max_display_scenarios],
            "scenarios_truncated_for_display": len(scenarios) > model.max_display_scenarios,
            "method": "analytic_partition" if intervals else "exact_enumeration",
            "regions": regions, "offers": summary,
            "robust_feasible": robust if complete else [], "common_winners": common if complete else [],
            "unique_winner": unique if complete else None,
            "provisional_common_winners": common if not complete else [],
            "diversity": decision_diversity(scenarios), "questions": questions,
            "witnesses": [witness] if witness else [], "thresholds": thresholds,
            "issues": issues, "duration_ms": round((perf_counter() - started) * 1000, 3)}
