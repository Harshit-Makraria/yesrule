import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from yesrule.api import create_app
from yesrule.channels import (
    SlackChannel,
    TelegramChannel,
    callback_data,
    parse_callback,
)
from yesrule.core.redact import redact

from .conftest import Recorder, invoice


def test_redact_removes_secrets():
    text = ("key sk-ant-api03-abcdefghijklmnop and ghp_abcdefghijklmnopqrstuvwxyz12 card 4111 1111 1111 1111 "
            "password=hunter2 AKIAABCDEFGHIJKLMNOP")
    out = redact(text)
    for secret in ("sk-ant-api03", "ghp_abc", "4111 1111", "hunter2", "AKIAABCDEFGHIJKLMNOP"):
        assert secret not in out


def test_callback_roundtrip_and_garbage():
    assert parse_callback(callback_data("req_1", True)) == ("req_1", True)
    assert parse_callback(callback_data("req_1", False)) == ("req_1", False)
    for bad in ("", "yr:x:req", "zz:a:req", "yr:a", "yr:a:b:c"):
        assert parse_callback(bad) is None


def test_telegram_flow_end_to_end(tmp_path):
    rec = Recorder()
    tg = TelegramChannel("TOKEN", "42", "s3cret", http=rec.client())
    c = TestClient(create_app(f"sqlite:///{tmp_path}/t.db", channels=[tg]))
    body = invoice(context={"command": "deploy with token=abc123secret"})
    rid = c.post("/v1/requests", json=body).json()["id"]

    sent = json.loads(rec.calls[0].content)
    assert "sendMessage" in str(rec.calls[0].url) and sent["chat_id"] == "42"
    assert "abc123secret" not in sent["text"]  # redacted before leaving the server
    buttons = sent["reply_markup"]["inline_keyboard"][0]
    assert buttons[0]["callback_data"] == f"yr:a:{rid}"

    update = {"callback_query": {"id": "cb1", "data": f"yr:a:{rid}", "from": {"username": "harshit"}}}
    assert c.post("/v1/channels/telegram/webhook", json=update).status_code == 401  # no secret
    r = c.post("/v1/channels/telegram/webhook", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"})
    assert r.status_code == 200
    assert c.get(f"/v1/requests/{rid}").json()["status"] == "approved"
    detail = c.get(f"/v1/requests/{rid}/detail").json()
    assert detail["decisions"][0]["by"] == "harshit" and detail["decisions"][0]["channel"] == "telegram"


def test_auto_approved_requests_are_not_sent(tmp_path):
    rec = Recorder()
    tg = TelegramChannel("T", "1", "s", http=rec.client())
    c = TestClient(create_app(f"sqlite:///{tmp_path}/t.db", channels=[tg]))
    c.post("/v1/hard-lines", json={"id": "H-0", "conditions": [{"field": "action", "op": "eq", "value": "nope"}]})
    c.post("/v1/requests", json=invoice())
    assert len(rec.calls) == 1  # pending → sent


def test_broken_channel_does_not_break_request(tmp_path):
    class Boom:
        name = "boom"

        def send(self, row):
            raise RuntimeError("network down")

    c = TestClient(create_app(f"sqlite:///{tmp_path}/t.db", channels=[Boom()]))
    assert c.post("/v1/requests", json=invoice()).status_code == 201


def _slack_sig(secret: str, ts: str, body: bytes) -> str:
    return "v0=" + hmac.new(secret.encode(), f"v0:{ts}:".encode() + body, hashlib.sha256).hexdigest()


def test_slack_signature_rules():
    sl = SlackChannel("xoxb", "C1", "sign")
    ts = str(int(time.time()))
    body = b"payload=x"
    assert sl.verify(ts, body, _slack_sig("sign", ts, body))
    assert not sl.verify(ts, body, _slack_sig("wrong", ts, body))
    assert not sl.verify(ts, b"payload=y", _slack_sig("sign", ts, body))  # body changed
    old = str(int(time.time()) - 600)
    assert not sl.verify(old, body, _slack_sig("sign", old, body))  # replay
    assert not sl.verify(None, body, "v0=x")
    assert not sl.verify("abc", body, "v0=x")


def test_slack_flow_end_to_end(tmp_path):
    rec = Recorder()
    sl = SlackChannel("xoxb-1", "C1", "sign", http=rec.client())
    c = TestClient(create_app(f"sqlite:///{tmp_path}/t.db", channels=[sl]))
    rid = c.post("/v1/requests", json=invoice()).json()["id"]
    assert "chat.postMessage" in str(rec.calls[0].url)

    payload = json.dumps({"actions": [{"value": f"yr:d:{rid}"}], "user": {"username": "priya"}})
    body = urlencode({"payload": payload}).encode()
    ts = str(int(time.time()))
    headers = {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": _slack_sig("sign", ts, body),
               "Content-Type": "application/x-www-form-urlencoded"}
    r = c.post("/v1/channels/slack/actions", content=body, headers=headers)
    assert r.status_code == 200 and "denied" in r.json()["text"]
    assert c.get(f"/v1/requests/{rid}").json()["status"] == "denied"
    bad = headers | {"X-Slack-Signature": "v0=forged"}
    assert c.post("/v1/channels/slack/actions", content=body, headers=bad).status_code == 401
