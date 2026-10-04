import copy

import pytest
from hypothesis import given, settings, strategies as st

from packages.domain import demo_model, evaluate


def literal(value):
    return {"op": "literal", "value": value}


def var(name):
    return {"op": "var", "name": name}


def variable(name, values):
    return {"id": name, "values": values, "kind": "enum", "complete": True, "source": "Authored regression input"}


def offer(name, amount, **extra):
    return {"id": name, "currency": "PLN", "tax_basis": "gross", "cost_items": [{"id": "price", "amount": amount}], **extra}


def assert_matches_reference(model, expect_acceleration=True):
    accelerated = evaluate(model)
    reference = evaluate(model, accelerated=False)
    if expect_acceleration:
        assert accelerated.get("acceleration") == "bounded_integer_arrays"
    else:
        assert "acceleration" not in accelerated
    for field in ("status", "complete", "scope", "scenario_count", "checked_count", "robust_feasible", "common_winners", "unique_winner", "diversity", "scenarios", "offers", "issues"):
        assert accelerated[field] == reference[field], field
    assert [(q["id"], q["score"], q["needed"]) for q in accelerated["questions"]] == [(q["id"], q["score"], q["needed"]) for q in reference["questions"]]
    for actual, expected in zip(accelerated["questions"], reference["questions"]):
        assert actual["branches"] == expected["branches"][:len(actual["branches"])]
        if actual.get("branches_truncated_for_display"):
            assert actual["branch_count"] == len(expected["branches"])
    witnesses = accelerated["witnesses"] + [q["witness"] for q in accelerated["questions"] if q.get("witness")]
    for witness in witnesses:
        for scenario in witness["scenarios"]:
            fixed = copy.deepcopy(model)
            for unknown in fixed["variables"]:
                unknown["values"] = [scenario["assignment"][unknown["id"]]]
            checked = evaluate(fixed, accelerated=False)["scenarios"][0]
            assert (checked["winners"], checked["feasible"], checked["costs"]) == (scenario["winners"], scenario["feasible"], scenario["costs"])
    return accelerated


def test_vectorized_av_all_values_are_enumerated_and_branch_display_is_explicit():
    model = demo_model()
    model["variables"][0]["values"] = list(range(0, 120001, 100))
    result = assert_matches_reference(model)
    assert result["checked_count"] == 1201
    assert result["questions"][0]["branch_count"] == 1201
    assert result["questions"][0]["branches_truncated_for_display"]


def test_vectorized_xor_ranks_joint_answers_and_respects_global_constraints():
    equality = {"op": "eq", "left": var("x"), "right": var("y")}
    model = {"offers": [offer("A", {"op": "if", "condition": equality, "then": literal(100), "otherwise": literal(300)}),
                        offer("B", {"op": "if", "condition": equality, "then": literal(300), "otherwise": literal(100)})],
             "variables": [variable("x", [False, True]), variable("y", [False, True]), variable("unused", list(range(256)))]}
    result = assert_matches_reference(model)
    assert result["questions"][0]["id"] == "x+y" and result["questions"][0]["score"] == 0
    model["constraints"] = [{"op": "or", "args": [var("x"), var("y")]}]
    assert_matches_reference(model)


def test_vectorized_tax_rounding_deposits_packages_and_offer_conditions():
    model = {"offers": [offer("A", {"op": "sum", "args": [literal(100), var("x")]}, tax_basis="net", tax_rate="0.23", tax_source="human-rate"),
                        offer("B", literal(800))], "variables": [variable("x", list(range(1100)))], "budget_minor": 1300}
    model["offers"][0]["cost_items"].extend([
        {"id": "deposit", "category": "deposit", "amount": literal(500)},
        {"id": "included", "amount": literal(20), "when": {"op": "lt", "left": var("x"), "right": literal(600)}}])
    model["offers"][0]["constraints"] = [{"op": "lte", "left": var("x"), "right": literal(950)}]
    assert_matches_reference(model)


@pytest.mark.parametrize("amount", [literal(2**61), {"op": "mul", "args": [var("x"), literal("0.5")]},
                                   {"op": "mul", "args": [var("x"), literal(2**59)]}])
def test_unsafe_or_nonintegral_forms_fall_back_without_overflow(amount):
    model = {"offers": [offer("A", amount), offer("B", literal(100))], "variables": [variable("x", list(range(1100)))]}
    assert_matches_reference(model, expect_acceleration=False)


@settings(max_examples=20, deadline=None)
@given(a=st.integers(0, 20), b=st.integers(0, 20), base_a=st.integers(0, 1000), base_b=st.integers(0, 1000))
def test_generated_shared_integer_costs_match_decimal_reference(a, b, base_a, base_b):
    def cost(slope, base):
        return {"op": "sum", "args": [literal(base), {"op": "mul", "args": [var("x"), literal(slope)]}]}
    model = {"offers": [offer("A", cost(a, base_a)), offer("B", cost(b, base_b))],
             "variables": [variable("x", list(range(1024)))], "budget_minor": 10000}
    assert_matches_reference(model)
