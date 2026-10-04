"""Strict provider output contracts. Values remain proposals until reviewed."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "offer-extraction-v5"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Citation(StrictModel):
    source_id: str
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)


class FactCandidate(StrictModel):
    id: str
    key: str = Field(description="Stable semantic field: currency, tax_basis, tax_rate, participants, microphones, ready_at, service_start, service_end, scope_confirmed, price, deposit, cancellation, payment, document_date, declared_author, or other explicit condition")
    value: str | int | bool | None
    unit: str | None = None
    scope: str = ""
    condition: str | None = None
    condition_unresolved: bool = False
    critical: bool = True
    evidence: list[Citation] = Field(min_length=1)


class CostCandidate(StrictModel):
    id: str
    label: str
    amount_minor: int | None = Field(default=None, description="Integer minor currency units. Null if no numeric amount is stated; zero only for an explicitly included free component.")
    variable_id: str | None = None
    quantity: str = "1"
    unit: str = "service"
    category: Literal["service", "deposit", "cancellation", "payment"] = "service"
    role: Literal["additive", "total_check", "included", "optional"] = Field(default="additive", description="A total stated alongside its breakdown is total_check, never additive. Included breakdown within an additive package is included. An out-of-scope optional service is optional.")
    condition: str | None = None
    condition_unresolved: bool = False
    fact_ids: list[str] = Field(min_length=1)


class VariableCandidate(StrictModel):
    id: str
    label: str
    kind: Literal["enum", "interval", "unknown"] = "unknown"
    values: list[int | str | bool] = Field(default_factory=list, description="Possible values. For a variable used by a cost, integer monetary values are in minor units, e.g. PLN 1200 = 120000.")
    minimum: int | None = None
    maximum: int | None = None
    complete: bool = Field(default=False, description="True only if values exhaust the documented interpretations within the stated scope. This is a proposed domain, not human approval or a limit on future supplier answers.")
    unit: str = "minor"
    question: str
    fact_ids: list[str] = Field(default_factory=list, description="Evidence facts supporting the listed possible values or bounds. Required and nonempty for any finite values or bounds; may be empty only for an entirely unknown domain.")
    explanation: str


class OfferExtraction(StrictModel):
    offer_name: str
    declared_author: str | None = None
    document_date: str | None = None
    facts: list[FactCandidate]
    costs: list[CostCandidate]
    variables: list[VariableCandidate] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    unsupported_conditions: list[str] = Field(default_factory=list)
    pages_reviewed: list[str] = Field(description="Every source_id:page actually analyzed. No silent page omission.")
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_exist(self):
        fact_ids = [fact.id for fact in self.facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("Duplicate fact IDs")
        variables = [variable.id for variable in self.variables]
        if len(variables) != len(set(variables)):
            raise ValueError("Duplicate variable IDs")
        for cost in self.costs:
            if not set(cost.fact_ids).issubset(fact_ids):
                raise ValueError("Cost references missing evidence fact")
            if cost.variable_id and cost.variable_id not in variables:
                raise ValueError("Cost references missing variable")
        for variable in self.variables:
            if not set(variable.fact_ids).issubset(fact_ids):
                raise ValueError("Variable references missing evidence fact")
            if (variable.values or variable.minimum is not None or variable.maximum is not None) and not variable.fact_ids:
                raise ValueError("A variable with finite values or bounds requires nonempty fact_ids supporting its domain")
            if variable.complete and (variable.kind == "unknown" or (variable.kind == "enum" and not variable.values)):
                raise ValueError("An unknown or empty domain cannot be complete")
        return self


class RequirementsProposal(StrictModel):
    participants: int | None = None
    microphones: int | None = None
    event_date: str | None = None
    service_start: str | None = None
    service_end: str | None = None
    ready_by: str | None = None
    budget_minor: int | None = None
    currency: str | None = None
    timezone: str | None = None
    scope: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class QuestionWording(StrictModel):
    question: str
    explanation: str
