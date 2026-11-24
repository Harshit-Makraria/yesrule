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

## Step 6: Channels, redaction and webhooks (2026-11-24)

- `core/redact.py` strips API keys (Anthropic, OpenAI, GitHub, Slack, AWS), bearer tokens, private keys, card numbers and `password=` pairs before **any** text leaves the server.
- `channels.py` covers both chat channels:
  - **Telegram:** a message with ✅ Approve and ❌ Deny buttons. Button presses come back to `/v1/channels/telegram/webhook` and are accepted only with the secret header.
  - **Slack:** Block Kit buttons. Presses come back to `/v1/channels/slack/actions`, with the HMAC signature checked and requests older than 5 minutes rejected, which blocks replay.
- A broken channel never breaks the agent's request. It's logged and skipped.

## Step 7: More engine features (2026-11-24)

- **Two-person rule:** `approvals_needed` (1–5). Approvals count only from distinct people, and any deny ends the request.
- **Drift watch:** `POST /v1/requests/{id}/flag` marks an automatic approval as wrong. It's recorded as a human denial and the rule is paused, and that denial then blocks the same rule being proposed again.
- **Hard lines** API (validated), rule **backtest** endpoint, **insights**, **monthly client report**, audit listing, request detail with every decision.

## Step 8: Adapters (2026-11-24)

| Adapter | How it works |
|---|---|
| **Claude Code hook** (`adapters/claude_code.py`) | Checked against the official hooks docs: stdin JSON in, `hookSpecificOutput.permissionDecision` out. Maps Bash, Write, Edit and MCP tools to requests, and spots dangerous shell commands and production hints. Low risk goes to the native prompt, and a PostToolUse hook records that local approval as training data. Medium and high risk wait for a remote answer. **Engine down, timeout or error leads to no output, so Claude Code's own prompt appears. It never silently allows.** |
| **Installer** | `yesrule install claude-code [--dry-run] [--remove] [--scope user\|project]`. It's a pure function: it leaves other hooks untouched, is idempotent, backs up settings first, and `--remove` restores the original exactly (tested). |
| **MCP server** (`adapters/mcp_server.py`) | Uses MCP SDK 2.x (`MCPServer`; FastMCP was renamed, which we found when the import failed). Tools: `request_approval` (blocking), `check_approval`, `list_pending`, `explain_rules`. If the engine is unreachable it tells the agent **not** to proceed. |
| **Python SDK** (`sdk.py`) | `submit`, `wait`, `require` and the `@guard` decorator. **Bug found by tests:** `require(timeout=0)` treated 0 as "not set" and waited 600 seconds, which hung the test run. Fixed with an explicit `is not None` check. |
| **n8n node** (`integrations/n8n-nodes-yesrule`) | TypeScript, compiled against real `n8n-workflow` types. Two outputs (Approved and Denied), polls until a final answer, input values clamped to valid ranges. |
| **Importer** (`importer.py`) | Generic JSON or an n8n executions export (finds Send-and-Wait approval nodes). |
| **CLI** | `serve`, `hook`, `install`, `mcp`, `audit verify`, `import`, `demo`, `mine`. |

## Step 9: Dashboard (2026-11-24)

A single page served by the engine at `/`, with no separate frontend build, so `docker compose up` is the whole product. Tabs: **Inbox** (approve or deny, risk reasons, live refresh), **History** (with a "Wrong" button on automatic approvals), **Rules** (accept, pause, dismiss, backtest, evidence, strict or early mode), **Hard lines**, **Insights**, **Audit** (chain status in the header). Light and dark mode, and every value is HTML-escaped. The JavaScript is syntax-checked with `node --check`.

**Live check:**
- `yesrule demo` → 205 decisions
- `yesrule mine` → 3 rules, one per client's invoices, each with about 60 approvals and a Wilson bound around 0.94. Cold outreach to unknown leads correctly got **no** rule.
- Dashboard returns 200.
- Hook with `ls` → native prompt. Hook with `npm publish` and nobody answering → native prompt. Hook with the engine down → native prompt.

## Step 10: Packaging (2026-11-24)

Dockerfile (with a healthcheck and a data volume), `docker-compose.yml`, `.env.example`, GitHub Actions CI (lint, tests, a 100k-case fuzz run with a new seed every run, n8n build and test, Docker build), MIT licence, README.

Docker Desktop wasn't running on this machine, so the image build wasn't run locally. CI builds it.

## Step 11: 500,000-case property test (2026-11-24)

`engine/stress/fuzz.py` generates random requests, rules (all statuses and effects, 0–3 conditions), hard lines, decision histories and audit chains, then checks invariants. Every case can be replayed from (seed, case number) with `--replay`.

| Kind | Cases | Invariants |
|---|---|---|
| Decision engine | 300,000 | score is the capped sum of reasons; band matches the score; deterministic; hard line → person; high risk never auto-approved; auto-approve only through a matching active rule with nothing blocking it; matching deny rule → deny; inactive rules never change the verdict; empty rules never match; risk never falls when the amount rises |
| Rule miner | 50,000 | proposals are only `proposed`; never match a past denial; enough approvals; confidence above the threshold; amount bound never wider than what was approved |
| Audit chain | 90,000 | valid chains verify; edit, delete, reorder and forged hash are all detected |
| Redaction and callbacks | 40,000 | generated secrets never survive; callback round-trips; garbage input never crashes |
| Full service and database | 20,000 | real SQLite: high risk never auto-approved; first decision wins; audit chain valid after mining and accepting rules |

**Results:**
- seed 1: **500,000 passed, 0 failed** (6.1 s on 10 cores)
- seed 2: **500,000 passed, 0 failed** (6.3 s)

**The harness found a bug in itself first:** the monotonic-amount check compared a score that included the agent's denial rate with one that didn't. It was fixed in the test, and the engine was correct.

**Proving the harness can fail (mutation test):** I planted bugs in a scratch copy of the engine, never the real files, and ran 20,000 cases against each:

| Planted bug | Caught |
|---|---|
| High-risk guard removed | 309 failures |
| Hard lines ignored | 233 |
| Audit hash check skipped | 896 |
| Redaction disabled | 1,600 |
| First-decision-wins removed | 800 |
| Risk cap removed | 996 |
| Miner's denial check **and** backtest both removed | 273 |

Removing only one of the miner's two checks is caught by neither, which is correct: each check alone still blocks unsafe rules. That confirms the two layers really are independent.

---

## Final status

| Check | Result |
|---|---|
| `pytest` (engine) | **61 passed** |
| `ruff` | clean |
| n8n node tests | **3 passed**, type-checks against n8n |
| Property test | **1,000,000 cases (2 × 500k), 0 failures** |
| Mutation check | 7/7 planted bugs caught |
