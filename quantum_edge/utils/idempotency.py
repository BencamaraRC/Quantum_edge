"""Idempotency key management for exactly-once processing."""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID

import redis.asyncio as aioredis

IDEM_KEY_PREFIX = "qe:idem:"
IDEM_TTL_S = 86400  # 24 hours


def make_idempotency_key(agent_id: str, memo_id: UUID, pass_number: int, symbol: str) -> str:
    """Create a deterministic idempotency key for a signal."""
    raw = f"{agent_id}:{memo_id}:{pass_number}:{symbol}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def make_event_key(event_type: str, memo_id: UUID, agent_id: str) -> str:
    """Create a deterministic key for pipeline events."""
    raw = f"{event_type}:{memo_id}:{agent_id}:{datetime.utcnow().strftime('%Y%m%d')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


async def check_and_set(redis: aioredis.Redis, key: str, ttl: int = IDEM_TTL_S) -> bool:
    """Returns True if this key was already processed (duplicate). Sets it otherwise."""
    full_key = f"{IDEM_KEY_PREFIX}{key}"
    # SET NX returns True if key was set (new), None if already existed
    was_set = await redis.set(full_key, "1", nx=True, ex=ttl)
    return was_set is None  # True = duplicate (key existed)
