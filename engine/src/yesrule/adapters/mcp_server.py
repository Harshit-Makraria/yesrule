"""MCP server: any MCP client (Claude Desktop, Cursor, Codex, custom agents) can ask for approval.

Run:  yesrule mcp            (stdio)
Tools: request_approval (blocks until decided), check_approval, list_pending, explain_rule.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from yesrule.sdk import Unavailable, Yesrule


def build(yr: Yesrule | None = None) -> MCPServer:
    yr = yr or Yesrule(agent="mcp-agent", platform="mcp")
    server = MCPServer("yesrule", instructions=(
        "Before any irreversible, external, financial or destructive action, call request_approval and only "
        "continue if the result says approved. Never retry a denied action with different wording."))

    @server.tool(description="Ask a human (or a learned rule) to approve an action. Blocks until decided.")
    def request_approval(action: str, summary: str, target_type: str = "unknown", target_id: str | None = None,
                         amount: float | None = None, currency: str = "INR", recipient: str | None = None,
                         recipient_known: bool = False, reversible: bool = True, environment: str = "unknown",
                         client: str | None = None, wait_seconds: int = 300) -> dict[str, Any]:
        fields: dict[str, Any] = {"target": {"type": target_type, "id": target_id}, "reversible": reversible,
                                  "environment": environment, "client": client, "context": {"summary": summary},
                                  "timeout_s": max(5, wait_seconds)}
        if amount is not None:
            fields["amount"] = {"value": amount, "currency": currency}
        if recipient:
            fields["recipient"] = {"id": recipient, "known": recipient_known}
        try:
            d = yr.submit(action, **fields)
            if not d.final:
                d = yr.wait(d.id, timeout=wait_seconds)
        except Unavailable:
            return {"approved": False, "status": "unavailable",
                    "message": "Approval service unreachable. Do not proceed; ask the user directly."}
        return {"approved": d.approved, "status": d.status, "request_id": d.id, "risk": d.risk_score,
                "reason": d.reason, "receipt": d.receipt}

    @server.tool(description="Check the status of an approval request.")
    def check_approval(request_id: str) -> dict[str, Any]:
        d = yr.status(request_id)
        return {"approved": d.approved, "status": d.status, "final": d.final, "reason": d.reason}

    @server.tool(description="List approval requests still waiting for a person.")
    def list_pending() -> list[dict[str, Any]]:
        return yr._call("GET", "/v1/requests", params={"status": "pending"})  # type: ignore[return-value]

    @server.tool(description="Show the rules Yesrule has learned and their evidence.")
    def explain_rules() -> list[dict[str, Any]]:
        return yr._call("GET", "/v1/rules")  # type: ignore[return-value]

    return server


def main() -> None:
    build().run("stdio")
