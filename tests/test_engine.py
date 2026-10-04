from copy import deepcopy
from decimal import Decimal
from itertools import product

import pytest
from hypothesis import given, settings, strategies as st
from pydantic import ValidationError

from packages.domain import (
    ComparisonModel, Expression, demo_model, evaluate, evaluate_expression,
    money_to_minor, parse_moment, rank_questions,
)
from packages.domain.engine import ModelError, decision_diversity


def literal(value):
    return {"op": "literal", "value": value}


def var(name):
    return {"op": "var", "name": name}


def binary(op, left, right):
    return {"op": op, "left": left, "right": right}


def offer(identifier, expression, **kwargs):
    return {"id": identifier, "currency": "PLN", "tax_basis": "gross",
            "cost_items": [{"id": "price", "amount": expression}], **kwargs}


def variable(identifier, values):
    return {"id": identifier, "values": values, "complete": True, "source": "test fixture"}


def model(offers, variables=None, **kwargs):
    return {"offers": offers, "variables": variables or [], **kwargs}


@pytest.mark.parametrize("amount,winners,feasible_a", [
    (0, ["A"], True), (69900, ["A"], True), (69999, ["A"], True),
    (70000, ["A", "B"], True), (70001, ["B"], True), (70100, ["B"], True),
    (79999, ["B"], True), (80000, ["B"], True), (80001, ["B"], False),
    (80100, ["B"], False), (120000, ["B"], False),
])
def test_exact_demo_thresholds(amount, winners, feasible_a):
    result = evaluate(demo_model(amount))
    assert result["complete"], result["issues"]
    assert result["scenarios"][0]["winners"] == winners
    assert ("A" in result["scenarios"][0]["feasible"]) == feasible_a
    assert result["scenarios"][0]["costs"]["A"] == 480000 + amount
    assert "C" not in result["scenarios"][0]["feasible"]


def test_demo_uncertainty_and_real_witness():
    result = evaluate(demo_model())
    assert result["status"] == "needs_clarification"
    assert result["robust_feasible"] == ["B"]
    question = result["questions"][0]
    assert question["score"] == 0
    assert question["needed"]
    assert not question["unknown_answer_reduces_scenarios"]
    assert question["witness"]["kind"] == "winner_change"
    assert question["witness"]["changed_variables"] == ["technician_surcharge"]
    for scenario in question["witness"]["scenarios"]:
        replay = evaluate(demo_model(scenario["assignment"]["technician_surcharge"]))
        assert replay["scenarios"][0]["winners"] == scenario["winners"]


def test_interval_question_has_real_witness_without_finite_ranking_score():
    result = evaluate(demo_model(continuous=True))
    question = result["questions"][0]
    assert question["kind"] == "interval" and question["score"] is None
    assert question["needed"] and question["witness"]["kind"] == "winner_change"
    assert any(t["value"] == 70000 for t in question["thresholds"])


@pytest.mark.parametrize("value,expected", [("699.99", 69999), ("700,01", 70001),
    ("0.005", 1), ("1.005", 101), ("-1.005", -101), ("1e2", 10000)])
def test_decimal_money(value, expected):
    assert money_to_minor(value) == expected


def test_minor_unit_tax_currency_and_deposit_are_explicit():
    a = offer("A", literal(10000), currency="EUR", tax_basis="net", tax_rate="0.23", tax_source="invoice",
              exchange_rate={"rate": "4.3333", "as_of": "2026-10-03", "source": "declared rate", "from_currency": "EUR", "to_currency": "PLN"})
    a["cost_items"].extend([
        {"id": "deposit", "amount": literal(100000), "category": "deposit", "refundable": True},
        {"id": "first-payment", "amount": literal(5000), "category": "payment", "due_at": "2026-10-09"},
        {"id": "cancellation", "amount": literal(2500), "category": "cancellation"},
    ])
    result = evaluate(model([a, offer("B", literal(60000))]))
    assert result["complete"], result["issues"]
    assert result["scenarios"][0]["costs"]["A"] == 53300
    assert result["scenarios"][0]["ancillary"]["A"]["deposit"] == 433330
    assert result["unique_winner"] == "A"
    a["tax_source"] = None
    missing = evaluate(model([a]))
    assert missing["status"] == "incomplete"
    assert not missing["unique_winner"]


def test_unknown_currency_and_tax_never_inferred():
    for field, value in (("currency", None), ("tax_basis", "unknown"), ("currency", "EUR")):
        a = offer("A", literal(10000))
        a[field] = value
        result = evaluate(model([a]))
        assert not result["complete"]
        assert result["scenarios"][0]["costs"]["A"] is None


