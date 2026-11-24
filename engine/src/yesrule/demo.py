"""Seed a realistic demo: an agency running agents for three clients over the last 30 days."""

from __future__ import annotations

import random
from datetime import timedelta

from sqlalchemy.orm import Session

from yesrule.db import utcnow
from yesrule.importer import import_decisions

CLIENTS = {"acme-dental": 1_800, "brightpath-legal": 45_000, "nova-gyms": 3_500}


def demo_items(days: int = 30, seed: int = 7) -> list[dict]:
    rnd = random.Random(seed)
    now = utcnow()
    items: list[dict] = []
    for d in range(days, 0, -1):
        day = now - timedelta(days=d)
        for client, typical in CLIENTS.items():
            for _ in range(rnd.randint(1, 3)):  # invoices to known clients: always approved
                items.append({"agent": "invoice-bot", "platform": "n8n", "action": "send_email",
                              "target_type": "invoice", "amount": round(typical * rnd.uniform(0.6, 1.0)),
                              "recipient": f"billing@{client}.com", "recipient_known": True,
                              "reversible": False, "environment": "production", "client": client,
                              "approved": True, "decided_at": (day + timedelta(hours=rnd.randint(9, 18))).isoformat(),
                              "by": "owner"})
        if rnd.random() < 0.6:  # small refunds from the voice agent
            items.append({"agent": "support-voice", "platform": "retell", "action": "refund",
                          "target_type": "order", "amount": rnd.randint(200, 1_400), "recipient": "customer",
                          "recipient_known": True, "reversible": False, "environment": "production",
                          "client": "nova-gyms", "approved": True,
                          "decided_at": (day + timedelta(hours=rnd.randint(9, 20))).isoformat(), "by": "owner"})
        if rnd.random() < 0.25:  # cold outreach to new people: usually denied
            items.append({"agent": "outreach-bot", "platform": "n8n", "action": "send_email",
                          "target_type": "lead", "recipient": f"lead{d}@unknown.io", "recipient_known": False,
                          "reversible": False, "environment": "production", "client": "brightpath-legal",
                          "approved": rnd.random() < 0.3,
                          "decided_at": (day + timedelta(hours=11)).isoformat(), "by": "owner"})
    return items


def seed(db: Session) -> int:
    return import_decisions(db, demo_items())
