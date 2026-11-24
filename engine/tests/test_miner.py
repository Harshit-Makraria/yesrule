from datetime import datetime, timedelta

import pytest

from yesrule.core.miner import (
    MinerSettings,
    PastDecision,
    backtest,
    mine,
    needed_for_confidence,
    wilson_lower_bound,
)
from yesrule.core.models import ApprovalRequest, Environment, Money, Platform, Recipient
from yesrule.core.rules import Rule, RuleStatus

START = datetime(2026, 11, 1, 10, 0)


def refund(amount: float, client: str = "clinic-a") -> ApprovalRequest:
    return ApprovalRequest(
        agent="support-voice",
        platform=Platform.RETELL,
        action="refund",
        amount=Money(value=amount),
        recipient=Recipient(id="cust", known=True),
        environment=Environment.PRODUCTION,
        client=client,
    )


def history(n: int, approved: bool = True, amount: float = 1_200, days: int = 5, client: str = "clinic-a"):
    return [
        PastDecision(refund(amount + i, client), approved, START + timedelta(days=i % days, minutes=i))
        for i in range(n)
    ]


def test_wilson_bound_known_values():
    assert wilson_lower_bound(0, 0) == 0.0
    assert wilson_lower_bound(10, 10) == pytest.approx(0.722, abs=0.002)
    assert wilson_lower_bound(50, 50) > 0.92


def test_needed_for_confidence_is_monotonic():
    assert needed_for_confidence(0.80) < needed_for_confidence(0.90)
    assert needed_for_confidence(0.90) == 35


def test_proposes_rule_after_enough_clean_approvals():
    proposals = mine(history(40))
    assert len(proposals) == 1
    p = proposals[0]
    assert p.rule.status is RuleStatus.PROPOSED  # never applied automatically
    assert p.backtest.passed and p.backtest.matched_past_denials == 0
    assert p.rule.evidence["approvals"] == 40


def test_rule_uses_tightest_amount_bound():
    rule = mine(history(40))[0].rule
    bound = next(c for c in rule.conditions if c.field == "amount.value")
    assert bound.op == "lte" and bound.value == 1_239  # largest amount seen, not unlimited


def test_too_few_approvals_no_proposal():
    assert mine(history(9)) == []


def test_any_denial_in_group_blocks_proposal():
    data = history(40) + [PastDecision(refund(1_100), False, START)]
    assert mine(data) == []


def test_single_day_not_enough():
    assert mine(history(40, days=1)) == []


def test_suggest_early_mode_needs_fewer():
    early = MinerSettings(min_confidence=0.80)
    assert mine(history(20)) == []
    assert len(mine(history(20), early)) == 1


def test_backtest_catches_a_broadened_rule():
    # The miner proposes a tight rule; a user widens it by dropping the client condition.
    # Backtest must then catch a denial from another client the wider rule would approve.
    data = history(40, client="clinic-a") + [PastDecision(refund(900, client="clinic-b"), False, START)]
    rule = mine(data)[0].rule
    assert backtest(rule, data).passed  # tight rule: clean

    widened = Rule(id="R-x", conditions=[c for c in rule.conditions if c.field != "client"])
    result = backtest(widened, data)
    assert not result.passed and result.matched_past_denials == 1


def test_separate_clients_get_separate_rules():
    data = history(40, client="clinic-a") + history(40, client="clinic-b")
    clients = {p.rule.evidence and p.shape[5] for p in mine(data)}
    assert clients == {"clinic-a", "clinic-b"}
