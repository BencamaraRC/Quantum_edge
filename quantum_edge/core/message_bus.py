"""Redis Streams message bus — publish/subscribe with consumer groups."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine

import redis.asyncio as aioredis

from quantum_edge.core.config import settings

logger = logging.getLogger(__name__)

# Stream name constants
STREAMS = {
    # Signal streams
    "news": "qe:signals:news",
    "market_data": "qe:signals:market_data",
    "events": "qe:signals:events",
    "data_science": "qe:signals:data_science",
    "smart_money": "qe:signals:smart_money",
    "technicals": "qe:signals:technicals",
    "risk": "qe:signals:risk",
    "position_monitor": "qe:signals:position_monitor",
    # Context streams
    "ctx_regime": "qe:context:regime",
    "ctx_volatility": "qe:context:volatility",
    "ctx_macro": "qe:context:macro",
    "ctx_calendar": "qe:context:calendar",
    "ctx_portfolio": "qe:context:portfolio",
    # Pipeline control
    "phase": "qe:pipeline:phase",
    "memo": "qe:pipeline:memo",
    "decision": "qe:pipeline:decision",
    "execution": "qe:pipeline:execution",
    # System
    "heartbeat": "qe:system:heartbeat",
    "errors": "qe:system:errors",
    "audit": "qe:system:audit",
}


class MessageBus:
    """Redis Streams wrapper for event-driven agent communication."""

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url or settings.redis_url
        self._redis: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._redis = aioredis.from_url(
            self._redis_url,
            decode_responses=True,
            max_connections=20,
        )
        await self._redis.ping()
        logger.info("MessageBus connected to Redis")

    async def disconnect(self) -> None:
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    @property
    def redis(self) -> aioredis.Redis:
        if self._redis is None:
            raise RuntimeError("MessageBus not connected. Call connect() first.")
        return self._redis

    async def publish(self, stream: str, data: dict[str, str], max_len: int = 10000) -> str:
        """Publish a message to a Redis Stream. Returns the message ID."""
        msg_id: str = await self.redis.xadd(stream, data, maxlen=max_len, approximate=True)
        return msg_id

    async def ensure_consumer_group(self, stream: str, group: str) -> None:
        """Create consumer group if it doesn't exist."""
        try:
            await self.redis.xgroup_create(stream, group, id="0", mkstream=True)
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def consume(
        self,
        streams: dict[str, str],
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[tuple[str, str, dict[str, str]]]:
        """Read messages from streams via consumer group.

        Returns list of (stream_name, message_id, data) tuples.
        """
        results: list[tuple[str, str, dict[str, str]]] = []
        try:
            response = await self.redis.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams=streams,
                count=count,
                block=block_ms,
            )
            if response:
                for stream_name, messages in response:
                    for msg_id, data in messages:
                        results.append((stream_name, msg_id, data))
        except aioredis.ResponseError as e:
            if "NOGROUP" in str(e):
                # Auto-create groups on first read
                for stream_name in streams:
                    await self.ensure_consumer_group(stream_name, group)
            else:
                raise
        return results

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        """Acknowledge a message has been processed."""
        await self.redis.xack(stream, group, message_id)

    async def consume_loop(
        self,
        streams: dict[str, str],
        group: str,
        consumer: str,
        handler: Callable[[str, str, dict[str, str]], Coroutine[Any, Any, None]],
        count: int = 10,
        block_ms: int = 5000,
    ) -> None:
        """Continuously consume and process messages."""
        # Ensure all consumer groups exist
        for stream_name in streams:
            await self.ensure_consumer_group(stream_name, group)

        while True:
            try:
                messages = await self.consume(streams, group, consumer, count, block_ms)
                for stream_name, msg_id, data in messages:
                    try:
                        await handler(stream_name, msg_id, data)
                        await self.ack(stream_name, group, msg_id)
                    except Exception:
                        logger.exception(
                            "Error processing message",
                            extra={"stream": stream_name, "msg_id": msg_id},
                        )
                        # Publish to error stream
                        await self.publish(
                            STREAMS["errors"],
                            {
                                "source_stream": stream_name,
                                "msg_id": msg_id,
                                "consumer": consumer,
                                "error": "processing_failed",
                            },
                        )
            except asyncio.CancelledError:
                logger.info("Consume loop cancelled for %s", consumer)
                break
            except Exception:
                logger.exception("Consume loop error for %s", consumer)
                await asyncio.sleep(1)
