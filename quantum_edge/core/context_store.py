"""Context Layer — dual-write pattern (Redis Hash + Stream).

Agents share interpreted context (regime, volatility, macro, calendar, portfolio)
via this layer. Every update atomically writes to both:
  A. Redis Hash (qe:state:{domain}) — point-in-time reads (sub-ms)
  B. Redis Stream (qe:context:{domain}) — change notifications (reactive)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import orjson
import redis.asyncio as aioredis

from quantum_edge.core.config import settings
from quantum_edge.models.memo import ContextSnapshot

logger = logging.getLogger(__name__)

STATE_KEY_PREFIX = "qe:state:"
CONTEXT_STREAM_PREFIX = "qe:context:"


class ContextStore:
    """Dual-write context layer for cross-agent knowledge sharing."""

    def __init__(self, redis_client: aioredis.Redis | None = None) -> None:
        self._redis = redis_client

    async def connect(self) -> None:
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                max_connections=20,
            )

    @property
    def redis(self) -> aioredis.Redis:
        if self._redis is None:
            raise RuntimeError("ContextStore not connected.")
        return self._redis

    async def update(
        self,
        domain: str,
        data: dict[str, Any],
        agent_id: str,
    ) -> None:
        """Atomically write context to Hash + Stream in a pipeline."""
        hash_key = f"{STATE_KEY_PREFIX}{domain}"
        stream_key = f"{CONTEXT_STREAM_PREFIX}{domain}"

        # Flatten complex values to JSON strings for Hash storage
        flat_data: dict[str, str] = {}
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                flat_data[k] = orjson.dumps(v).decode()
            elif isinstance(v, datetime):
                flat_data[k] = v.isoformat()
            else:
                flat_data[k] = str(v)

        flat_data["_updated_by"] = agent_id
        flat_data["_updated_at"] = datetime.utcnow().isoformat()

        # Atomic pipeline: Hash SET + Stream XADD
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.hset(hash_key, mapping=flat_data)
            pipe.xadd(
                stream_key,
                {
                    "agent_id": agent_id,
                    "domain": domain,
                    "data": orjson.dumps(data).decode(),
                    "timestamp": datetime.utcnow().isoformat(),
                },
                maxlen=5000,
                approximate=True,
            )
            await pipe.execute()

        logger.debug("Context updated: %s by %s", domain, agent_id)

    async def get(self, domain: str) -> dict[str, Any]:
        """Read current state for a domain from Redis Hash."""
        hash_key = f"{STATE_KEY_PREFIX}{domain}"
        raw = await self.redis.hgetall(hash_key)
        if not raw:
            return {}

        result: dict[str, Any] = {}
        for k, v in raw.items():
            if k.startswith("_"):
                result[k] = v
                continue
            # Try to parse JSON values
            try:
                result[k] = orjson.loads(v)
            except (orjson.JSONDecodeError, ValueError):
                result[k] = v
        return result

    async def get_multi(self, domains: list[str]) -> dict[str, dict[str, Any]]:
        """Read multiple domains in a single pipeline."""
        async with self.redis.pipeline(transaction=False) as pipe:
            for domain in domains:
                pipe.hgetall(f"{STATE_KEY_PREFIX}{domain}")
            results = await pipe.execute()

        output: dict[str, dict[str, Any]] = {}
        for domain, raw in zip(domains, results):
            if not raw:
                output[domain] = {}
                continue
            parsed: dict[str, Any] = {}
            for k, v in raw.items():
                if k.startswith("_"):
                    parsed[k] = v
                    continue
                try:
                    parsed[k] = orjson.loads(v)
                except (orjson.JSONDecodeError, ValueError):
                    parsed[k] = v
            output[domain] = parsed
        return output

    async def snapshot(self) -> ContextSnapshot:
        """Capture a frozen context snapshot for memo assembly."""
        domains = ["regime", "volatility", "macro", "calendar", "portfolio"]
        data = await self.get_multi(domains)
        return ContextSnapshot(
            regime=data.get("regime", {}),
            volatility=data.get("volatility", {}),
            macro=data.get("macro", {}),
            calendar=data.get("calendar", {}),
            portfolio=data.get("portfolio", {}),
            captured_at=datetime.utcnow(),
        )

    async def delete(self, domain: str) -> None:
        """Remove a domain's state (used in testing)."""
        await self.redis.delete(f"{STATE_KEY_PREFIX}{domain}")
