"""Watchlist Scanner — monitors signal streams and triggers memo creation.

Uses the strategy universe (primary symbols + satellites). Triggers satellite
lag-window scanning when a primary anchor trade completes.

Strategy rules:
- Primary symbols (Mag 7 + Expanded) are independent watchlist candidates
- Satellite scanning activates 2-6 hours after a primary anchor trade
- Satellites get +0.05 prior boost but must independently clear 0.75
- Max 1 satellite per anchor event
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from quantum_edge.core.config import settings
from quantum_edge.core.context_store import ContextStore
from quantum_edge.core.memo_factory import MemoFactory
from quantum_edge.core.memo_store import MemoStore
from quantum_edge.core.message_bus import STREAMS, MessageBus
from quantum_edge.core.strategy import (
    FULL_UNIVERSE,
    MAX_SATELLITES_PER_ANCHOR,
    PRIMARY_SYMBOLS,
    SATELLITE_CLUSTERS,
    SATELLITE_LAG_WINDOW_HOURS,
    is_primary,
)

logger = logging.getLogger(__name__)

# Minimum signals before triggering a memo
MIN_SIGNAL_COUNT = 2
# Cooldown before re-triggering the same symbol
COOLDOWN_SECONDS = 300
# Signal decay window — only count signals within this window
SIGNAL_WINDOW_SECONDS = 300


class AnchorEvent:
    """Tracks a completed Mag 7 trade for satellite lag-window scanning."""

    def __init__(self, anchor_symbol: str, memo_id: UUID, completed_at: datetime) -> None:
        self.anchor_symbol = anchor_symbol
        self.memo_id = memo_id
        self.completed_at = completed_at
        self.satellites_triggered: int = 0

    def is_in_lag_window(self) -> bool:
        now = datetime.utcnow()
        elapsed = now - self.completed_at
        min_hours, max_hours = SATELLITE_LAG_WINDOW_HOURS
        return timedelta(hours=min_hours) <= elapsed <= timedelta(hours=max_hours)

    def is_expired(self) -> bool:
        elapsed = datetime.utcnow() - self.completed_at
        _, max_hours = SATELLITE_LAG_WINDOW_HOURS
        return elapsed > timedelta(hours=max_hours)

    def can_trigger_satellite(self) -> bool:
        return (
            self.is_in_lag_window()
            and self.satellites_triggered < MAX_SATELLITES_PER_ANCHOR
        )


class WatchlistScanner:
    """Scans signal streams for actionable symbols and creates memos."""

    def __init__(self) -> None:
        self.bus = MessageBus()
        self.memo_store = MemoStore()
        self.context = ContextStore()
        self.memo_factory: MemoFactory | None = None
        self._running = False
        # Track signals per symbol: {symbol: [(score, timestamp), ...]}
        self._signal_buffer: dict[str, list[tuple[float, datetime]]] = {}
        # Cooldown tracker: {symbol: last_trigger_time}
        self._cooldowns: dict[str, datetime] = {}
        # Active anchor events for satellite lag-window scanning
        self._anchor_events: list[AnchorEvent] = []

    async def start(self) -> None:
        """Connect to Redis and start scanning."""
        await self.bus.connect()
        self.memo_store._redis = self.bus.redis
        self.context._redis = self.bus.redis
        self.memo_factory = MemoFactory(self.bus, self.memo_store, self.context)
        self._running = True

        group = "cg:watchlist_scanner"
        streams = {
            STREAMS["news"]: ">",
            STREAMS["market_data"]: ">",
            STREAMS["events"]: ">",
            STREAMS["smart_money"]: ">",
            STREAMS["data_science"]: ">",
            STREAMS["execution"]: ">",  # Listen for anchor trade completions
        }

        for stream in streams:
            await self.bus.ensure_consumer_group(stream, group)

        logger.info(
            "Watchlist Scanner started — universe: %d symbols (%d Mag7 + %d satellites)",
            len(FULL_UNIVERSE), len(PRIMARY_SYMBOLS), len(FULL_UNIVERSE) - len(PRIMARY_SYMBOLS),
        )

        while self._running:
            try:
                messages = await self.bus.consume(
                    streams, group, "scanner_0", count=50, block_ms=2000,
                )
                for stream, msg_id, data in messages:
                    try:
                        if stream == STREAMS["execution"]:
                            await self._process_execution_event(data)
                        else:
                            await self._process_signal(stream, data)
                    except Exception:
                        logger.debug("Error processing signal on %s", stream)
                    await self.bus.ack(stream, group, msg_id)

                # Check for trigger conditions
                await self._check_triggers()

                # Clean up expired anchor events
                self._anchor_events = [
                    ae for ae in self._anchor_events if not ae.is_expired()
                ]

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Scanner loop error")
                await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False
        await self.bus.disconnect()

    async def _process_signal(self, stream: str, data: dict[str, str]) -> None:
        """Extract symbol and score from a raw signal."""
        symbol = data.get("symbol", "")
        if not symbol:
            return

        # Only track symbols in our universe
        if symbol not in FULL_UNIVERSE:
            return

        score = 0.0
        if "sentiment_score" in data:
            score = float(data["sentiment_score"])
        elif "score" in data:
            score = float(data["score"])
        elif "data" in data:
            import orjson
            try:
                parsed = orjson.loads(data["data"])
                if "price" in parsed:
                    score = 0.1
            except Exception:
                pass

        now = datetime.utcnow()
        if symbol not in self._signal_buffer:
            self._signal_buffer[symbol] = []
        self._signal_buffer[symbol].append((score, now))

    async def _process_execution_event(self, data: dict[str, str]) -> None:
        """Detect completed Mag 7 trades and open satellite lag windows."""
        event_type = data.get("event_type", "")
        if event_type != "order_filled":
            return

        symbol = data.get("symbol", "")
        memo_id_str = data.get("memo_id", "")
        if not symbol or not memo_id_str:
            return

        # Only create anchor events for primary symbols
        if not is_primary(symbol):
            return

        # Only if this anchor has satellites defined
        if symbol not in SATELLITE_CLUSTERS:
            return

        anchor = AnchorEvent(
            anchor_symbol=symbol,
            memo_id=UUID(memo_id_str),
            completed_at=datetime.utcnow(),
        )
        self._anchor_events.append(anchor)
        logger.info(
            "Anchor event created for %s — satellite lag window opens in %dh",
            symbol, SATELLITE_LAG_WINDOW_HOURS[0],
        )

    async def _check_triggers(self) -> None:
        """Check if any symbol has enough signals to trigger a memo."""
        now = datetime.utcnow()
        window = timedelta(seconds=SIGNAL_WINDOW_SECONDS)
        cooldown = timedelta(seconds=COOLDOWN_SECONDS)

        for symbol, signals in list(self._signal_buffer.items()):
            # Prune old signals
            signals[:] = [(s, t) for s, t in signals if now - t < window]
            if not signals:
                del self._signal_buffer[symbol]
                continue

            # Check cooldown
            if symbol in self._cooldowns and now - self._cooldowns[symbol] < cooldown:
                continue

            # Check if enough signals with meaningful scores
            strong_signals = [(s, t) for s, t in signals if abs(s) > 0.05]
            if len(strong_signals) < MIN_SIGNAL_COUNT:
                continue

            # Check if symbol is in the avoid list
            calendar_ctx = await self.context.get("calendar")
            avoid_symbols = calendar_ctx.get("avoid_symbols", [])
            if symbol in avoid_symbols:
                logger.info("Skipping %s — avoid due to upcoming event", symbol)
                continue

            # Check circuit breaker
            portfolio_ctx = await self.context.get("portfolio")
            if str(portfolio_ctx.get("circuit_breaker_active", "")).lower() == "true":
                logger.warning("Circuit breaker active — skipping memo creation")
                continue

            # Determine if this is a primary (Mag 7) or satellite trigger
            is_satellite_trade = False
            anchor_symbol = None
            anchor_memo_id = None

            if is_primary(symbol):
                # Primary trigger — always allowed (Mag 7 + Expanded)
                pass
            else:
                # Satellite — only trigger if in an active lag window
                anchor_event = self._find_anchor_event(symbol)
                if anchor_event is None:
                    continue  # No active lag window for this satellite
                if not anchor_event.can_trigger_satellite():
                    continue

                is_satellite_trade = True
                anchor_symbol = anchor_event.anchor_symbol
                anchor_memo_id = anchor_event.memo_id
                anchor_event.satellites_triggered += 1
                logger.info(
                    "Satellite trigger: %s (anchor: %s, lag window active)",
                    symbol, anchor_symbol,
                )

            # Create memo
            avg_score = sum(s for s, _ in signals) / len(signals) if signals else 0.0
            logger.info(
                "Triggering memo for %s: %d signals, avg_score=%.3f, satellite=%s",
                symbol, len(signals), avg_score, is_satellite_trade,
            )

            if self.memo_factory:
                memo = await self.memo_factory.create_memo(symbol)
                if memo and is_satellite_trade:
                    memo.is_satellite = True
                    memo.anchor_symbol = anchor_symbol
                    memo.anchor_memo_id = anchor_memo_id
                    await self.memo_store.save(memo)

            self._cooldowns[symbol] = now
            self._signal_buffer[symbol] = []

    def _find_anchor_event(self, satellite_symbol: str) -> AnchorEvent | None:
        """Find an active anchor event whose cluster includes this satellite."""
        for ae in self._anchor_events:
            cluster = SATELLITE_CLUSTERS.get(ae.anchor_symbol, [])
            if satellite_symbol in cluster and ae.can_trigger_satellite():
                return ae
        return None


async def main() -> None:
    from quantum_edge.utils.logging import setup_logging

    setup_logging()
    scanner = WatchlistScanner()
    await scanner.start()


if __name__ == "__main__":
    asyncio.run(main())
