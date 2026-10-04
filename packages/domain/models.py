"""Closed, versioned input contract. Expressions are data, never executable code."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Expression(StrictModel):
    op: Literal["literal", "var", "sum", "mul", "if", "eq", "ne", "lt", "lte", "gt", "gte", "and", "or", "not", "date"]
    value: str | int | float | bool | None = None
    name: str | None = None
    args: list[Expression] | None = None
    left: Expression | None = None
    right: Expression | None = None
    condition: Expression | None = None
    then: Expression | None = None
    otherwise: Expression | None = None
    arg: Expression | None = None
    timezone: str | None = None

    @model_validator(mode="after")
    def closed_operator(self):
        fields = self.model_fields_set - {"op"}
        required = {
            "literal": {"value"}, "var": {"name"}, "sum": {"args"}, "mul": {"args"},
            "if": {"condition", "then", "otherwise"}, "and": {"args"}, "or": {"args"},
            "not": {"arg"}, "date": {"value"},
        }.get(self.op, {"left", "right"})
        allowed = required | ({"timezone"} if self.op == "date" else set())
        if not required <= fields or fields - allowed:
            raise ValueError(f"Invalid fields for operator {self.op}: expected {sorted(required)}")
        if self.op != "literal" and any(getattr(self, key) is None for key in required):
            raise ValueError(f"Null argument for {self.op}")
        if self.args is not None and (not self.args or (self.op == "mul" and len(self.args) != 2)):
            raise ValueError("sum/and/or need operands; mul takes exactly two operands")
        if self.op == "var" and not self.name:
            raise ValueError("Empty variable name")
        return self


class Variable(StrictModel):
    id: str
    label: str = ""
    kind: Literal["enum", "interval", "open"] = "enum"
    values: list[str | int | float | bool | None] = Field(default_factory=list)
    lower: Decimal | None = None
    upper: Decimal | None = None
    step: Decimal | None = None
    complete: bool = False
    unit: str | None = None
    source: str | None = None
    assumption: str | None = None
    question: str | None = None
    difficulty: int = Field(default=0, ge=0)
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_domain(self):
        if self.kind == "interval" and (self.lower is None or self.upper is None or self.lower > self.upper):
            raise ValueError("Interval requires ordered finite bounds")
        if self.step is not None and self.step <= 0:
            raise ValueError("Interval step must be positive")
        if self.kind == "open" and self.complete:
            raise ValueError("An open domain cannot be complete")
        return self


class CostItem(StrictModel):
    id: str
    label: str = ""
    amount: Expression
    category: Literal["service", "deposit", "cancellation", "payment"] = "service"
    when: Expression | None = None
    unit: str = "service"
    evidence_ids: list[str] = Field(default_factory=list)
    due_at: str | None = None
    refundable: bool | None = None


class ExchangeRate(StrictModel):
    rate: Decimal = Field(gt=0)
    as_of: str
    source: str = Field(min_length=1)
    from_currency: str
    to_currency: str


class Offer(StrictModel):
    id: str
    name: str = ""
    currency: str | None = None
    minor_unit: int = Field(default=2, ge=0, le=4)
    tax_basis: Literal["gross", "net", "unknown"] = "unknown"
    tax_rate: Decimal | None = Field(default=None, ge=0, le=1)
    tax_source: str | None = None
    exchange_rate: ExchangeRate | None = None
    cost_items: list[CostItem] = Field(default_factory=list)
    participants: int | None = Field(default=None, ge=0)
    microphones: int | None = Field(default=None, ge=0)
    ready_at: str | None = None
    service_start: str | None = None
    service_end: str | None = None
    scope_confirmed: bool | None = None
    constraints: list[Expression] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    excluded_reason: str | None = None


class Requirements(StrictModel):
    participants: int | None = Field(default=None, ge=0)
    microphones: int | None = Field(default=None, ge=0)
    ready_by: str | None = None
    service_start: str | None = None
    service_end: str | None = None
    scope_required: bool = False
    description: str = ""
    confirmed: bool = False


class ComparisonModel(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    currency: str = "PLN"
    minor_unit: int = Field(default=2, ge=0, le=4)
    budget_minor: int | None = Field(default=None, ge=0)
    timezone: str = "Europe/Warsaw"
    requirements: Requirements = Field(default_factory=Requirements)
    variables: list[Variable] = Field(default_factory=list, max_length=50)
    offers: list[Offer] = Field(default_factory=list, max_length=100)
    constraints: list[Expression] = Field(default_factory=list)
    issues: list[dict[str, Any]] = Field(default_factory=list)
    max_scenarios: int = Field(default=100000, ge=1, le=1000000)
    max_display_scenarios: int = Field(default=200, ge=1, le=1000000)

    @model_validator(mode="after")
    def unique_ids(self):
        for values in (self.offers, self.variables):
            ids = [v.id for v in values]
            if len(ids) != len(set(ids)):
                raise ValueError("IDs must be unique")
        for offer in self.offers:
            ids = [item.id for item in offer.cost_items]
            if len(ids) != len(set(ids)):
                raise ValueError("Cost item IDs must be unique within an offer")
        return self