def test_shared_variables_preserve_correlation():
    plus = lambda base: {"op": "sum", "args": [literal(base), var("X")]}
    result = evaluate(model([offer("A", plus(100)), offer("B", plus(101))], [variable("X", [0, 10, 10000])]))
    assert result["unique_winner"] == "A"
    assert result["witnesses"] == []
    assert all(not q["needed"] for q in result["questions"])


def test_package_excludes_double_count_and_constraints_reject_invalid_scenarios():
    a = offer("A", literal(100))
    a["cost_items"] += [{"id": "extra", "amount": literal(50), "when": {"op": "not", "arg": var("package")}}]
    m = model([a], [variable("package", [True, False]), variable("extra", [True, False])],
              constraints=[binary("ne", var("package"), var("extra"))])
    result = evaluate(m)
    assert result["complete"] and result["scenario_count"] == 2
    for s in result["scenarios"]:
        assert s["assignment"]["package"] != s["assignment"]["extra"]
        assert s["costs"]["A"] == (100 if s["assignment"]["package"] else 150)


def test_empty_s_is_inconsistent_empty_f_is_diagnosis_mixed_is_unresolved():
    result = evaluate(model([offer("A", literal(100))], [variable("x", [0])], constraints=[binary("eq", var("x"), literal(1))]))
    assert result["status"] == "inconsistent"
    assert result["complete"] and result["scenario_count"] == 0
    none = evaluate(model([offer("A", literal(100))], budget_minor=99))
    assert none["status"] == "no_feasible_offer"
    mixed = evaluate(model([offer("A", var("x"))], [variable("x", [100, 200])], budget_minor=150))
    assert mixed["status"] == "needs_clarification"
    assert mixed["witnesses"][0]["kind"] == "feasibility_change"
    assert mixed["questions"][0]["score"] == 0


def test_tie_to_single_retains_common_winner_and_is_not_reversal():
    m = model([offer("A", literal(100)), offer("B", var("x"))], [variable("x", [100, 101])])
    result = evaluate(m)
    assert result["status"] == "common_winner"
    assert result["common_winners"] == ["A"]
    assert result["unique_winner"] is None
    assert result["witnesses"][0]["kind"] == "tie_change"
    assert result["diversity"] == 0
    assert not result["questions"][0]["needed"]


def test_pairwise_intersecting_triple_shows_three_scenarios():
    offers = [offer(name, {"op": "if", "condition": binary("eq", var("absent"), literal(name)),
                           "then": literal(200), "otherwise": literal(100)}) for name in "ABC"]
    result = evaluate(model(offers, [variable("absent", ["A", "B", "C"])]))
    assert result["status"] == "needs_clarification"
    witness = result["witnesses"][0]
    assert witness["kind"] == "no_common_winner"
    assert len(witness["scenarios"]) == 3
    assert set.intersection(*(set(s["winners"]) for s in witness["scenarios"])) == set()
    assert all(set(a["winners"]) & set(b["winners"]) for a, b in __import__("itertools").combinations(witness["scenarios"], 2))


