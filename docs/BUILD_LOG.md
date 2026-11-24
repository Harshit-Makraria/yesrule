# Yesrule build log

What was built, how it works, and how it was tested, in order.

---

## Step 0: Name and project setup (2026-11-24)

**What:** picked the name and created the repository.

**How:**
- Checked six names against the npm registry, PyPI and GitHub search:

  | Name | npm | PyPI | GitHub repos |
  |---|---|---|---|
  | signoff | taken | free | 479 |
  | okayed | taken | free | 6 |
  | nodwise | free | free | 3 |
  | approvd | free | free | 14 |
  | **yesrule** | **free** | **free** | **0** |
  | tapprove | free | free | 2 |

- Chose **Yesrule**: completely unused, and it says what the product does ("yes" decisions turned into rules). The working name "Gatekeeper" was dropped because it collides with OPA Gatekeeper.
- Created `yesrule/`, `git init`, and `docs/OVERVIEW.md` (what we're building, features, plan, tools).

**Toolchain:** installed `uv` 0.12.19 for the user (`pip install --user uv`), then Python 3.13.16 through `uv python install`. The system Python is 3.9, which is too old.

---

## Step 1: Engine package (2026-11-24)

**What:** a Python package at `engine/`, managed by uv.

**How:** `uv init --package --name yesrule --python 3.13 engine`, then:
- runtime: `fastapi`, `uvicorn`, `pydantic`, `sqlalchemy`, `httpx`
- dev: `pytest`, `ruff`

Layout:
```
engine/
├── pyproject.toml
├── src/yesrule/core/     pure logic, no I/O (testable without a database or network)
└── tests/
```

---

## Step 2: Core logic (2026-11-24)

All four modules are **pure**: no database, no network, no model calls. Every decision Yesrule makes comes from here, which is why it can be tested and audited.

### `core/models.py`: the request format
One Pydantic model, `ApprovalRequest`, that every adapter (Claude Code, n8n, MCP, SDK) converts its events into: agent, platform, action, target, amount, recipient (known? external?), reversible, environment, client, context, fallback and timeout. Validation is built in (amounts can't be negative, timeouts between 5 seconds and 24 hours).

### `core/risk.py`: deterministic risk scoring
Adds points for each risk signal and returns the score, a band (low under 30, medium under 60, high 60+) and **the list of reasons**, so the UI can always explain a score.

| Signal | Points |
|---|---|
| Irreversible | 30 |
| Money involved | 10 (+20 above the client's limit) |
| New or unknown recipient | 25 (+20 if they're outside the organisation) |
| Production | 15 |
| Destructive or publishing action (`delete`, `publish`, `deploy`, or shell commands like `rm -rf`, `npm publish`, `git push --force`) | 30 |
| Agent's denial rate above 20% | 10 |

**Design fix found by a test:** at first, "data leaves the organisation" counted for every external recipient. That made a routine invoice to a *known* client score 75 (high), so it could never be auto-approved, which broke the product's main use case. Now that signal only counts for **new** outside parties. A known-client invoice scores 55 (medium). The same invoice to an unknown recipient scores 100 (high).

### `core/rules.py`: rules, hard lines and the decision
- `Condition(field, op, value)` reads dotted paths like `amount.value` or `recipient.known`, with operators `eq`, `ne`, `lte`, `gte`, `in`, `contains`.
- `Rule` = conditions (all must hold) + effect (approve or deny) + status (proposed, active, paused, expired). **Only active rules fire.** An empty rule never matches.
- `HardLine` = conditions that always send the request to a human.
- `decide()` checks in a fixed order:
  1. hard lines → ask a human
  2. active deny rules → auto-deny
  3. high risk → ask a human (**no rule can auto-approve high risk**)
  4. active approve rules → auto-approve
  5. otherwise → ask a human

### `core/audit.py`: tamper-evident log
Each entry stores the SHA-256 hash of (sequence, event, data, timestamp, previous hash). `verify()` walks the chain and returns the first bad entry if anything was **edited, deleted or reordered**.

---

## Step 3: Rule learning, the headline feature (2026-11-24)

### `core/miner.py`
1. **Group** past human decisions by *action shape*: platform, action, target type, whether the recipient is known, environment, client.
2. **Candidate** only if the group has at least 10 approvals, **zero denials** and approvals on at least 2 different days.
3. **Confidence:** the Wilson lower bound of the approval rate at 95% must be ≥ 0.90. In practice that needs **35 clean approvals**. A "suggest early" setting (≥ 0.80) needs fewer. The Wilson bound is used instead of the raw rate because 10/10 is 100% but only 72% at 95% confidence, so it stops rules being learned from small samples.
4. **Tightest rule:** conditions copy the group's shape, and the amount is limited to the **largest amount actually approved**, never "any amount".
5. **Backtest** against all history: the rule is dropped if it would have approved anything a human denied.
6. Proposals are created with status **`proposed`**. They never fire until a human accepts them.
7. Each rule carries its **evidence** (approvals, days, Wilson bound, backtest result). This becomes the receipt shown on every automatic approval.

**Honest note on the backtest:** a rule the miner generates already matches only its own group, and groups with any denial are skipped, so the backtest rarely rejects a fresh proposal. It matters when a **user edits a rule to make it broader**. The test `test_backtest_catches_a_broadened_rule` covers exactly that case. An earlier version of the test passed for the wrong reason (the group check caught it first), so it was rewritten.

---

## Step 4: Database (2026-11-24)

### `db.py`
SQLAlchemy 2 tables. SQLite by default (`yesrule.db`), Postgres by setting `YESRULE_DATABASE_URL`.

| Table | Holds |
|---|---|
| `requests` | the full request (JSON), risk score, band and reasons, status (`pending`, `approved`, `denied`, `expired`, `auto_approved`, `auto_denied`), verdict reason, matching rule, expiry |
| `decisions` | who decided (a person, `rule:R-7`, or a timeout), approve or deny, channel, response time, and **`human` true/false**. Only human decisions train the miner, so the system never learns from its own auto-approvals. |
| `rules` | conditions (JSON), effect, status, evidence, who accepted it, how often it fired |
| `hard_lines` | conditions that always go to a human |
| `audit_log` | the hash chain |

---

## Step 5: Service layer and HTTP API (2026-11-24)

### `service.py`: connects the pure core to the database
- `create_request`: loads rules and hard lines → `assess()` → `decide()` → saves the request → if a rule fired, records an automatic decision and bumps the rule's fire count → writes an audit entry.
- `record_decision`: **first decision wins** (a second answer gets `409`), rejects expired requests, records response time, writes an audit entry.
- `expire_overdue`: marks pending requests past their deadline as `expired`.
- `propose_rules`: runs the miner on **human decisions only**, skips rules that already exist, saves proposals as `proposed`.
- `set_rule_status`: accept, pause or dismiss, recording who did it.
- `verify_audit`: re-checks the whole hash chain.

### `api.py`: FastAPI endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness |
| POST | `/v1/requests` | an agent asks for approval → returns status, risk, reasons and (if auto-approved) the **receipt** |
| GET | `/v1/requests/{id}` | adapters poll for the decision |
| GET | `/v1/requests?status=pending` | inbox |
| POST | `/v1/requests/{id}/decision` | approve or deny |
| GET | `/v1/rules` | all rules with evidence |
| POST | `/v1/rules/mine` | run rule learning now (`min_confidence` adjustable) |
| POST | `/v1/rules/{id}/accept\|pause\|dismiss` | manage a rule |
| GET | `/v1/audit/verify` | check the audit chain |

Interactive API docs are generated automatically at `/docs`.

**Receipt example** (returned on an auto-approval):
```json
{"rule": "R-1", "description": "send_email on n8n for acme",
 "evidence": {"approvals": 40, "denials": 0, "days": 4, "wilson_lower_bound": 0.912, "backtest_matched_denials": 0},
 "accepted_by": "harshit"}
```

**Problems hit and fixed:**
- Decision timestamps came from a database default, so tests couldn't simulate approvals over several days. They're now set explicitly.
- In the learning-loop test, approved invoices were ₹30,000–₹33,900, and the test then expected ₹35,000 to auto-approve. It correctly didn't, because the rule caps at the largest approved amount. The test was wrong, not the code. It now checks both sides: ₹32,000 auto-approves, ₹35,000 asks a human.
- FastAPI couldn't resolve a dependency alias under postponed annotations (`422` errors). Removed `from __future__ import annotations` from `api.py`.

**Live smoke test:** started the server with `uvicorn yesrule.api:app` and sent a Claude Code `npm publish` request. Result: risk 75 (high), reasons "irreversible action", "production environment" and "destructive or publishing action", status `pending`, audit chain verified.

---

## Tests so far

`uv run pytest`: **30 passed**. `uv run ruff check`: clean.

| File | What it checks |
|---|---|
| `tests/test_api.py` (5) | new requests wait for a human with reasons; first decision wins; **the full loop**: 40 human approvals over 4 days → rule proposed → does nothing until accepted → accepted → next request auto-approved with a receipt naming the rule and who accepted it → amounts above the learned cap still ask a human; audit verify detects direct database tampering; expired requests can't be approved |

| File | What it checks |
|---|---|
| `tests/test_core.py` (15) | risk bands and reasons, the money limit, dangerous shell commands, rule matching, proposed rules never firing, high risk beating approve rules, hard lines beating everything, deny beating approve, the audit chain detecting edits and deletions |
| `tests/test_miner.py` (10) | Wilson bound values, 35 approvals needed at 0.90, proposals created only as `proposed`, the tightest amount bound, too few approvals, any denial blocking a proposal, single-day groups rejected, suggest-early mode, the backtest catching a widened rule, separate clients getting separate rules |

---

## Next

- Step 6: Claude Code PreToolUse hook + installer (`--dry-run`, `--remove`)
- Step 7: Telegram channel with Approve/Deny buttons
- Step 8: basic web inbox
