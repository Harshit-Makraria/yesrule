"""Deterministic risk scoring. No model is involved, so every score is explainable."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from yesrule.core.models import ApprovalRequest, Environment

DANGEROUS_ACTIONS = frozenset(
    {"delete", "delete_record", "drop", "publish", "deploy", "permission_change", "transfer", "refund_all"}
)
# Shell commands that are destructive or publish something; matched as substrings of Bash commands.
DANGEROUS_SHELL = ("rm -rf", "npm publish", "git push --force", "drop table", "kubectl delete", "terraform destroy")


class RiskBand(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class RiskAssessment:
    score: int
    band: RiskBand
    reasons: list[tuple[str, int]] = field(default_factory=list)


def _band(score: int) -> RiskBand:
    if score >= 60:
        return RiskBand.HIGH
    if score >= 30:
        return RiskBand.MEDIUM
    return RiskBand.LOW


def assess(req: ApprovalRequest, *, money_limit: float | None = None, agent_denial_rate: float = 0.0) -> RiskAssessment:
    """Score a request. `money_limit` is the client's own threshold; above it money counts double."""
    reasons: list[tuple[str, int]] = []

    if not req.reversible:
        reasons.append(("irreversible action", 30))

    if req.amount is not None and req.amount.value > 0:
        reasons.append(("involves money", 10))
        if money_limit is not None and req.amount.value > money_limit:
            reasons.append((f"amount above limit {money_limit:g}", 20))

    if req.recipient is not None and not req.recipient.known:
        reasons.append(("new or unknown recipient", 25))
        # Sending to a known client is the routine case; only new outside parties add this.
        if req.recipient.external:
            reasons.append(("data leaves the organisation to a new party", 20))

    if req.environment is Environment.PRODUCTION:
        reasons.append(("production environment", 15))

    action = req.action.lower()
    command = str(req.context.get("command", "")).lower()
    if action in DANGEROUS_ACTIONS or any(s in command for s in DANGEROUS_SHELL):
        reasons.append(("destructive or publishing action", 30))

    if agent_denial_rate > 0.2:
        reasons.append((f"agent denied {agent_denial_rate:.0%} of the time", 10))

    score = min(100, sum(points for _, points in reasons))
    return RiskAssessment(score=score, band=_band(score), reasons=reasons)
