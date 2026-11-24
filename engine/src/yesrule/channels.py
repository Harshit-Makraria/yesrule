"""Send approval requests to people and read their button presses.

Telegram: sendMessage with inline buttons; button presses arrive at our webhook with a secret header.
Slack: chat.postMessage with Block Kit buttons; presses arrive signed with the app's signing secret.
All outbound text is redacted first. Network calls go through an injectable httpx client so tests fake them.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from yesrule.core.redact import redact
from yesrule.db import RequestRow

CALLBACK_PREFIX = "yr"


def summary_text(row: RequestRow) -> str:
    p = row.payload
    parts = [f"{p.get('agent')} · {p.get('platform')}", f"Action: {p.get('action')}"]
    if p.get("amount"):
        parts.append(f"Amount: {p['amount']['value']:,.0f} {p['amount']['currency']}")
    if p.get("recipient"):
        r = p["recipient"]
        parts.append(f"To: {r['id']} ({'known' if r.get('known') else 'NEW'})")
    if cmd := (p.get("context") or {}).get("command"):
        parts.append(f"Command: {str(cmd)[:300]}")
    if p.get("client"):
        parts.append(f"Client: {p['client']}")
    reasons = ", ".join(r[0] for r in row.risk_reasons) or "none"
    parts.append(f"Risk: {row.risk_score} ({row.risk_band}) — {reasons}")
    parts.append(f"Why asking: {row.verdict_reason}")
    return redact("\n".join(parts))


def callback_data(request_id: str, approved: bool) -> str:
    return f"{CALLBACK_PREFIX}:{'a' if approved else 'd'}:{request_id}"


def parse_callback(data: str) -> tuple[str, bool] | None:
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX or parts[1] not in {"a", "d"}:
        return None
    return parts[2], parts[1] == "a"


class Channel(Protocol):
    name: str

    def send(self, row: RequestRow) -> None: ...


@dataclass
class TelegramChannel:
    token: str
    chat_id: str
    secret: str  # sent by Telegram in X-Telegram-Bot-Api-Secret-Token
    http: httpx.Client | None = None
    name: str = "telegram"

    def _client(self) -> httpx.Client:
        return self.http or httpx.Client(timeout=10)

    def send(self, row: RequestRow) -> None:
        keyboard = {"inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": callback_data(row.id, True)},
            {"text": "❌ Deny", "callback_data": callback_data(row.id, False)},
        ]]}
        self._client().post(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            json={"chat_id": self.chat_id, "text": "🔐 Approval needed\n\n" + summary_text(row),
                  "reply_markup": keyboard},
        )

    def verify(self, header_secret: str | None) -> bool:
        return header_secret is not None and hmac.compare_digest(header_secret, self.secret)

    def answer(self, callback_query_id: str, text: str) -> None:
        self._client().post(f"https://api.telegram.org/bot{self.token}/answerCallbackQuery",
                            json={"callback_query_id": callback_query_id, "text": text})


@dataclass
class SlackChannel:
    bot_token: str
    channel: str
    signing_secret: str
    http: httpx.Client | None = None
    name: str = "slack"

    def send(self, row: RequestRow) -> None:
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "*Approval needed*\n" + summary_text(row)}},
            {"type": "actions", "elements": [
                {"type": "button", "style": "primary", "text": {"type": "plain_text", "text": "Approve"},
                 "action_id": "approve", "value": callback_data(row.id, True)},
                {"type": "button", "style": "danger", "text": {"type": "plain_text", "text": "Deny"},
                 "action_id": "deny", "value": callback_data(row.id, False)},
            ]},
        ]
        (self.http or httpx.Client(timeout=10)).post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {self.bot_token}"},
            json={"channel": self.channel, "text": "Approval needed", "blocks": blocks},
        )

    def verify(self, timestamp: str | None, body: bytes, signature: str | None, now: float | None = None) -> bool:
        """Slack request signing: v0=HMAC_SHA256(secret, 'v0:{ts}:{body}'), rejected if older than 5 minutes."""
        if not timestamp or not signature:
            return False
        try:
            if abs((now or time.time()) - int(timestamp)) > 300:
                return False
        except ValueError:
            return False
        base = f"v0:{timestamp}:".encode() + body
        expected = "v0=" + hmac.new(self.signing_secret.encode(), base, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def parse_action(payload_json: str) -> tuple[str, bool, str] | None:
        payload: dict[str, Any] = json.loads(payload_json)
        actions = payload.get("actions") or []
        if not actions:
            return None
        parsed = parse_callback(actions[0].get("value", ""))
        if parsed is None:
            return None
        user = (payload.get("user") or {}).get("username") or (payload.get("user") or {}).get("id", "slack-user")
        return parsed[0], parsed[1], user


def channels_from_env() -> list[Channel]:
    out: list[Channel] = []
    if os.environ.get("YESRULE_TELEGRAM_TOKEN") and os.environ.get("YESRULE_TELEGRAM_CHAT_ID"):
        out.append(TelegramChannel(os.environ["YESRULE_TELEGRAM_TOKEN"], os.environ["YESRULE_TELEGRAM_CHAT_ID"],
                                   os.environ.get("YESRULE_TELEGRAM_SECRET", "")))
    if os.environ.get("YESRULE_SLACK_BOT_TOKEN") and os.environ.get("YESRULE_SLACK_CHANNEL"):
        out.append(SlackChannel(os.environ["YESRULE_SLACK_BOT_TOKEN"], os.environ["YESRULE_SLACK_CHANNEL"],
                                os.environ.get("YESRULE_SLACK_SIGNING_SECRET", "")))
    return out