def test_question_ranking_common_cowinner_beats_counting_outcomes():
    outcomes = [["A"], ["A", "B"], ["A", "C"], ["D"], ["D", "E"], ["D", "F"]]
    scenarios = [{"id": str(i), "winners": outcome, "assignment": {"group": i // 3, "pair": i % 3}}
                 for i, outcome in enumerate(outcomes)]
    ranked = rank_questions(scenarios, [variable("group", [0, 1]), variable("pair", [0, 1, 2])])
    assert ranked[0]["id"] == "group" and ranked[0]["score"] == 0
    assert ranked[1]["score"] == 1
    assert decision_diversity(scenarios[:3]) == 0


def test_xor_requires_pair_of_questions():
    xor = binary("ne", var("x"), var("y"))
    result = evaluate(model([offer("A", {"op": "if", "condition": xor, "then": literal(100), "otherwise": literal(300)}),
                             offer("B", literal(200))],
                            [variable("x", [False, True]), variable("y", [False, True])]))
    ranked = result["questions"]
    assert ranked[0]["kind"] == "pair" and ranked[0]["score"] == 0
    assert all(q["score"] == 1 for q in ranked[1:])
    for q in ranked:
        witness = q["witness"]
        assert any(k in witness["changed_variables"] for k in q["variable_ids"])


def test_witness_discloses_other_changes_when_constraints_correlate_answers():
    m = model([offer("A", var("x")), offer("B", literal(5))],
              [variable("x", [0, 10]), variable("y", [0, 10])],
              constraints=[binary("eq", var("x"), var("y"))])
    result = evaluate(m)
    for q in result["questions"]:
        assert q["witness"]["other_changed_variables"]
        for s in q["witness"]["scenarios"]:
            assert s["assignment"]["x"] == s["assignment"]["y"]


@pytest.mark.parametrize("kind", ["cap", "open", "source", "unknown_operator", "nonlinear", "dimensions"])
def test_incomplete_results_cannot_claim_full_winner(kind):
    m = model([offer("A", literal(0))], [variable("x", [0, 1])])
    if kind == "cap":
        m["max_scenarios"] = 1
    elif kind == "open":
        m["variables"][0].update(kind="open", complete=False)
    elif kind == "source":
        m["variables"][0]["source"] = None
    elif kind == "unknown_operator":
        m["offers"][0]["cost_items"][0]["amount"] = {"op": "exec", "value": "print('unsafe')"}
    else:
        m["variables"][0].update(kind="interval", lower=0, upper=10)
        if kind == "nonlinear":
            m["offers"][0]["cost_items"][0]["amount"] = {"op": "mul", "args": [var("x"), var("x")]}
        else:
            m["variables"].append({**variable("y", []), "kind": "interval", "lower": 0, "upper": 1})
    result = evaluate(m)
    assert result["status"] == "incomplete"
    assert not result["complete"] and result["unique_winner"] is None
    assert not result["robust_feasible"] and not result["common_winners"]


def test_invalid_operator_shape_and_bool_money_are_rejected():
    with pytest.raises(ValidationError):
        Expression.model_validate({"op": "literal", "value": 1, "args": []})
    with pytest.raises(ModelError):
        evaluate_expression({"op": "sum", "args": [literal(True), literal(10)]}, {})
    assert evaluate_expression(binary("eq", literal(True), literal(1)), {}) is False


def test_new_answer_outside_initial_domain_requires_new_model_version():
    original = demo_model()
    changed = demo_model(70100)
    assert original["variables"][0]["values"] == [0, 120000]
    assert evaluate(changed)["unique_winner"] == "B"


def test_overnight_and_dst_times():
    m = model([offer("A", literal(100), ready_at="2026-10-10T22:30:00+02:00",
                     service_start="2026-10-10T23:00:00+02:00", service_end="2026-10-11T02:00:00+02:00")],
              requirements={"ready_by": "2026-10-10T23:00:00+02:00", "service_start": "2026-10-10T23:00:00+02:00",
                            "service_end": "2026-10-11T02:00:00+02:00"})
    assert evaluate(m)["unique_winner"] == "A"
    assert parse_moment("2026-10-25T02:30:00+02:00") != parse_moment("2026-10-25T02:30:00+01:00")
    for timestamp in ("2026-10-25T02:30:00", "2026-03-29T02:30:00", "tomorrow", "09:00"):
        with pytest.raises(ModelError):
            parse_moment(timestamp)


def test_missing_technician_interval_and_scope_are_unknown_not_satisfied():
    m = demo_model()
    m["offers"][0]["service_end"] = None
    m["offers"][1]["scope_confirmed"] = None
    result = evaluate(m)
    assert not result["complete"]
    assert {i["code"] for i in result["issues"]} >= {"missing_time", "missing_scope"}


def test_one_interval_analytically_finds_grosz_thresholds():
    result = evaluate(demo_model(continuous=True))
    assert result["complete"], result["issues"]
    assert result["method"] == "analytic_partition"
    assert result["scenario_count"] < 30
    assert {("tie", 70000), ("budget", 80000)} <= {(t["kind"], t["value"]) for t in result["thresholds"]}
    assignments = [s["assignment"]["technician_surcharge"] for s in result["scenarios"]]
    for value in (69999, 70000, 70001, 79999, 80000, 80001):
        assert value in assignments
    assert result["robust_feasible"] == ["B"]


def test_true_continuous_rounding_tie_band_is_not_lost():
    m = model([offer("A", var("x")), offer("B", literal(1))],
              [{**variable("x", []), "kind": "interval", "lower": 0, "upper": 2}])
    result = evaluate(m)
    assert result["complete"]
    assert {tuple(s["winners"]) for s in result["scenarios"]} == {("A",), ("A", "B"), ("B",)}
    assert any(s["assignment"]["x"] == "0.5" and s["winners"] == ["A", "B"] for s in result["scenarios"])


def test_interval_constraints_and_fractional_tax_are_partitioned_correctly():
    m = model([offer("A", var("x"), tax_basis="net", tax_rate="0.23", tax_source="fixture"), offer("B", literal(6))],
              [{**variable("x", []), "kind": "interval", "lower": 0, "upper": 10, "step": 1}],
              constraints=[binary("gte", var("x"), literal(4))], budget_minor=10)
    analytic = evaluate(m)
    enumerated = deepcopy(m)
    enumerated["variables"] = [variable("x", list(range(11)))]
    reference = evaluate(enumerated)
    assert analytic["complete"], analytic["issues"]
    assert {tuple(s["winners"]) for s in analytic["scenarios"]} == {tuple(s["winners"]) for s in reference["scenarios"]}
    assert all(s["assignment"]["x"] >= 4 for s in analytic["scenarios"])


def test_nonterminating_analytic_root_is_exact_and_replayable():
    m = model([offer("A", literal(100))],
              [{**variable("x", []), "kind": "interval", "lower": 0, "upper": 1}],
              constraints=[binary("eq", {"op": "mul", "args": [literal(3), var("x")]}, literal(1))])
    result = evaluate(m)
    assert result["complete"], result["issues"]
    assert result["unique_winner"] == "A"
    assert result["scenario_count"] == 1
    assert result["scenarios"][0]["assignment"]["x"] == "1/3"
    replay = deepcopy(m)
    replay["variables"] = [variable("x", ["1/3"])]
    assert evaluate(replay)["unique_winner"] == "A"


@given(st.integers(1, 19), st.integers(1, 19), st.integers(1, 19))
@settings(max_examples=40, deadline=None)
def test_rational_equality_boundaries_do_not_disappear(a, b, price):
    m = model([offer("A", literal(price))],
              [{**variable("x", []), "kind": "interval", "lower": 0, "upper": 20}],
              constraints=[binary("eq", {"op": "mul", "args": [literal(a), var("x")]}, literal(b))])
    result = evaluate(m)
    assert result["complete"] and result["unique_winner"] == "A"
    assert result["scenario_count"] == 1


@given(st.lists(st.integers(min_value=0, max_value=100000), min_size=1, max_size=6),
       st.lists(st.integers(min_value=0, max_value=1000), min_size=1, max_size=6),
       st.integers(min_value=0, max_value=200000))
@settings(max_examples=60, deadline=None)
def test_generated_enumeration_matches_independent_reference(base_prices, quantities, budget):
    offers = [offer(str(i), {"op": "sum", "args": [literal(price), {"op": "mul", "args": [literal(i + 1), var("quantity")]}]})
              for i, price in enumerate(base_prices)]
    result = evaluate(model(offers, [variable("quantity", quantities)], budget_minor=budget))
    assert result["complete"], result["issues"]
    for scenario in result["scenarios"]:
        q = scenario["assignment"]["quantity"]
        costs = {str(i): price + (i + 1) * q for i, price in enumerate(base_prices)}
        feasible = {k: value for k, value in costs.items() if value <= budget}
        minimum = min(feasible.values(), default=None)
        winners = sorted(k for k, value in feasible.items() if value == minimum)
        assert scenario["costs"] == costs
        assert scenario["winners"] == winners
    reversed_model = model(list(reversed(offers)), [variable("quantity", quantities + quantities)], budget_minor=budget)
    other = evaluate(reversed_model)
    assert result["common_winners"] == other["common_winners"]
    assert result["scenario_count"] == other["scenario_count"]


def test_numeric_formats_and_duplicate_scenarios_do_not_change_result():
    m = model([offer("A", var("x")), offer("B", literal(100))], [variable("x", [100, "100.0", "1e2", 100.0])])
    result = evaluate(m)
    assert result["scenario_count"] == 1
    assert result["common_winners"] == ["A", "B"]


def test_explicit_exclusion_records_scope_without_blocking_other_offers():
    result = evaluate(model([offer("A", literal(100)), {"id": "B", "excluded_reason": "Oferta poza zakresem na życzenie właściciela"}]))
    assert result["complete"] and result["unique_winner"] == "A"
    assert result["offers"][1]["exclusions"][0]["code"] == "excluded_by_user"


def test_exclusion_removes_private_open_domains_and_gaps_but_keeps_shared_constraints():
    m = model([offer("A", literal(100)), offer("B", var("B:price"), excluded_reason="Brak kompletnego źródła B")],
              [{"id": "B:price", "kind": "open", "values": [], "complete": False}],
              issues=[{"code": "missing_source", "message": "Nieodczytana strona B", "offer_id": "B"}])
    result = evaluate(m)
    assert result["complete"] and result["unique_winner"] == "A"
    assert result["scope"] == {"limited": True, "excluded_offer_ids": ["B"], "excluded_variable_ids": ["B:price"]}
    assert m["variables"][0]["kind"] == "open"  # Evaluation never mutates the saved model.
    m["offers"][0]["cost_items"][0]["amount"] = var("B:price")
    shared = evaluate(m)
    assert not shared["complete"]
    assert shared["scope"]["excluded_variable_ids"] == []
    assert any(i["code"] == "open_domain" for i in shared["issues"])
