"""Portable troubleshooting issue record; no ticket creation or submission."""
from dataclasses import dataclass
from uuid import UUID

from purrfect.knowledge import SiteKnowledge
from purrfect.troubleshooting import TroubleshootingState, current


@dataclass(frozen=True)
class IssueAttempt:
    step_id: str
    evidence_id: str
    source: str
    user_reported_result: str


@dataclass(frozen=True)
class IssueRecord:
    issue_id: str
    product_id: str
    product_version: str
    procedure_id: str
    summary: str
    outcome: str
    attempts: tuple[IssueAttempt, ...]
    contract_version: int = 1

    def __post_init__(self):
        if self.contract_version != 1 or self.outcome not in ("resolved", "escalation_required"):
            raise ValueError("Invalid issue contract or outcome")
        if not isinstance(self.summary, str) or not self.summary.strip() or len(self.summary) > 2000:
            raise ValueError("Issue summary required")
        if UUID(self.issue_id).version != 7:
            raise ValueError("Issue ID must be UUIDv7")

    def export(self) -> dict:
        return {
            "contract_version": self.contract_version, "issue_id": self.issue_id,
            "product_id": self.product_id, "product_version": self.product_version,
            "procedure_id": self.procedure_id, "summary": self.summary,
            "outcome": self.outcome,
            "attempts": [
                {"step_id": a.step_id, "evidence_id": a.evidence_id,
                 "source": a.source, "user_reported_result": a.user_reported_result}
                for a in self.attempts
            ],
        }


def build_issue_record(knowledge: SiteKnowledge, state: TroubleshootingState,
                       issue_id: str, summary: str) -> IssueRecord:
    """Build from validated, current product evidence; never infer missing facts."""
    current(knowledge, state)
    if state.status not in ("resolved", "escalation_required"):
        raise ValueError("Issue is still in progress")
    product = knowledge.products[state.product_id]
    by_id = {e.id: e for e in product.evidence}
    attempts = tuple(IssueAttempt(a.step_id, a.evidence_id, by_id[a.evidence_id].source, a.result)
                     for a in state.attempts)
    return IssueRecord(issue_id, state.product_id, state.product_version,
                       state.procedure_id, summary, state.status, attempts)
