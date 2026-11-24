"""Tamper-evident audit log: each entry stores the hash of the previous one."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

GENESIS = "0" * 64


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    event: str
    data: dict[str, Any]
    created_at: str
    prev_hash: str
    hash: str


def entry_hash(seq: int, event: str, data: dict[str, Any], created_at: str, prev_hash: str) -> str:
    payload = json.dumps(
        {"seq": seq, "event": event, "data": data, "created_at": created_at, "prev": prev_hash},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def make_entry(prev: AuditEntry | None, event: str, data: dict[str, Any], created_at: str) -> AuditEntry:
    seq = 1 if prev is None else prev.seq + 1
    prev_hash = GENESIS if prev is None else prev.hash
    return AuditEntry(seq, event, data, created_at, prev_hash, entry_hash(seq, event, data, created_at, prev_hash))


def verify(entries: list[AuditEntry]) -> tuple[bool, int | None]:
    """Return (ok, first_bad_seq). Detects edits, deletions and reordering."""
    prev_hash = GENESIS
    expected_seq = 1
    for e in entries:
        if e.seq != expected_seq or e.prev_hash != prev_hash:
            return False, e.seq
        if entry_hash(e.seq, e.event, e.data, e.created_at, e.prev_hash) != e.hash:
            return False, e.seq
        prev_hash, expected_seq = e.hash, expected_seq + 1
    return True, None
