from dataclasses import replace

from yesrule.core.audit import make_entry, verify
from yesrule.core.models import ApprovalRequest, Environment, Money, Platform, Recipient
from yesrule.core.risk import RiskBand, assess
from yesrule.core.rules import (
    Condition,
    Effect,
    HardLine,
    Outcome,
    Rule,
    RuleStatus,
    decide,
)


def invoice(amount: float = 42_000, known: bool = True) -> ApprovalRequest:
    return ApprovalRequest(
        agent="invoice-bot",
        platform=Platform.N8N,
        action="send_email",
        amount=Money(value=amount),
        recipient=Recipient(id="acme@client.com", known=known, past_count=11),
        reversible=False,
        environment=Environment.PRODUCTION,
    )


INVOICE_RULE = Rule(
    id="R-1",
    conditions=[
        Condition("action", "eq", "send_email"),
        Condition("amount.value", "lte", 50_000),
        Condition("recipient.known", "eq", True),
    ],
)


# --- risk ---------------------------------------------------------------

def test_safe_read_is_low_risk():
    req = ApprovalRequest(agent="cc", platform=Platform.CLAUDE_CODE, action="read_file")
    assert assess(req).band is RiskBand.LOW


def test_known_invoice_is_medium_and_explained():
    risk = assess(invoice())
    labels = [r for r, _ in risk.reasons]
    assert "irreversible action" in labels and "production environment" in labels
    assert risk.score == sum(p for _, p in risk.reasons)


def test_unknown_recipient_pushes_to_high():
    assert assess(invoice(known=False)).band is RiskBand.HIGH


def test_dangerous_shell_command_detected():
    req = ApprovalRequest(agent="cc", platform=Platform.CLAUDE_CODE, action="bash", context={"command": "npm publish"})
    assert any("destructive" in r for r, _ in assess(req).reasons)


def test_money_limit_adds_points():
    assert assess(invoice(90_000), money_limit=50_000).score > assess(invoice(40_000), money_limit=50_000).score


# --- rules --------------------------------------------------------------

def test_rule_matches_and_auto_approves():
    req = invoice()
    v = decide(req, assess(req, money_limit=100_000), [INVOICE_RULE], [])
    assert v.outcome is Outcome.AUTO_APPROVE and v.rule_id == "R-1"


def test_rule_does_not_match_above_amount():
    req = invoice(60_000)
    assert decide(req, assess(req), [INVOICE_RULE], []).outcome is Outcome.ASK_HUMAN


def test_proposed_rule_never_fires():
    req = invoice()
    proposed = replace(INVOICE_RULE, status=RuleStatus.PROPOSED)
    assert decide(req, assess(req), [proposed], []).outcome is Outcome.ASK_HUMAN


def test_high_risk_beats_approve_rule():
    req = invoice(known=False)
    loose = Rule(id="R-2", conditions=[Condition("action", "eq", "send_email")])
    assert decide(req, assess(req), [loose], []).outcome is Outcome.ASK_HUMAN


def test_hard_line_beats_everything():
    req = invoice()
    line = HardLine(id="H-1", conditions=[Condition("amount.value", "gte", 40_000)], description="big payments")
    v = decide(req, assess(req), [INVOICE_RULE], [line])
    assert v.outcome is Outcome.ASK_HUMAN and v.hard_line_id == "H-1"


def test_deny_rule_wins_over_approve_rule():
    req = invoice()
    deny = Rule(id="R-9", conditions=[Condition("platform", "eq", "n8n")], effect=Effect.DENY)
    assert decide(req, assess(req), [INVOICE_RULE, deny], []).outcome is Outcome.AUTO_DENY


def test_empty_rule_never_matches():
    assert not Rule(id="R-0", conditions=[]).matches(invoice())


# --- audit --------------------------------------------------------------

def _chain(n: int = 3):
    entries, prev = [], None
    for i in range(n):
        prev = make_entry(prev, "decision", {"i": i}, f"2026-11-24T10:0{i}:00Z")
        entries.append(prev)
    return entries


def test_audit_chain_verifies():
    assert verify(_chain()) == (True, None)


def test_audit_detects_edit():
    entries = _chain()
    entries[1] = replace(entries[1], data={"i": 999})
    assert verify(entries) == (False, 2)


def test_audit_detects_deletion():
    entries = _chain()
    del entries[1]
    assert verify(entries)[0] is False
