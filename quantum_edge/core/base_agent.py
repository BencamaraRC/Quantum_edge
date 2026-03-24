"""Abstract base class for all 7 trading agents."""

from __future__ import annotations

import asyncio
import logging
import signal
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from quantum_edge.core.config import settings
from quantum_edge.core.context_store import ContextStore
from quantum_edge.core.message_bus import STREAMS, MessageBus
from quantum_edge.models.events import PipelineEvent, PipelineEventType

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Base class providing consume loop, heartbeat, context access, and graceful shutdown."""

    agent_id: str  # e.g. "agent_01"
    agent_name: str  # e.g. "news_scanner"
    consumer_group: str  # e.g. "cg:agent_01_news_scanner"
    subscribe_streams: list[str]  # streams this agent reads from
    cycle_seconds: float = 30.0  # how often the agent runs its cycle

    def __init__(self) -> None:
        self.bus = MessageBus()
        self.context = ContextStore()
        self._running = False
        self._tasks: list[asyncio.Task[Any]] = []
        self._processed_keys: set[str] = set()
        self._consecutive_cycle_failures: int = 0

    @property
    def health_status(self) -> str:
        """Return health status based on consecutive cycle failures."""
        if self._consecutive_cycle_failures <= 1:
            return "active"
        elif self._consecutive_cycle_failures <= 4:
            return "degraded"
        else:
            return "failing"

    async def start(self) -> None:
        """Initialize connections and start the agent loop."""
        await self.bus.connect()
        self.context._redis = self.bus.redis

        # Set up consumer groups for all subscribed streams
        for stream in self.subscribe_streams:
            await self.bus.ensure_consumer_group(stream, self.consumer_group)

        await self.on_start()
        self._running = True

        # Register signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        # Launch concurrent tasks
        self._tasks = [
            asyncio.create_task(self._heartbeat_loop()),
            asyncio.create_task(self._consume_loop()),
            asyncio.create_task(self._cycle_loop()),
        ]

        logger.info("%s started", self.agent_name)
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def stop(self) -> None:
        """Graceful shutdown."""
        logger.info("%s stopping...", self.agent_name)
        self._running = False
        for task in self._tasks:
            task.cancel()
        await self.on_stop()
        await self.bus.disconnect()
        logger.info("%s stopped", self.agent_name)

    # ─── Abstract methods for subclass implementation ───

    @abstractmethod
    async def on_start(self) -> None:
        """Called once on startup. Load models, warm caches, etc."""

    @abstractmethod
    async def on_stop(self) -> None:
        """Called on shutdown. Cleanup resources."""

    @abstractmethod
    async def on_cycle(self) -> None:
        """Called every cycle_seconds. Main agent work loop."""

    @abstractmethod
    async def on_message(self, stream: str, msg_id: str, data: dict[str, str]) -> None:
        """Called when a message arrives on a subscribed stream."""

    # ─── Helpers ───

    def is_duplicate(self, idempotency_key: str) -> bool:
        """Check if we've already processed this key."""
        if idempotency_key in self._processed_keys:
            return True
        self._processed_keys.add(idempotency_key)
        # Keep set bounded
        if len(self._processed_keys) > 50000:
            # Remove oldest half
            to_remove = list(self._processed_keys)[:25000]
            self._processed_keys -= set(to_remove)
        return False

    async def publish_signal(self, stream: str, data: dict[str, str]) -> str:
        """Publish a signal to a stream."""
        return await self.bus.publish(stream, data)

    async def publish_event(self, event: PipelineEvent) -> str:
        """Publish a pipeline event."""
        return await self.bus.publish(STREAMS["phase"], event.to_stream_dict())

    async def get_context(self, domain: str) -> dict[str, Any]:
        """Read current context for a domain."""
        return await self.context.get(domain)

    async def update_context(self, domain: str, data: dict[str, Any]) -> None:
        """Update context (dual-write Hash + Stream)."""
        await self.context.update(domain, data, self.agent_id)

    # ─── Internal loops ───

    async def _heartbeat_loop(self) -> None:
        """Publish heartbeat every 30 seconds."""
        while self._running:
            try:
                await self.bus.publish(
                    STREAMS["heartbeat"],
                    {
                        "agent_id": self.agent_id,
                        "agent_name": self.agent_name,
                        "status": self.health_status,
                        "consecutive_failures": str(self._consecutive_cycle_failures),
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )
            except Exception:
                logger.exception("Heartbeat publish failed")
            await asyncio.sleep(30)

    async def _consume_loop(self) -> None:
        """Consume messages from subscribed streams."""
        if not self.subscribe_streams:
            return

        streams_map = {s: ">" for s in self.subscribe_streams}
        while self._running:
            try:
                messages = await self.bus.consume(
                    streams_map,
                    self.consumer_group,
                    self.agent_id,
                    count=10,
                    block_ms=2000,
                )
                for stream, msg_id, data in messages:
                    try:
                        await self.on_message(stream, msg_id, data)
                        await self.bus.ack(stream, self.consumer_group, msg_id)
                    except Exception:
                        logger.exception(
                            "Error handling message on %s:%s",
                            stream,
                            msg_id,
                        )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Consume loop error")
                await asyncio.sleep(1)

    async def _cycle_loop(self) -> None:
        """Run on_cycle at the configured interval."""
        while self._running:
            try:
                await self.on_cycle()
                self._consecutive_cycle_failures = 0
            except asyncio.CancelledError:
                break
            except Exception:
                self._consecutive_cycle_failures += 1
                logger.exception(
                    "Cycle error in %s (consecutive failures: %d, health: %s)",
                    self.agent_name,
                    self._consecutive_cycle_failures,
                    self.health_status,
                )
            await asyncio.sleep(self.cycle_seconds)
