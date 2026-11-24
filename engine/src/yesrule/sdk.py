"""Python SDK: put an approval step in front of any function your agent calls.

    from yesrule.sdk import Yesrule
    yr = Yesrule("http://localhost:8787", agent="billing-bot")

    @yr.guard(action="refund", amount=lambda order_id, value: value)
    def refund(order_id: str, value: float): ...

    refund("o-1", 900)   # blocks until approved; raises Denied otherwise
"""

from __future__ import annotations

import functools
import inspect
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

FINAL = {"approved", "auto_approved", "denied", "auto_denied", "expired", "flagged"}


class Denied(Exception):
    def __init__(self, decision: Decision):
        super().__init__(f"{decision.status}: {decision.reason}")
        self.decision = decision


class Unavailable(Exception):
    """The Yesrule server could not be reached."""


@dataclass
class Decision:
    id: str
    status: str
    reason: str
    risk_score: int
    risk_band: str
    receipt: dict[str, Any] | None

    @property
    def approved(self) -> bool:
        return self.status in {"approved", "auto_approved"}

    @property
    def final(self) -> bool:
        return self.status in FINAL

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Decision:
        return cls(d["id"], d["status"], d.get("reason", ""), d.get("risk_score", 0), d.get("risk_band", ""),
                   d.get("receipt"))


class Yesrule:
    def __init__(self, base_url: str | None = None, *, agent: str = "sdk", platform: str = "sdk",
                 client: httpx.Client | None = None, poll_interval: float = 1.0):
        self.base_url = (base_url or os.environ.get("YESRULE_URL", "http://localhost:8787")).rstrip("/")
        self.agent, self.platform, self.poll_interval = agent, platform, poll_interval
        self.http = client or httpx.Client(timeout=10)

    def _call(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        try:
            r = self.http.request(method, self.base_url + path, **kw)
        except httpx.HTTPError as e:
            raise Unavailable(str(e)) from e
        r.raise_for_status()
        return r.json()

    def submit(self, action: str, **fields: Any) -> Decision:
        body = {"agent": self.agent, "platform": self.platform, "action": action} | fields
        return Decision.from_json(self._call("POST", "/v1/requests", json=body))

    def status(self, request_id: str) -> Decision:
        return Decision.from_json(self._call("GET", f"/v1/requests/{request_id}"))

    def wait(self, request_id: str, timeout: float = 600, sleep: Callable[[float], None] = time.sleep) -> Decision:
        deadline = time.monotonic() + timeout
        while True:
            d = self.status(request_id)
            if d.final or time.monotonic() >= deadline:
                return d
            sleep(self.poll_interval)

    def require(self, action: str, *, timeout: float | None = None, **fields: Any) -> Decision:
        """Submit and block until a final answer. Raises Denied unless approved."""
        d = self.submit(action, **fields)
        if not d.final:
            d = self.wait(d.id, timeout if timeout is not None else fields.get("timeout_s", 600))
        if not d.approved:
            raise Denied(d)
        return d

    def guard(self, action: str, *, timeout: float | None = None, **field_fns: Any) -> Callable:
        """Decorator. Each keyword is a value or a function of the wrapped call's arguments."""

        def wrap(fn: Callable) -> Callable:
            sig = inspect.signature(fn)

            @functools.wraps(fn)
            def inner(*args: Any, **kwargs: Any) -> Any:
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                fields: dict[str, Any] = {}
                for key, v in field_fns.items():
                    val = v(**bound.arguments) if callable(v) else v
                    if key == "amount" and isinstance(val, int | float):
                        val = {"value": val}
                    fields[key] = val
                fields.setdefault("context", {"function": fn.__name__,
                                              "args": {k: repr(v)[:200] for k, v in bound.arguments.items()}})
                self.require(action, timeout=timeout, **fields)
                return fn(*args, **kwargs)

            return inner

        return wrap
