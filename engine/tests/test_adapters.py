import json

import httpx
import pytest
from fastapi.testclient import TestClient

from yesrule.adapters import claude_code as cc
from yesrule.api import create_app
from yesrule.importer import detect_and_parse, import_decisions
from yesrule.sdk import Denied, Unavailable, Yesrule

from .conftest import invoice


@pytest.fixture
def yr(tmp_path):
    app = create_app(f"sqlite:///{tmp_path}/t.db", channels=[])
    tc = TestClient(app)
    return Yesrule("http://testserver", agent="t", client=tc, poll_interval=0)


def bash_event(cmd: str, tid: str = "toolu_1") -> dict:
    return {"session_id": "s", "cwd": "/home/u/shop", "hook_event_name": "PreToolUse", "tool_name": "Bash",
            "tool_input": {"command": cmd}, "tool_use_id": tid, "permission_mode": "default"}


def test_to_request_mapping():
    r = cc.to_request(bash_event("git push --force origin main"))
    assert r["action"] == "bash" and r["reversible"] is False and r["environment"] == "production"
    assert r["context"]["command"].startswith("git push")
    w = cc.to_request({"tool_name": "Write", "tool_input": {"file_path": "/x/.env"}, "cwd": "/x"})
    assert w["action"] == "edit_file" and w["reversible"] is False
    m = cc.to_request({"tool_name": "mcp__stripe__create_refund", "tool_input": {"amount": 5}, "cwd": "/x"})
    assert m["action"] == "create_refund" and m["target"]["type"] == "mcp:stripe"


def test_hook_low_risk_uses_native_prompt_and_post_records(yr, tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "STATE_DIR", tmp_path / "pending")
    out = cc.pre_tool_use(bash_event("ls -la", "toolu_low"), yr)
    assert out == ""  # native prompt
    assert (tmp_path / "pending" / "toolu_low").exists()
    cc.post_tool_use({"tool_use_id": "toolu_low"}, yr)
    assert not (tmp_path / "pending" / "toolu_low").exists()
    approved = yr._call("GET", "/v1/requests", params={"status": "approved"})
    assert len(approved) == 1  # local approval became training data


def test_hook_high_risk_waits_then_times_out_to_native(yr, tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "STATE_DIR", tmp_path / "pending")
    out = cc.pre_tool_use(bash_event("npm publish"), yr, wait_s=0)
    assert out == ""  # no answer in time → native prompt, never silent allow


def test_hook_high_risk_remote_deny(yr, monkeypatch):
    real_wait = yr.wait

    def wait_and_deny(rid, timeout=0, **kw):
        yr._call("POST", f"/v1/requests/{rid}/decision", json={"approved": False, "by": "phone"})
        return real_wait(rid, timeout=0)

    monkeypatch.setattr(yr, "wait", wait_and_deny)
    out = json.loads(cc.pre_tool_use(bash_event("rm -rf /var/www"), yr))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hook_remote_approve(yr, monkeypatch):
    real_wait = yr.wait

    def wait_and_ok(rid, timeout=0, **kw):
        yr._call("POST", f"/v1/requests/{rid}/decision", json={"approved": True, "by": "phone"})
        return real_wait(rid, timeout=0)

    monkeypatch.setattr(yr, "wait", wait_and_ok)
    out = json.loads(cc.pre_tool_use(bash_event("terraform destroy"), yr))
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_hook_engine_down_falls_back():
    def boom(req):
        raise httpx.ConnectError("refused")

    yr = Yesrule("http://nowhere", client=httpx.Client(transport=httpx.MockTransport(boom)))
    assert cc.pre_tool_use(bash_event("rm -rf /"), yr) == ""


