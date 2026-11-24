"""Randomised property test: N generated cases checked against Yesrule's safety invariants.

    uv run python stress/fuzz.py --cases 500000 --seed 1

Every case is generated from (seed, case number), so any failure can be replayed exactly with --replay.
Case mix: 60% decision engine, 10% rule miner, 18% audit chain, 8% redaction/callbacks, 4% full service + database.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import random
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta

from yesrule.channels import callback_data, parse_callback
from yesrule.core import audit
from yesrule.core.miner import MinerSettings, PastDecision, backtest, mine
from yesrule.core.models import ApprovalRequest
from yesrule.core.redact import redact
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

ACTIONS = ["send_email", "refund", "bash", "edit_file", "delete_record", "publish", "deploy", "create_invoice",
           "post_tweet", "transfer", "read_report", "update_crm"]
PLATFORMS = ["claude_code", "codex", "n8n", "mcp", "retell", "vapi", "sdk"]
ENVS = ["production", "staging", "development", "unknown"]
CLIENTS = [None, "acme", "nova", "bright", "zen"]
COMMANDS = ["ls", "git status", "npm test", "rm -rf build", "npm publish", "git push --force", "kubectl delete pod x",
            "terraform destroy", "echo hi", "DROP TABLE users", "pytest"]
OPS = ["eq", "ne", "lte", "gte", "in", "contains"]
FIELDS = ["action", "platform", "environment", "client", "amount.value", "recipient.known", "reversible",
          "target.type"]


def gen_request(r: random.Random) -> ApprovalRequest:
    d: dict = {"agent": r.choice(["bot-a", "bot-b", "voice", "claude"]), "platform": r.choice(PLATFORMS),
               "action": r.choice(ACTIONS), "target": {"type": r.choice(["invoice", "order", "shell", "file", "lead"])},
               "reversible": r.random() < 0.5, "environment": r.choice(ENVS), "client": r.choice(CLIENTS)}
    if r.random() < 0.6:
        d["amount"] = {"value": round(r.choice([r.uniform(0, 2_000), r.uniform(0, 200_000)]), 2)}
    if r.random() < 0.6:
        d["recipient"] = {"id": "x@y.z", "known": r.random() < 0.6, "external": r.random() < 0.8}
    if d["action"] == "bash" or r.random() < 0.1:
        d["context"] = {"command": r.choice(COMMANDS)}
    return ApprovalRequest.model_validate(d)


def gen_condition(r: random.Random) -> Condition:
    f = r.choice(FIELDS)
    op = r.choice(OPS)
    vals = {"action": ACTIONS, "platform": PLATFORMS, "environment": ENVS, "client": CLIENTS[1:],
            "target.type": ["invoice", "order", "shell"], "recipient.known": [True, False],
            "reversible": [True, False]}
    if f == "amount.value":
        v = round(r.uniform(0, 100_000), 2)
        op = r.choice(["lte", "gte", "eq", "ne"])
    else:
        pool = vals[f]
        v = r.sample(pool, k=min(2, len(pool))) if op == "in" else r.choice(pool)
        if op in {"lte", "gte"}:
            op = "eq"
    return Condition(f, op, v)


def gen_rule(r: random.Random, i: int) -> Rule:
    return Rule(f"R-{i}", [gen_condition(r) for _ in range(r.randint(0, 3))],
                r.choice([Effect.APPROVE, Effect.APPROVE, Effect.DENY]), r.choice(list(RuleStatus)))


# --- case kinds ---------------------------------------------------------------

def case_decide(r: random.Random) -> None:
    req = gen_request(r)
    limit = r.choice([None, 1_000.0, 50_000.0])
    rate = r.random() * 0.5
    risk = assess(req, money_limit=limit, agent_denial_rate=rate)
    total = sum(p for _, p in risk.reasons)
    assert 0 <= risk.score <= 100, "score out of range"
    assert risk.score == min(100, total), "score != capped sum of reasons"
    expected_band = RiskBand.HIGH if risk.score >= 60 else RiskBand.MEDIUM if risk.score >= 30 else RiskBand.LOW
    assert risk.band == expected_band, "band inconsistent with score"

    rules = [gen_rule(r, i) for i in range(r.randint(0, 6))]
    lines = [HardLine(f"H-{i}", [gen_condition(r) for _ in range(r.randint(1, 2))]) for i in range(r.randint(0, 2))]
    v = decide(req, risk, rules, lines)
    assert v == decide(req, risk, rules, lines), "non-deterministic"

    crossed = any(h.crossed(req) for h in lines)
    active = [x for x in rules if x.status is RuleStatus.ACTIVE]
    deny_hit = any(x.effect is Effect.DENY and x.matches(req) for x in active)
    approve_hit = any(x.effect is Effect.APPROVE and x.matches(req) for x in active)
    if crossed:
        assert v.outcome is Outcome.ASK_HUMAN, "hard line did not force a human"
    if risk.band is RiskBand.HIGH:
        assert v.outcome is not Outcome.AUTO_APPROVE, "high risk auto-approved"
    if v.outcome is Outcome.AUTO_APPROVE:
        assert approve_hit and not deny_hit and not crossed, "auto-approve without a valid active rule"
        rule = next(x for x in rules if x.id == v.rule_id)
        assert rule.status is RuleStatus.ACTIVE and rule.matches(req), "receipt names wrong rule"
    if v.outcome is Outcome.AUTO_DENY:
        assert deny_hit and not crossed, "auto-deny without an active deny rule"
    if deny_hit and not crossed:
        assert v.outcome is Outcome.AUTO_DENY, "matching deny rule ignored"
    if not active:
        assert v.outcome is Outcome.ASK_HUMAN, "inactive rules changed the outcome"
    assert v == decide(req, risk, active, lines), "non-active rules affected the verdict"
    assert not any(x.matches(req) for x in rules if not x.conditions), "empty rule matched"

    if req.amount is not None and limit is not None:  # monotonic in amount
        bigger = req.model_copy(update={"amount": req.amount.model_copy(update={"value": limit * 2 + 1})})
        assert assess(bigger, money_limit=limit, agent_denial_rate=rate).score >= risk.score, "raising amount lowered risk"


def case_miner(r: random.Random) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    shapes = [gen_request(r) for _ in range(r.randint(1, 3))]
    history: list[PastDecision] = []
    for _ in range(r.randint(0, 70)):
        base = r.choice(shapes)
        req = base
        if base.amount is not None:
            req = base.model_copy(update={"amount": base.amount.model_copy(
                update={"value": round(r.uniform(0, 5_000), 2)})})
        approved = r.random() < r.choice([0.9, 0.98, 1.0, 1.0])
        history.append(PastDecision(req, approved, start + timedelta(days=r.randint(0, 9), minutes=r.randint(0, 999))))
    settings = MinerSettings(min_approvals=r.choice([5, 10]), min_days=r.choice([1, 2]),
                             min_confidence=r.choice([0.8, 0.9]))
    for p in mine(history, settings):
        rule = p.rule
        assert rule.status is RuleStatus.PROPOSED, "miner applied a rule"
        assert p.backtest.matched_past_denials == 0, "proposal fails its own backtest"
        rule_active = Rule(rule.id, rule.conditions, Effect.APPROVE, RuleStatus.ACTIVE)
        assert backtest(rule_active, history).passed, "rule would approve a past denial"
        assert not any(rule_active.matches(d.request) for d in history if not d.approved), "past denial matched"
        assert p.approvals >= settings.min_approvals, "too few approvals"
        assert p.confidence >= settings.min_confidence, "confidence below threshold"
        bound = [c for c in rule.conditions if c.field == "amount.value"]
        if bound:
            covered = [d.request.amount.value for d in history if d.approved and rule_active.matches(d.request)]
            assert bound[0].op == "lte" and covered and bound[0].value <= max(covered) + 1e-9, "amount bound too wide"


def case_audit(r: random.Random) -> None:
    entries: list[audit.AuditEntry] = []
    prev = None
    for i in range(r.randint(1, 12)):
        prev = audit.make_entry(prev, r.choice(["request", "decision", "rule_active"]),
                                {"i": i, "v": r.random(), "s": r.choice(["a", "ü", "😀", ""])}, f"2026-01-01T00:00:{i:02d}")
        entries.append(prev)
    assert audit.verify(entries) == (True, None), "valid chain rejected"
    kind = r.choice(["edit", "delete", "swap", "forge_hash", "none"])
    t = list(entries)
    if kind == "edit":
        k = r.randrange(len(t))
        e = t[k]
        t[k] = audit.AuditEntry(e.seq, e.event, {**e.data, "v": -1}, e.created_at, e.prev_hash, e.hash)
    elif kind == "delete" and len(t) > 1:
        del t[r.randrange(len(t) - 1)]  # deleting anything but the tail breaks the chain
    elif kind == "swap" and len(t) > 1:
        k = r.randrange(len(t) - 1)
        t[k], t[k + 1] = t[k + 1], t[k]
    elif kind == "forge_hash":
        k = r.randrange(len(t))
        e = t[k]
        t[k] = audit.AuditEntry(e.seq, e.event, e.data, e.created_at, e.prev_hash, "f" * 64)
    else:
        return
    if t != entries:
        assert audit.verify(t)[0] is False, f"tampering ({kind}) not detected"


SECRETS = [lambda r: "sk-ant-api03-" + "".join(r.choices("abcdefXYZ0123_-", k=30)),
           lambda r: "sk-proj-" + "".join(r.choices("abcdefXYZ0123", k=40)),
           lambda r: "ghp_" + "".join(r.choices("abcdefXYZ0123", k=36)),
           lambda r: "xoxb-" + "".join(r.choices("0123456789abc-", k=24)),
           lambda r: "AKIA" + "".join(r.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567", k=16)),
           lambda r: " ".join("".join(r.choices("0123456789", k=4)) for _ in range(4))]


def case_redact(r: random.Random) -> None:
    secret = r.choice(SECRETS)(r)
    noise = "".join(r.choices("abc xyz.,:/=", k=r.randint(0, 30)))
    text = f"{noise} {secret} {noise}" if r.random() < 0.8 else f"password={secret}"
    out = redact(text)
    assert secret not in out, "secret leaked through redaction"
    rid = "req_" + "".join(r.choices("0123456789abcdef", k=16))
    ok = r.random() < 0.5
    assert parse_callback(callback_data(rid, ok)) == (rid, ok), "callback roundtrip broke"
    garbage = "".join(r.choices("yr:ad_x0123", k=r.randint(0, 20)))
    parse_callback(garbage)  # must never raise


_SVC: dict = {}


def case_service(r: random.Random) -> None:
    """Full path through the service layer and a real (in-memory SQLite) database."""
    from yesrule import service
    from yesrule.db import RequestRow, make_session_factory

    if "f" not in _SVC:
        _SVC["f"] = make_session_factory("sqlite://")
        _SVC["n"] = 0
    db = _SVC["f"]()
    try:
        if _SVC["n"] % 200 == 0 and r.random() < 0.5:
            service.add_hard_line(db, f"H-{_SVC['n']}", "fuzz", [{"field": "client", "op": "eq", "value": r.choice(CLIENTS[1:])}])
        _SVC["n"] += 1
        req = gen_request(r)
        row = service.create_request(db, req)
        assert row.status in {"pending", "auto_approved", "auto_denied"}, "bad initial status"
        if row.risk_band == "high":
            assert row.status != "auto_approved", "high risk auto-approved through service"
        if row.status == "pending":
            first = r.random() < 0.5
            service.record_decision(db, row.id, approved=first, by="p1")
            try:
                service.record_decision(db, row.id, approved=not first, by="p2")
                raise AssertionError("second decision accepted")
            except service.DecisionError:
                pass
            assert db.get(RequestRow, row.id).status == ("approved" if first else "denied"), "first-wins violated"
        if _SVC["n"] % 500 == 0:
            for p in service.propose_rules(db):
                if r.random() < 0.7:
                    service.set_rule_status(db, p.id, RuleStatus.ACTIVE, "fuzz")
            ok, bad, _ = service.verify_audit(db)
            assert ok, f"audit chain broken at {bad}"
    finally:
        db.close()


KINDS = [(case_decide, 60), (case_miner, 10), (case_audit, 18), (case_redact, 8), (case_service, 4)]


def kind_for(i: int) -> int:
    x = i % 100
    acc = 0
    for k, (_, w) in enumerate(KINDS):
        acc += w
        if x < acc:
            return k
    return 0


def run_chunk(args: tuple[int, int, int]) -> tuple[Counter, list[dict]]:
    seed, lo, hi = args
    counts: Counter = Counter()
    failures: list[dict] = []
    for i in range(lo, hi):
        k = kind_for(i)
        fn = KINDS[k][0]
        try:
            fn(random.Random(seed * 1_000_003 + i))
            counts[fn.__name__] += 1
        except Exception as e:  # noqa: BLE001 - we report every failure with its replay id
            counts["FAILED"] += 1
            if len(failures) < 20:
                failures.append({"case": i, "kind": fn.__name__, "error": f"{type(e).__name__}: {e}"})
    return counts, failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=500_000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=mp.cpu_count())
    ap.add_argument("--replay", type=int, help="run one case number and show the traceback")
    ap.add_argument("--json", help="write a summary JSON here")
    a = ap.parse_args()
    if a.replay is not None:
        KINDS[kind_for(a.replay)][0](random.Random(a.seed * 1_000_003 + a.replay))
        print("case passed")
        return 0
    t0 = time.time()
    chunk = 5_000
    jobs = [(a.seed, lo, min(lo + chunk, a.cases)) for lo in range(0, a.cases, chunk)]
    total: Counter = Counter()
    failures: list[dict] = []
    with mp.get_context("spawn").Pool(a.workers) as pool:
        for done, (c, f) in enumerate(pool.imap_unordered(run_chunk, jobs), 1):
            total += c
            failures += f
            if done % 10 == 0 or done == len(jobs):
                print(f"  {sum(total.values()):>8,} / {a.cases:,} cases  ({time.time() - t0:.0f}s)", flush=True)
    secs = time.time() - t0
    passed = sum(v for k, v in total.items() if k != "FAILED")
    print(f"\n{passed:,} passed, {total['FAILED']:,} failed in {secs:.1f}s  (seed {a.seed}, {a.workers} workers)")
    for k, v in sorted(total.items()):
        print(f"  {k:<14} {v:>8,}")
    for f in failures[:20]:
        print("FAIL", f)
    if a.json:
        with open(a.json, "w") as fh:
            json.dump({"cases": a.cases, "seed": a.seed, "passed": passed, "failed": total["FAILED"],
                       "seconds": round(secs, 1), "by_kind": dict(total), "failures": failures[:20]}, fh, indent=2)
    return 1 if total["FAILED"] else 0


if __name__ == "__main__":
    sys.exit(main())
