from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class Write(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expectedRevision: int = Field(ge=0)


class CreateCase(Write):
    title: str = Field(min_length=1, max_length=160)
    requirements: dict = Field(default_factory=dict)


class UpdateCase(Write):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    requirements: dict | None = None


class CreateOffer(Write):
    name: str = Field(min_length=1, max_length=160)


class UpdateFact(Write):
    value: Any = None
    unit: Literal["minor", "major"] | None = None
    reason: str = Field(min_length=1, max_length=4000)
    confirmation: Literal["confirmed", "proposed"] = "confirmed"


class ApprovalInput(Write):
    factIds: list[str] = Field(default_factory=list)
    requirementsConfirmed: bool = False


class AnalysisInput(Write):
    consent: bool


class Recalculate(Write):
    assignments: dict | None = None


class QuestionInput(Write):
    status: Literal["prepared", "waiting", "answer_added", "resolved"] | None = None
    assignee: str | None = None
    dueAt: str | None = None
    difficulty: int | None = Field(default=None, ge=0, le=10)


class AnswerInput(Write):
    text: str = Field(min_length=1, max_length=20000)
    kind: Literal["unknown", "value"]
    value: Any = None
    confirmed: bool = False


class DecisionInput(Write):
    offerId: str
    kind: Literal["final", "conditional"]
    reason: str = Field(min_length=1, max_length=10000)
    assumptions: str | None = None
    nextStep: str | None = None
    owner: str | None = None
    confirmCost: bool
    confirmScope: bool
    confirmDeadline: bool


class UndoInput(Write):
    targetRevision: int = Field(ge=1)


class InvitationInput(Write):
    role: Literal["editor", "observer"]


class DeleteInput(Write):
    reason: str = "Usunięcie przez użytkownika"


class RequirementsProposal(Write):
    text: str = Field(min_length=1, max_length=10000)
    consent: bool


class ExcludeInput(Write):
    excluded: bool
    reason: str = Field(min_length=1, max_length=4000)


class ModelInput(Write):
    model: dict
    reason: str = Field(min_length=1, max_length=4000)


class CaseDetail(BaseModel):
    id: str
    title: str
    revision: int
    role: str
    status: str
    updatedAt: str
    requirements: dict
    model: dict
    offers: list[dict]
    documents: list[dict]
    facts: list[dict]
    questions: list[dict]
    analysis: dict | None
    decisions: list[dict]
    history: list[dict]
    members: list[dict]
    jobs: list[dict]
    approval: dict | None
    impact: list[dict]
    pendingAnalysis: bool
    usage: dict
    retention: dict = Field(default_factory=dict)
    recordedDemo: bool = False
