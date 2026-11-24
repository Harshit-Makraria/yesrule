"""Claude Code PreToolUse / PostToolUse hook.

PreToolUse reads the tool call from stdin and prints a permissionDecision:
  allow  - a rule or a person approved it
  deny   - a rule or a person denied it (the reason is shown to Claude)
  (no output) - Claude Code's own permission prompt runs as normal. Used when the engine is down
               (fail open to the native prompt, never silently allow) and, by default, for low-risk calls.
PostToolUse tells the engine that a call answered at the native prompt ran, so local approvals train rules too.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx

from yesrule.core.risk import DANGEROUS_SHELL
from yesrule.sdk import Unavailable, Yesrule

STATE_DIR = Path(os.environ.get("YESRULE_STATE_DIR", Path.home() / ".yesrule" / "pending"))
PROD_HINTS = re.compile(r"(?i)\b(prod|production|main|master|live)\b")


def to_request(event: dict[str, Any]) -> dict[str, Any]:
    tool = event.get("tool_name", "")
    tin: dict[str, Any] = event.get("tool_input") or {}
    cwd = event.get("cwd", "")
    req: dict[str, Any] = {
        "agent": "claude-code:" + (Path(cwd).name or "session"),
        "platform": "claude_code",
        "action": tool.lower(),
        "context": {"tool": tool, "cwd": cwd, "session_id": event.get("session_id"),
                    "tool_use_id": event.get("tool_use_id"), "permission_mode": event.get("permission_mode")},
        "client": Path(cwd).name or None,
    }
    if tool == "Bash":
        cmd = str(tin.get("command", ""))
        req["action"] = "bash"
        req["target"] = {"type": "shell", "id": cmd.split()[0] if cmd.split() else None}
        req["context"]["command"] = cmd
        dangerous = any(p in cmd.lower() for p in DANGEROUS_SHELL)
        req["reversible"] = not dangerous
        if PROD_HINTS.search(cmd):
            req["environment"] = "production"
    elif tool in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
        path = str(tin.get("file_path") or tin.get("notebook_path") or "")
        req["action"] = "edit_file"
        req["target"] = {"type": "file", "id": path}
        ext = Path(path).suffix or Path(path).name
        req["context"]["file_kind"] = ext
        if any(s in path for s in (".env", "secrets", ".github/workflows", "id_rsa")):
            req["reversible"] = False
    elif tool.startswith("mcp__"):
        parts = tool.split("__")
        req["action"] = parts[-1]
        req["target"] = {"type": "mcp:" + (parts[1] if len(parts) > 2 else "tool")}
        req["context"]["input"] = {k: str(v)[:200] for k, v in tin.items()}
    else:
        req["target"] = {"type": "tool"}
        req["context"]["input"] = {k: str(v)[:200] for k, v in tin.items()}
    return req


def _out(decision: str, reason: str) -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                              "permissionDecisionReason": reason}})


def pre_tool_use(event: dict[str, Any], yr: Yesrule, *, local_band: str = "low", wait_s: float = 290) -> str:
    """Return the stdout text for the hook ('' means: let Claude Code's own prompt handle it)."""
    try:
        d = yr.submit(**to_request(event) | {"timeout_s": int(wait_s) + 5})
    except (Unavailable, httpx.HTTPStatusError):
        return ""  # engine down or rejected the call: fall back to the native prompt
    if d.status == "auto_approved":
        rule = (d.receipt or {}).get("rule", "rule")
        return _out("allow", f"Yesrule: auto-approved by {rule} ({d.reason})")
    if d.status == "auto_denied":
        return _out("deny", f"Yesrule: denied by rule ({d.reason})")
    if d.risk_band == local_band or (local_band == "medium" and d.risk_band == "low"):
        tid = event.get("tool_use_id")
        if tid:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            (STATE_DIR / f"{tid}").write_text(d.id)
        return ""  # answer at the native prompt; PostToolUse records it if it ran
    try:
        d = yr.wait(d.id, timeout=wait_s)
    except Unavailable:
        return ""
    if d.approved:
        return _out("allow", f"Yesrule: approved remotely ({d.status})")
    if d.status == "denied":
        return _out("deny", "Yesrule: a person denied this action")
    return ""  # expired or still pending: hand back to the native prompt


def post_tool_use(event: dict[str, Any], yr: Yesrule) -> None:
    tid = event.get("tool_use_id")
    if not tid:
        return
    f = STATE_DIR / f"{tid}"
    if not f.exists():
        return
    request_id = f.read_text().strip()
    f.unlink(missing_ok=True)
    try:
        yr._call("POST", f"/v1/requests/{request_id}/decision",
                 json={"approved": True, "by": os.environ.get("USER", "local"), "channel": "claude-code-prompt"})
    except (Unavailable, httpx.HTTPStatusError):
        return  # already decided or engine down; the native prompt already handled it


def main(kind: str) -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    yr = Yesrule(agent="claude-code", platform="claude_code")
    if kind == "pre":
        text = pre_tool_use(event, yr, local_band=os.environ.get("YESRULE_LOCAL_BAND", "low"),
                            wait_s=float(os.environ.get("YESRULE_WAIT_S", "290")))
        if text:
            print(text)
    else:
        post_tool_use(event, yr)
    return 0


# --- installer ---------------------------------------------------------------

MATCHER = "Bash|Write|Edit|MultiEdit|NotebookEdit|WebFetch|mcp__.*"
MARK = "yesrule hook"


def settings_path(scope: str, cwd: Path | None = None) -> Path:
    if scope == "user":
        return Path.home() / ".claude" / "settings.json"
    return (cwd or Path.cwd()) / ".claude" / "settings.json"


def _strip(hooks: dict[str, Any]) -> dict[str, Any]:
    for event in ("PreToolUse", "PostToolUse"):
        groups = hooks.get(event, [])
        kept = []
        for g in groups:
            g = dict(g)
            g["hooks"] = [h for h in g.get("hooks", []) if MARK not in h.get("command", "")]
            if g["hooks"]:
                kept.append(g)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    return hooks


def install(settings: dict[str, Any], command: str = "yesrule", remove: bool = False) -> dict[str, Any]:
    """Pure: return new settings with Yesrule hooks added (or removed). Other hooks are left untouched."""
    new = json.loads(json.dumps(settings))
    hooks = _strip(new.get("hooks", {}))
    if not remove:
        hooks.setdefault("PreToolUse", []).append(
            {"matcher": MATCHER, "hooks": [{"type": "command", "command": f"{command} hook pre", "timeout": 300}]})
        hooks.setdefault("PostToolUse", []).append(
            {"matcher": MATCHER, "hooks": [{"type": "command", "command": f"{command} hook post", "timeout": 10}]})
    if hooks:
        new["hooks"] = hooks
    else:
        new.pop("hooks", None)
    return new
