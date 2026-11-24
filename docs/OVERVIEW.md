# Yesrule: what we're building

> **Stop approving the same thing twice, and see the proof behind every automatic approval.**

## 1. What it is

Yesrule is an open-source, self-hosted **approval layer for AI agents**. Your agents (Claude Code, n8n workflows, MCP clients, your own code) send "may I do this?" requests to one place. You answer from Telegram, Slack or the web in one tap. Yesrule watches your decisions, **learns rules from them**, tests each rule against your history, and only then suggests it. Once you accept a rule, matching requests are approved automatically, each with a **receipt** explaining why.

## 2. The problem it solves

- Every agent asks for permission in a different place: Claude Code in the terminal, n8n through a hand-built Wait node, voice agents usually not at all.
- So people either click "yes" all day without reading, or switch on auto mode and hope.
- Existing approval tools (Impri, gotoHuman, withHuman, n8n's built-in approvals) give you an inbox, but **none learn from your decisions** or prove why something was auto-approved.

## 3. What it does

| Feature | What it means for you |
|---|---|
| **One inbox for every agent** | Claude Code, n8n, MCP and SDK requests all arrive in one place |
| **One-tap answers** | Approve, Deny or Edit from Telegram, Slack or the web |
| **Risk scoring** | Fixed, explainable rules: irreversible actions, money, new recipients, production systems and deletes add risk. High risk always reaches a human. |
| **Hard lines** | Things that are never auto-approved (e.g. payments above a limit, deletes, publishing) |
| **Learned rules** | After enough similar approvals, Yesrule proposes a rule, with the evidence and a test against your history |
| **Backtest safety** | Any rule that would have approved something you once denied is rejected automatically |
| **Receipts** | Every automatic decision says which rule fired, what evidence it was learned from, and who accepted it |
| **Drift watch** | If you start denying what a rule approves, the rule pauses itself |
| **Timeouts** | No answer in time → escalate, deny, or let the agent take a safer fallback |
| **Tamper-evident audit log** | Hash-chained; one command verifies nothing was edited |
| **Per-client reports** | For agencies: proof that clients' automations were supervised |

## 4. Example

1. An n8n workflow wants to email a ₹42,000 invoice to an existing client → Telegram: *"Send invoice ₹42,000 to Acme (11 past invoices). Approve / Deny"* → you tap Approve → the workflow continues.
2. After many similar approvals, Yesrule proposes: *"Auto-approve invoices ≤ ₹50,000 to known clients? Learned from 38 approvals, 0 denials. Backtest: would never have approved anything you denied."*
3. You accept. The next invoice is approved automatically with a receipt.
4. Claude Code wants to run `npm publish` → high risk → always asks you.

## 5. How we'll build it

**Architecture**

```
Agents (Claude Code hook, n8n node, MCP, SDK, REST)
        │
        ▼
Engine (FastAPI): normalise → risk score → hard lines → rule match
        │ match → auto-decide + receipt
        │ no match → send to Telegram / Slack / web → wait → timeout policy
        ▼
Decision → resume the agent → audit log (hash chain)
        │
        └─► Pattern miner → rule proposals + backtest
```

**Design principle:** every *decision* is deterministic (rules, thresholds, hard lines), so it can be tested and audited. AI models only write one-line summaries and intent labels.

**Build order (about 3 part-time weeks for v1)**

| Week | What gets built |
|---|---|
| 1 | Core engine: typed requests, risk scoring, hard lines, rule engine, audit chain, Claude Code hook, basic inbox |
| 2 | Telegram and Slack buttons, timeouts and escalation, the n8n node, the MCP server, the Python SDK |
| 3 | Rule learning with backtests, the n8n decision importer, insights, demo data, README, CI, launch |
| Later | WhatsApp, Retell/Vapi voice agents, Codex/Gemini hooks, per-client PDF reports |

## 6. Tools and stack

| Layer | Tool | Why |
|---|---|---|
| Engine language | **Python 3.13** | Strong for AI and data work; matches AI-engineer roles |
| Package manager | **uv** | Fast, modern Python tooling |
| API framework | **FastAPI + Pydantic** | Typed APIs with automatic OpenAPI docs |
| Database | **SQLite** locally, **Postgres** in production (via SQLAlchemy) | Zero-setup locally, robust in production |
| Background jobs | Async scheduler in the engine (timeouts, nightly rule mining) | No extra services for v1 |
| Tests | **pytest** | All model and channel calls faked offline |
| Lint and types | **Ruff**, **Pyright** | Clean, typed code |
| Dashboard | **Next.js 16, React 19, Tailwind v4** | Modern web stack; types generated from the API |
| n8n integration | **n8n community node** (TypeScript) | Native drag-and-drop node for n8n users |
| Claude Code integration | **PreToolUse hook script** + installer | Intercepts tool calls before they run |
| MCP | **FastMCP** | Any MCP client can request approvals |
| Channels | **Telegram Bot API**, **Slack Block Kit**, web push | One-tap buttons; WhatsApp later |
| Models (optional) | Bring your own key via **OpenRouter** | Summaries and intent labels only |
| Deployment | **Docker Compose** | One command to run everything |
| CI | **GitHub Actions** | Tests on every push, live badge |

## 7. How progress is tracked

Every step is recorded in [`BUILD_LOG.md`](BUILD_LOG.md): what was built, how it works, and how it was tested.
