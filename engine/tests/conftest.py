import httpx
import pytest
from fastapi.testclient import TestClient

from yesrule.api import create_app


@pytest.fixture
def app_client(tmp_path):
    return TestClient(create_app(f"sqlite:///{tmp_path}/t.db", channels=[]))


def invoice(amount: float = 42_000, **over) -> dict:
    return {
        "agent": "invoice-bot", "platform": "n8n", "action": "send_email", "target": {"type": "invoice"},
        "amount": {"value": amount, "currency": "INR"},
        "recipient": {"id": "acme@client.com", "known": True, "past_count": 11},
        "reversible": False, "environment": "production", "client": "acme",
    } | over


class Recorder:
    """Fake httpx transport that records outbound calls."""

    def __init__(self):
        self.calls: list[httpx.Request] = []

    def client(self) -> httpx.Client:
        def handler(req: httpx.Request) -> httpx.Response:
            self.calls.append(req)
            return httpx.Response(200, json={"ok": True})
        return httpx.Client(transport=httpx.MockTransport(handler))
