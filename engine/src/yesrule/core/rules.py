"""Rules and hard lines.

A rule is a list of conditions on request fields. All conditions must hold for the rule to match.
Hard lines are checked first and always send the request to a human.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from yesrule.core.models import ApprovalRequest
from yesrule.core.risk import RiskAssessment, RiskBand

Op = str  # "eq" | "ne" | "lte" | "gte" | "in" | "contains"


@dataclass(frozen=True)
class Condition:
    field: str  # dotted path, e.g. "amount.value", "recipient.known", "action"
    op: Op
    value: Any

    def holds(self, req: ApprovalRequest) -> bool:
        actual = field_value(req, self.field)
        match self.op:
            case "eq":
                return actual == self.value
            case "ne":
                return actual != self.value
            case "lte":
                return actual is not None and actual <= self.value
            case "gte":
                return actual is not None and actual >= self.value
            case "in":
                return actual in self.value
            case "contains":
                return actual is not None and str(self.value).lower() in str(actual).lower()
            case _:
                raise ValueError(f"unknown operator {self.op!r}")


class Effect(StrEnum):
    APPROVE = "approve"
    DENY = "deny"


class RuleStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    PAUSED = "paused"
    EXPIRED = "expired"


@dataclass
class Rule:
    id: str
    conditions: list[Condition]
    effect: Effect = Effect.APPROVE
    status: RuleStatus = RuleStatus.ACTIVE
    description: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def matches(self, req: ApprovalRequest) -> bool:
        return bool(self.conditions) and all(c.holds(req) for c in self.conditions)


@dataclass
class HardLine:
    id: str
    conditions: list[Condition]
    description: str = ""

    def crossed(self, req: ApprovalRequest) -> bool:
        return bool(self.conditions) and all(c.holds(req) for c in self.conditions)


def field_value(req: ApprovalRequest, path: str) -> Any:
    """Read a dotted path from the request; missing parts return None."""
    obj: Any = req
    for part in path.split("."):
        if obj is None:
            return None
        obj = obj.get(part) if isinstance(obj, dict) else getattr(obj, part, None)
    return obj  # StrEnum members compare equal to their string values


class Outcome(StrEnum):
    AUTO_APPROVE = "auto_approve"
    AUTO_DENY = "auto_deny"
    ASK_HUMAN = "ask_human"


@dataclass(frozen=True)
class Verdict:
    outcome: Outcome
    reason: str
    rule_id: str | None = None
    hard_line_id: str | None = None


def decide(req: ApprovalRequest, risk: RiskAssessment, rules: list[Rule], hard_lines: list[HardLine]) -> Verdict:
    """Order matters: hard lines, then high risk, then deny rules, then approve rules, then a human."""
    for line in hard_lines:
        if line.crossed(req):
            return Verdict(Outcome.ASK_HUMAN, f"hard line: {line.description or line.id}", hard_line_id=line.id)

    active = [r for r in rules if r.status is RuleStatus.ACTIVE]

    for rule in active:
        if rule.effect is Effect.DENY and rule.matches(req):
            return Verdict(Outcome.AUTO_DENY, f"denied by rule {rule.id}", rule_id=rule.id)

    if risk.band is RiskBand.HIGH:
        return Verdict(Outcome.ASK_HUMAN, f"high risk ({risk.score})")

    for rule in active:
        if rule.effect is Effect.APPROVE and rule.matches(req):
            return Verdict(Outcome.AUTO_APPROVE, f"approved by rule {rule.id}", rule_id=rule.id)

    return Verdict(Outcome.ASK_HUMAN, "no matching rule")
