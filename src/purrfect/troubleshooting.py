"""Pure, product-grounded troubleshooting transitions (Goal 1.8, Slice 2).

No WordPress bridge, model generation, execution, or ticket persistence here.
Each transition re-resolves active product-owned procedures and evidence.
"""
from dataclasses import dataclass, replace
from typing import Literal

from purrfect.knowledge import SiteKnowledge, TroubleshootingProcedure

Result = Literal["worked", "failed"]
Status = Literal["awaiting_result", "resolved", "escalation_required"]


@dataclass(frozen=True, slots=True)
class Attempt:
    step_id: str
    result: Result
    evidence_id: str


@dataclass(frozen=True, slots=True)
class TroubleshootingState:
    product_id: str
    product_version: str
    procedure_id: str
    step_id: str
    attempts: tuple[Attempt, ...] = ()
    status: Status = "awaiting_result"

    def export(self) -> dict:
        return {
            "product_id": self.product_id,
            "product_version": self.product_version,
            "procedure_id": self.procedure_id,
            "step_id": self.step_id,
            "attempts": [
                {"step_id": a.step_id, "result": a.result, "evidence_id": a.evidence_id}
                for a in self.attempts
            ],
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class TroubleshootingReply:
    status: Status
    message: str
    step_id: str | None
    source: str | None


def _procedure(knowledge: SiteKnowledge, state: TroubleshootingState):
    product = knowledge.products.get(state.product_id)
    if product is None or product.version != state.product_version:
        raise ValueError("Product is inactive or its version has changed")
    procedure = next(
        (p for p in product.troubleshooting if p.id == state.procedure_id), None
    )
    if procedure is None:
        raise ValueError("Troubleshooting procedure is no longer registered")
    evidence = {e.id: e for e in product.evidence}
    return procedure, evidence


def _validate(knowledge: SiteKnowledge, state: TroubleshootingState):
    procedure, evidence = _procedure(knowledge, state)
    steps = procedure.steps
    ids = [s.id for s in steps]
    if state.status not in ("awaiting_result", "resolved", "escalation_required"):
        raise ValueError("Invalid troubleshooting status")
    if len(state.attempts) > len(steps):
        raise ValueError("Excess troubleshooting attempts")
    if [a.step_id for a in state.attempts] != ids[:len(state.attempts)]:
        raise ValueError("Invalid attempt order")
    for index, attempt in enumerate(state.attempts):
        if attempt.result not in ("worked", "failed"):
            raise ValueError("Invalid attempt result")
        if attempt.evidence_id != steps[index].evidence_id:
            raise ValueError("Attempt evidence does not match active knowledge")
        if index < len(state.attempts) - 1 and attempt.result != "failed":
            raise ValueError("Cannot continue after successful attempt")
    if state.status == "awaiting_result":
        if len(state.attempts) >= len(steps) or any(a.result == "worked" for a in state.attempts):
            raise ValueError("Cannot await an already completed procedure")
        expected = steps[len(state.attempts)].id
    else:
        if not state.attempts or state.status == "resolved" and state.attempts[-1].result != "worked":
            raise ValueError("Invalid resolved state")
        if state.status == "escalation_required" and (
            len(state.attempts) != len(steps) or any(a.result != "failed" for a in state.attempts)
        ):
            raise ValueError("Escalation requires all documented steps to fail")
        if state.status == "resolved" and any(a.result == "worked" for a in state.attempts[:-1]):
            raise ValueError("Resolved before last attempt")
        expected = state.attempts[-1].step_id
    if state.step_id != expected:
        raise ValueError("Saved step does not match procedure progress")
    return procedure, evidence


def start(knowledge: SiteKnowledge, product_id: str, procedure_id: str):
    product = knowledge.products.get(product_id)
    if product is None:
        raise ValueError("Product must be registered and active")
    procedure = next((p for p in product.troubleshooting if p.id == procedure_id), None)
    if procedure is None:
        raise ValueError("Unknown product-owned troubleshooting procedure")
    state = TroubleshootingState(product_id, product.version, procedure_id, procedure.steps[0].id)
    return state, current(knowledge, state)


def restore(knowledge: SiteKnowledge, raw: dict) -> TroubleshootingState:
    if not isinstance(raw, dict) or set(raw) != {
        "product_id", "product_version", "procedure_id", "step_id", "attempts", "status"
    }:
        raise ValueError("Invalid troubleshooting snapshot")
    for key in ("product_id", "product_version", "procedure_id", "step_id", "status"):
        if not isinstance(raw[key], str) or not raw[key] or len(raw[key]) > 128:
            raise ValueError("Invalid troubleshooting identifier")
    if not isinstance(raw["attempts"], list) or len(raw["attempts"]) > 100:
        raise ValueError("Invalid attempts")
    attempts = []
    for item in raw["attempts"]:
        if not isinstance(item, dict) or set(item) != {"step_id", "result", "evidence_id"}:
            raise ValueError("Invalid attempt")
        if any(not isinstance(value, str) or not value or len(value) > 128 for value in item.values()):
            raise ValueError("Invalid attempt field")
        attempts.append(Attempt(**item))
    state = TroubleshootingState(
        raw["product_id"], raw["product_version"], raw["procedure_id"], raw["step_id"],
        tuple(attempts), raw["status"]
    )
    _validate(knowledge, state)
    return state


def current(knowledge: SiteKnowledge, state: TroubleshootingState) -> TroubleshootingReply:
    procedure, evidence = _validate(knowledge, state)
    if state.status == "resolved":
        return TroubleshootingReply(state.status, "Glad that worked! Issue marked resolved from your confirmation.", None, None)
    if state.status == "escalation_required":
        return TroubleshootingReply(
            state.status, "All documented checks were unsuccessful. Further help is needed.",
            None, None
        )
    step = procedure.steps[len(state.attempts)]
    return TroubleshootingReply(
        state.status, step.instruction + " Did this solve the problem?",
        step.id, evidence[step.evidence_id].source
    )


def advance(knowledge: SiteKnowledge, state: TroubleshootingState, result: Result):
    procedure, _ = _validate(knowledge, state)
    if state.status != "awaiting_result":
        raise ValueError("Troubleshooting has already ended")
    if result not in ("worked", "failed"):
        raise ValueError("Explicit worked/failed confirmation required")
    step = procedure.steps[len(state.attempts)]
    attempts = state.attempts + (Attempt(step.id, result, step.evidence_id),)
    if result == "worked":
        updated = replace(state, attempts=attempts, status="resolved")
    elif len(attempts) == len(procedure.steps):
        updated = replace(state, attempts=attempts, status="escalation_required")
    else:
        updated = replace(state, attempts=attempts, step_id=procedure.steps[len(attempts)].id)
    return updated, current(knowledge, updated)


def explain(knowledge: SiteKnowledge, state: TroubleshootingState) -> str:
    """Answer 'why?' with existing source text; do not generate a rationale."""
    procedure, evidence = _validate(knowledge, state)
    if state.status != "awaiting_result":
        raise ValueError("No pending step to explain")
    step = procedure.steps[len(state.attempts)]
    return evidence[step.evidence_id].text