def test_installer_adds_removes_and_keeps_other_hooks():
    mine = {"type": "command", "command": "my-linter"}
    settings = {"model": "opus", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [mine]}]}}
    new = cc.install(settings)
    pre = new["hooks"]["PreToolUse"]
    assert pre[0]["hooks"] == [mine] and "yesrule hook pre" in pre[1]["hooks"][0]["command"]
    assert "yesrule hook post" in new["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
    again = cc.install(new)
    assert len(again["hooks"]["PreToolUse"]) == 2  # idempotent
    removed = cc.install(again, remove=True)
    assert removed == settings
    assert cc.install({}, remove=True) == {}


def test_cli_install_dry_run_and_real(tmp_path, monkeypatch, capsys):
    from yesrule import cli

    monkeypatch.setattr(cc, "settings_path", lambda scope, cwd=None: tmp_path / ".claude" / "settings.json")
    assert cli.main(["install", "claude-code", "--dry-run", "--command", "yesrule"]) == 0
    assert not (tmp_path / ".claude" / "settings.json").exists()
    assert cli.main(["install", "claude-code", "--command", "yesrule"]) == 0
    data = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "PreToolUse" in data["hooks"]
    assert cli.main(["install", "claude-code", "--remove", "--command", "yesrule"]) == 0
    assert json.loads((tmp_path / ".claude" / "settings.json").read_text()) == {}


def test_sdk_require_and_guard(yr, monkeypatch):
    with pytest.raises(Denied):
        yr.require("send_email", timeout=0, **{k: v for k, v in invoice().items() if k not in {"agent", "platform", "action"}})

    calls = []

    @yr.guard(action="refund", timeout=0, amount=lambda order_id, value: value, reversible=False)
    def refund(order_id: str, value: float):
        calls.append(order_id)

    with pytest.raises(Denied):
        refund("o-1", 900)  # nobody approved in time
    assert calls == []


def test_sdk_unavailable():
    def boom(req):
        raise httpx.ConnectError("x")

    yr = Yesrule("http://x", client=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(Unavailable):
        yr.submit("a")


def test_importer_generic_and_n8n(tmp_path):
    from yesrule.db import make_session_factory
    from yesrule.service import human_history

    generic = [{"action": "send_email", "approved": True, "decided_at": "2026-10-01T10:00:00Z", "amount": 10,
                "recipient": "a@b.c", "recipient_known": True, "client": "acme"}]
    n8n = {"data": [{"workflowData": {"name": "Invoices"}, "stoppedAt": "2026-10-02T10:00:00Z",
                     "data": {"resultData": {"runData": {
                         "Send and Wait for Approval": [{"data": {"main": [[{"json": {"data": {"approved": False}}}]]}}],
                         "HTTP Request": [{"data": {"main": [[{"json": {"approved": True}}]]}}]}}}}]}
    items = detect_and_parse(generic) + detect_and_parse(n8n)
    assert len(items) == 2 and items[1]["approved"] is False and items[1]["agent"] == "Invoices"
    with pytest.raises(TypeError):
        detect_and_parse("nope")
    s = make_session_factory(f"sqlite:///{tmp_path}/i.db")()
    assert import_decisions(s, items) == 2
    assert sorted(d.approved for d in human_history(s)) == [False, True]


def test_demo_seed_produces_rules(tmp_path):
    from yesrule.db import make_session_factory
    from yesrule.demo import seed
    from yesrule.service import propose_rules

    s = make_session_factory(f"sqlite:///{tmp_path}/d.db")()
    assert seed(s) > 60
    rules = propose_rules(s)
    assert rules, "30 days of clean invoice approvals should produce at least one proposal"
    assert all(r.status == "proposed" for r in rules)
    assert not any("outreach" in r.description or "lead" in str(r.conditions) for r in rules)


def test_mcp_server_tools(yr):
    import asyncio

    from yesrule.adapters.mcp_server import build

    server = build(yr)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"request_approval", "check_approval", "list_pending", "explain_rules"}
    result = asyncio.run(server.call_tool("request_approval", {"action": "deploy", "summary": "ship v2",
                                                               "reversible": False, "environment": "production",
                                                               "wait_seconds": 0}))
    assert "pending" in str(result) or "expired" in str(result)
