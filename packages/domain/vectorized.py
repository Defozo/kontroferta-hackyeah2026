"""Exact bounded integer enumeration, with compact arrays and lazy proof rows.

Every Cartesian-product assignment is checked. This is not sampling or an
interval approximation. Unsupported numeric forms and overflow risks fall back
to the Decimal/Fraction reference implementation before a result is returned.
"""
from decimal import Decimal
from fractions import Fraction
from itertools import combinations
from math import prod
from time import perf_counter

import numpy as np

LIMIT = 2**60


class NotApplicable(Exception):
    pass


def _integer(value):
    if type(value) is int:
        result = value
    elif isinstance(value, bool) or value is None:
        raise NotApplicable
    else:
        try:
            number = Decimal(str(value).replace(",", "."))
            if not number.is_finite() or number != number.to_integral_value():
                raise NotApplicable
            result = int(number)
        except (ValueError, ArithmeticError):
            raise NotApplicable
    if abs(result) >= LIMIT:
        raise NotApplicable
    return result


def evaluate_integer_model(model, static, scope, started):
    from .engine import _factor, _scenario, _witness
    if not model.variables or len(model.offers) > 63 or not model.offers:
        return None
    if any(v.kind != "enum" or not v.complete or not (v.source or v.assumption) for v in model.variables):
        return None
    rough_size = prod(len(v.values) for v in model.variables)
    if rough_size < 1000 or rough_size > model.max_scenarios * 2:
        return None
    try:
        domains = []
        kinds = []
        for variable in model.variables:
            kind = "bool" if variable.values and all(type(v) is bool for v in variable.values) else "number"
            if kind == "bool":
                values = list(dict.fromkeys(variable.values))
            elif all(type(value) is int and -LIMIT < value < LIMIT for value in variable.values):
                # Pydantic has already typed native integers. Preserve the exact
                # insertion order while deduplicating directly in C.
                values = list(dict.fromkeys(variable.values))
            else:
                values = list(dict.fromkeys(_integer(v) for v in variable.values))
            if not values:
                raise NotApplicable
            domains.append(values)
            kinds.append(kind)
        sizes = [len(d) for d in domains]
        count = prod(sizes)
        if count > model.max_scenarios or count < 1000:
            raise NotApplicable
        if model.budget_minor is not None and model.budget_minor >= LIMIT:
            raise NotApplicable
        columns, codes = {}, {}
        for index, variable in enumerate(model.variables):
            right = prod(sizes[index+1:])
            code = np.tile(np.repeat(np.arange(sizes[index], dtype=np.int64), right), prod(sizes[:index]))
            codes[variable.id] = code
            values = np.asarray(domains[index], dtype=np.bool_ if kinds[index] == "bool" else np.int64)[code]
            columns[variable.id] = (values, min(domains[index]), max(domains[index]), kinds[index])

        def bounded(value, low, high, kind="number"):
            if kind == "number" and max(abs(low), abs(high)) >= LIMIT:
                raise NotApplicable
            return value, low, high, kind

        def expression(expr):
            op = expr.op
            if op == "literal":
                if type(expr.value) is bool:
                    return expr.value, expr.value, expr.value, "bool"
                value = _integer(expr.value)
                return value, value, value, "number"
            if op == "var":
                if expr.name not in columns:
                    raise NotApplicable
                return columns[expr.name]
            if op in {"sum", "mul"}:
                operands = [expression(a) for a in expr.args]
                if any(a[3] != "number" for a in operands):
                    raise NotApplicable
                if op == "sum":
                    low, high = sum(a[1] for a in operands), sum(a[2] for a in operands)
                    # Bound each intermediate sum, including cancellation extremes.
                    if sum(max(abs(a[1]), abs(a[2])) for a in operands) >= LIMIT:
                        raise NotApplicable
                    return bounded(sum(a[0] for a in operands), low, high)
                a, b = operands
                corners = [a[x] * b[y] for x in (1, 2) for y in (1, 2)]
                if max(map(abs, corners)) >= LIMIT:
                    raise NotApplicable
                return bounded(a[0] * b[0], min(corners), max(corners))
            if op == "if":
                condition = expression(expr.condition)
                yes, no = expression(expr.then), expression(expr.otherwise)
                if condition[3] != "bool" or yes[3] != no[3]:
                    raise NotApplicable
                return bounded(np.where(condition[0], yes[0], no[0]), min(yes[1], no[1]), max(yes[2], no[2]), yes[3])
            if op in {"and", "or", "not"}:
                operands = [expression(a) for a in expr.args] if op != "not" else [expression(expr.arg)]
                if any(a[3] != "bool" for a in operands):
                    raise NotApplicable
                value = operands[0][0]
                if op == "not":
                    value = np.logical_not(value)
                else:
                    for operand in operands[1:]:
                        value = np.logical_and(value, operand[0]) if op == "and" else np.logical_or(value, operand[0])
                return value, False, True, "bool"
            if op in {"eq", "ne", "lt", "lte", "gt", "gte"}:
                left, right = expression(expr.left), expression(expr.right)
                if op in {"eq", "ne"} and left[3] != right[3]:
                    return op == "ne", False, True, "bool"
                if op not in {"eq", "ne"} and (left[3] != "number" or right[3] != "number"):
                    raise NotApplicable
                compare = {"eq": np.equal, "ne": np.not_equal, "lt": np.less, "lte": np.less_equal, "gt": np.greater, "gte": np.greater_equal}[op]
                return compare(left[0], right[0]), False, True, "bool"
            raise NotApplicable

        def boolean(expr):
            value = expression(expr)
            if value[3] != "bool":
                raise NotApplicable
            return value[0]

        admitted = np.ones(count, dtype=np.bool_)
        for condition in model.constraints:
            admitted &= boolean(condition)
        valid_indices = np.flatnonzero(admitted)
        if not len(valid_indices):
            raise NotApplicable  # Preserve the reference inconsistent-data response.
        prices = []
        feasible = []
        condition_failures = []
        for offer in model.offers:
            reasons, invalid = static[offer.id]
            if invalid:
                raise NotApplicable
            if offer.excluded_reason:
                prices.append(None)
                feasible.append(np.zeros(count, dtype=np.bool_))
                condition_failures.append(np.zeros(count, dtype=np.bool_))
                continue
            factor = _factor(offer, model)
            total = np.zeros(count, dtype=np.int64)
            total_bound = 0
            for item in offer.cost_items:
                raw, low, high, kind = expression(item.amount)
                if kind != "number":
                    raise NotApplicable
                conversion = factor / (1 + offer.tax_rate) if item.category == "deposit" and offer.tax_basis == "net" else factor
                rational = Fraction(conversion)
                numerator, denominator = rational.numerator, rational.denominator
                if max(abs(low), abs(high)) * abs(numerator) * 2 + denominator >= LIMIT or denominator >= LIMIT:
                    raise NotApplicable
                scaled = raw * numerator
                amount = np.where(scaled < 0, -1, 1) * ((np.abs(scaled) * 2 + denominator) // (denominator * 2))
                if item.when is not None:
                    amount = np.where(boolean(item.when), amount, 0)
                if np.any(np.asarray(amount)[()] < 0):
                    raise NotApplicable
                if item.category == "service":
                    total_bound += int(np.max(amount))
                    if total_bound >= LIMIT:
                        raise NotApplicable
                    total += amount
            available = np.full(count, not reasons, dtype=np.bool_)
            if model.budget_minor is not None:
                available &= total <= model.budget_minor
            failed_conditions = np.zeros(count, dtype=np.bool_)
            for condition in offer.constraints:
                condition_met = boolean(condition)
                failed_conditions |= np.logical_not(condition_met)
                available &= condition_met
            prices.append(total)
            feasible.append(available)
            condition_failures.append(failed_conditions)
        minimum = np.full(count, LIMIT, dtype=np.int64)
        for price, available in zip(prices, feasible):
            if price is not None:
                minimum = np.minimum(minimum, np.where(available, price, LIMIT))
        outcome = np.zeros(count, dtype=np.uint64)
        for index, (price, available) in enumerate(zip(prices, feasible)):
            if price is not None:
                outcome |= np.where(available & (price == minimum), np.uint64(1 << index), np.uint64(0))
        outcomes = outcome[admitted]
        distinct, first = np.unique(outcomes, return_index=True)
        if len(distinct) > 128:
            raise NotApplicable  # Complex witness set uses the full reference search.
        common = int(np.bitwise_and.reduce(outcomes))
        any_winner = bool(np.any(outcomes))
        diversity = 0 if common or not any_winner else len(distinct)-1

        def decode(mask):
            return sorted(offer.id for index, offer in enumerate(model.offers) if int(mask) & (1 << index))

        def assignment(index):
            return {variable.id: domains[i][int(codes[variable.id][index])] for i, variable in enumerate(model.variables)}

        proof_cache = {}
        def proof(index):
            index = int(index)
            if index not in proof_cache:
                row = _scenario(model, assignment(index), static, f"s{index+1}")
                # Each displayed configuration and counterexample is also checked
                # by the original constraint engine, never by array math alone.
                if row is None or row["winners"] != decode(outcome[index]):
                    raise NotApplicable
                if any(row["costs"][o.id] != (None if prices[i] is None else int(prices[i][index])) for i, o in enumerate(model.offers)):
                    raise NotApplicable
                proof_cache[index] = row
            return proof_cache[index]

        representative_indices = sorted(int(valid_indices[i]) for i in first)
        witness = _witness([proof(i) for i in representative_indices])

        def question(items):
            keys = [v.id for v in items]
            question_codes = np.zeros(count, dtype=np.int64)
            for variable in items:
                question_codes = question_codes * len(domains[next(i for i, v in enumerate(model.variables) if v.id == variable.id)]) + codes[variable.id]
            groups, positions, inverse, counts = np.unique(question_codes[admitted], return_index=True, return_inverse=True, return_counts=True)
            group_common = np.full(len(groups), np.uint64((1 << len(model.offers))-1), dtype=np.uint64)
            group_any = np.zeros(len(groups), dtype=np.uint64)
            np.bitwise_and.at(group_common, inverse, outcomes)
            np.bitwise_or.at(group_any, inverse, outcomes)
            order = np.lexsort((outcomes, inverse))
            ordered_groups, ordered_outcomes = inverse[order], outcomes[order]
            changes = np.ones(len(order), dtype=np.bool_)
            changes[1:] = (ordered_groups[1:] != ordered_groups[:-1]) | (ordered_outcomes[1:] != ordered_outcomes[:-1])
            distinct_counts = np.bincount(ordered_groups[changes], minlength=len(groups))
            scores = np.where((group_common != 0) | (group_any == 0), 0, distinct_counts-1)
            branches = [{"answers": {key: assignment(valid_indices[positions[i]])[key] for key in keys},
                         "scenario_count": int(counts[i]), "diversity": int(scores[i]),
                         "common_winners": decode(group_common[i]), "all_infeasible": not bool(group_any[i])}
                        for i in np.argsort(positions)[:model.max_display_scenarios]]
            representatives = set(representative_indices)
            for outcome_value, position in zip(distinct, first):
                index = int(valid_indices[position])
                different_answer = admitted & (outcome == outcome_value) & (question_codes != question_codes[index])
                alternatives = np.flatnonzero(different_answer)
                if len(alternatives):
                    representatives.add(int(alternatives[0]))
            question_witness = _witness([proof(i) for i in sorted(representatives)], keys)
            return {"id": "+".join(keys), "variable_ids": keys,
                    "text": " ".join(v.question or f"Proszę wyjaśnić: {v.label or v.id}." for v in items),
                    "score": int(np.max(scores)), "difficulty": sum(v.difficulty for v in items), "needed": bool(diversity),
                    "branches": branches, "branch_count": len(groups), "branches_truncated_for_display": len(groups) > model.max_display_scenarios,
                    "witness": question_witness, "unknown_answer_reduces_scenarios": False, "heuristic": True,
                    "kind": "pair" if len(keys) > 1 else "variable"}

        available = [v for v in model.variables if bool(np.any(codes[v.id][admitted] != codes[v.id][valid_indices[0]]))]
        questions = [question([v]) for v in available]
        if diversity > 0 and questions and min(q["score"] for q in questions) >= diversity:
            for pair in combinations(available, 2):
                candidate = question(pair)
                if candidate["score"] < diversity:
                    questions.append(candidate)
        questions.sort(key=lambda q: (q["score"], q["difficulty"], q["id"]))
        robust = sorted(o.id for i, o in enumerate(model.offers) if bool(np.all(feasible[i][admitted])))
        common_ids = decode(common)
        unique = common_ids[0] if len(common_ids) == 1 and bool(np.all(outcomes == common)) else None
        status = "no_feasible_offer" if not any_winner else "unique_winner" if unique else "common_winner" if common else "needs_clarification"
        summary = []
        for index, offer in enumerate(model.offers):
            price = prices[index]
            examples = {int(valid_indices[0])}
            if price is not None and model.budget_minor is not None:
                excess = np.flatnonzero(admitted & (price > model.budget_minor))
                if len(excess):
                    examples.add(int(excess[0]))
            failed = np.flatnonzero(admitted & condition_failures[index])
            if len(failed):
                examples.add(int(failed[0]))
            reasons = {}
            for example in sorted(examples):
                for reason in proof(example)["exclusions"][offer.id]:
                    reasons.setdefault(reason["code"], reason)
            summary.append({"id": offer.id, "name": offer.name or offer.id,
                "min_cost_minor": None if price is None else int(np.min(price[admitted])),
                "max_cost_minor": None if price is None else int(np.max(price[admitted])),
                "always_feasible": offer.id in robust, "sometimes_feasible": bool(np.any(feasible[index][admitted])),
                "possible_winner": bool(np.any(outcomes & np.uint64(1 << index))), "common_winner": offer.id in common_ids,
                "exclusions": list(reasons.values()), "evidence_ids": offer.evidence_ids, "scope_confirmed": offer.scope_confirmed})
        return {"schema_version": "1.0", "status": status, "complete": True, "scope": scope,
            "currency": model.currency, "minor_unit": model.minor_unit,
            "rounding": "ROUND_HALF_UP, each cost item after explicit tax and currency conversion",
            "scenario_count": len(valid_indices), "checked_count": count,
            "scenarios": [proof(i) for i in valid_indices[:model.max_display_scenarios]],
            "scenarios_truncated_for_display": len(valid_indices) > model.max_display_scenarios,
            "method": "exact_enumeration", "acceleration": "bounded_integer_arrays", "regions": [], "offers": summary,
            "robust_feasible": robust, "common_winners": common_ids, "unique_winner": unique,
            "provisional_common_winners": [], "diversity": diversity, "questions": questions,
            "witnesses": [witness] if witness else [], "thresholds": [], "issues": [],
            "duration_ms": round((perf_counter()-started)*1000, 3)}
    except (NotApplicable, OverflowError, TypeError, ArithmeticError):
        return None
