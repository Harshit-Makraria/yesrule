"""Learn rules from past human decisions, then backtest them before proposing.

Steps:
1. Group decisions by "action shape" (platform, action, target type, recipient known, environment).
2. A group becomes a candidate only with enough approvals, zero denials and decisions on 2+ days.
3. Confidence = Wilson lower bound of the approval rate (95%) must clear a threshold.
4. Propose the tightest rule covering the group (amount <= largest amount seen, not "any amount").
5. Backtest against all history: if the rule would have approved anything a human denied, drop it.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from yesrule.core.models import ApprovalRequest
from yesrule.core.rules import Condition, Rule, RuleStatus

Z_95 = 1.959964


@dataclass(frozen=True)
class PastDecision:
    request: ApprovalRequest
    approved: bool
    decided_at: datetime


@dataclass
class MinerSettings:
    min_approvals: int = 10
    min_days: int = 2
    min_confidence: float = 0.90  # Wilson lower bound; 0.80 = "suggest early" mode


@dataclass
class Backtest:
    would_auto_approve: int
    matched_past_denials: int
    passed: bool


@dataclass
class Proposal:
    rule: Rule
    approvals: int
    denials: int
    confidence: float
    backtest: Backtest
    shape: tuple = field(default_factory=tuple)


def wilson_lower_bound(successes: int, total: int, z: float = Z_95) -> float:
    if total == 0:
        return 0.0
    p = successes / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return (centre - margin) / denom


def action_shape(req: ApprovalRequest) -> tuple:
    return (
        str(req.platform),
        req.action,
        req.target.type,
        None if req.recipient is None else req.recipient.known,
        str(req.environment),
        req.client,
    )


def _conditions_for(group: list[PastDecision]) -> list[Condition]:
    sample = group[0].request
    conds = [
        Condition("platform", "eq", str(sample.platform)),
        Condition("action", "eq", sample.action),
        Condition("target.type", "eq", sample.target.type),
        Condition("environment", "eq", str(sample.environment)),
    ]
    if sample.recipient is not None:
        conds.append(Condition("recipient.known", "eq", sample.recipient.known))
    if sample.client is not None:
        conds.append(Condition("client", "eq", sample.client))
    amounts = [d.request.amount.value for d in group if d.request.amount is not None]
    if amounts:
        conds.append(Condition("amount.value", "lte", max(amounts)))  # tightest bound seen
    return conds


def backtest(rule: Rule, history: list[PastDecision]) -> Backtest:
    hits = [d for d in history if rule.matches(d.request)]
    denials = sum(1 for d in hits if not d.approved)
    return Backtest(would_auto_approve=len(hits) - denials, matched_past_denials=denials, passed=denials == 0)


def mine(history: list[PastDecision], settings: MinerSettings | None = None, *, next_id: int = 1) -> list[Proposal]:
    s = settings or MinerSettings()
    groups: dict[tuple, list[PastDecision]] = defaultdict(list)
    for d in history:
        groups[action_shape(d.request)].append(d)

    proposals: list[Proposal] = []
    for shape, group in groups.items():
        approved = [d for d in group if d.approved]
        denied = len(group) - len(approved)
        days = {d.decided_at.date() for d in approved}
        if denied or len(approved) < s.min_approvals or len(days) < s.min_days:
            continue
        confidence = wilson_lower_bound(len(approved), len(group))
        if confidence < s.min_confidence:
            continue

        rule = Rule(
            id=f"R-{next_id}",
            conditions=_conditions_for(approved),
            status=RuleStatus.PROPOSED,
            description=f"{shape[1]} on {shape[0]}" + (f" for {shape[5]}" if shape[5] else ""),
        )
        result = backtest(rule, history)  # against ALL history, not just the group
        if not result.passed:
            continue
        rule.evidence = {
            "approvals": len(approved),
            "denials": 0,
            "days": len(days),
            "wilson_lower_bound": round(confidence, 3),
            "backtest_matched_denials": 0,
        }
        proposals.append(Proposal(rule, len(approved), 0, confidence, result, shape))
        next_id += 1
    return proposals


def needed_for_confidence(threshold: float, max_n: int = 500) -> int:
    """Smallest number of clean approvals (n/n) whose Wilson bound clears `threshold`."""
    for n in range(1, max_n + 1):
        if wilson_lower_bound(n, n) >= threshold:
            return n
    return max_n
