"""Agent 8: Position Monitor — trailing stop management (15s cycle).

Monitors filled positions for trailing stop activation.
When unrealized P&L reaches the activation threshold (default 3.5%),
cancels bracket order legs and replaces with a native trailing stop.

Publishes: qe:signals:position_monitor
Subscribes: qe:pipeline:phase, qe:pipeline:execution
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import orjson
from pydantic import BaseModel

from quantum_edge.broker.alpaca import AlpacaBroker
from quantum_edge.core.base_agent import BaseAgent
from quantum_edge.core.config import settings
from quantum_edge.core.message_bus import STREAMS
from quantum_edge.models.events import PipelineEvent, PipelineEventType

logger = logging.getLogger(__name__)

MONITOR_STATE_KEY = "qe:state:position_monitor"


class MonitoredPosition(BaseModel):
    """A position being actively monitored for trailing stop activation."""

    memo_id: str
    symbol: str
    side: str  # "long" or "short"
    qty: int
    entry_price: float
    bracket_order_id: str
    stop_loss_leg_id: str = ""
    take_profit_leg_id: str = ""
    trailing_stop_order_id: str = ""
    trailing_stop_activated: bool = False
    activation_threshold_pct: float = 3.5
    trail_percent: float = 1.5
    highest_unrealized_pct: float = 0.0
    started_at: str = ""
    activated_at: str | None = None


class PositionMonitor(BaseAgent):
    agent_id = "agent_08"
    agent_name = "position_monitor"
    consumer_group = "cg:agent_08_position_monitor"
    subscribe_streams = [STREAMS["phase"], STREAMS["execution"]]
    cycle_seconds = 15.0

    def __init__(self) -> None:
        super().__init__()
        self._broker = AlpacaBroker()
        self._monitored: dict[str, MonitoredPosition] = {}

    async def on_start(self) -> None:
        self.cycle_seconds = settings.position_monitor_poll_interval_s
        await self._broker.connect()
        await self._recover_state()
        logger.info(
            "Position Monitor started (threshold=%.1f%%, trail=%.1f%%, poll=%ds)",
            settings.trailing_stop_activation_pct,
            settings.trailing_stop_trail_pct,
            int(settings.position_monitor_poll_interval_s),
        )

    async def on_stop(self) -> None:
        await self._broker.disconnect()

    async def on_message(self, stream: str, msg_id: str, data: dict[str, str]) -> None:
        """Listen for ORDER_FILLED events to start monitoring."""
        event_type = data.get("event_type", "")
        if event_type == PipelineEventType.ORDER_FILLED:
            await self._start_monitoring(data)
        elif event_type == PipelineEventType.POSITION_CLOSED:
            memo_id = data.get("memo_id", "")
            if memo_id in self._monitored:
                self._monitored.pop(memo_id)
                await self._persist_state()

    async def on_cycle(self) -> None:
        """Poll all monitored positions for trailing stop activation."""
        if not self._monitored:
            return

        if not await self._broker.is_market_open():
            return

        to_remove: list[str] = []

        for memo_id, mp in list(self._monitored.items()):
            try:
                position = await self._broker.get_open_position(mp.symbol)

                if position is None:
                    # Position was closed (SL, TP, or market close)
                    await self._on_position_closed(mp, reason="position_closed_by_bracket")
                    to_remove.append(memo_id)
                    continue

                unrealized_pct = position.unrealized_pl_pct * 100  # Alpaca returns decimal

                # Track peak
                if unrealized_pct > mp.highest_unrealized_pct:
                    mp.highest_unrealized_pct = unrealized_pct

                if not mp.trailing_stop_activated:
                    if unrealized_pct >= mp.activation_threshold_pct:
                        await self._activate_trailing_stop(mp, unrealized_pct)
                else:
                    # Trailing stop active — check if it's been filled
                    if mp.trailing_stop_order_id:
                        order = await self._broker.get_order_by_id(mp.trailing_stop_order_id)
                        status = order.get("status", "")
                        if status in ("filled", "expired", "canceled", "cancelled"):
                            await self._on_position_closed(mp, reason=f"trailing_stop_{status}")
                            to_remove.append(memo_id)

                # Log to position_monitor stream for dashboard feed
                await self._log_activity(mp, unrealized_pct)

            except Exception:
                logger.exception("Error monitoring position %s (%s)", mp.symbol, memo_id)

        for memo_id in to_remove:
            self._monitored.pop(memo_id, None)

        if to_remove:
            await self._persist_state()

    # ─── Core logic ───

    async def _start_monitoring(self, data: dict[str, str]) -> None:
        """Register a filled position for monitoring."""
        memo_id = data.get("memo_id", "")
        symbol = data.get("symbol", "")
        if not memo_id or not symbol or memo_id in self._monitored:
            return

        # Parse order_id from event data
        order_id = ""
        raw_data = data.get("data", "")
        if raw_data:
            try:
                parsed = orjson.loads(raw_data)
                event_data = parsed.get("data", parsed)
                order_id = event_data.get("order_id", "")
            except Exception:
                pass

        if not order_id:
            logger.warning("ORDER_FILLED for %s but no order_id in event data", symbol)
            return

        # Get bracket order leg IDs
        sl_leg_id = ""
        tp_leg_id = ""
        try:
            order = await self._broker.get_order_by_id(order_id)
            for leg in order.get("legs", []):
                if leg.get("order_type") == "stop":
                    sl_leg_id = leg["id"]
                elif leg.get("order_type") == "limit":
                    tp_leg_id = leg["id"]
        except Exception:
            logger.warning("Could not fetch bracket legs for order %s", order_id)

        # Get live position details
        position = await self._broker.get_open_position(symbol)
        if position is None:
            logger.warning("ORDER_FILLED for %s but no position found", symbol)
            return

        mp = MonitoredPosition(
            memo_id=memo_id,
            symbol=symbol,
            side=position.side,
            qty=abs(position.qty),
            entry_price=position.avg_entry_price,
            bracket_order_id=order_id,
            stop_loss_leg_id=sl_leg_id,
            take_profit_leg_id=tp_leg_id,
            activation_threshold_pct=settings.trailing_stop_activation_pct,
            trail_percent=settings.trailing_stop_trail_pct,
            started_at=datetime.utcnow().isoformat(),
        )

        self._monitored[memo_id] = mp
        await self._persist_state()

        await self.publish_event(PipelineEvent(
            event_type=PipelineEventType.POSITION_MONITORING_STARTED,
            memo_id=UUID(memo_id),
            symbol=symbol,
            agent_id=self.agent_id,
            data={"entry_price": str(position.avg_entry_price), "qty": str(position.qty)},
        ))
        logger.info(
            "Monitoring position: %s (%s), entry=$%.2f, threshold=%.1f%%",
            symbol, memo_id, position.avg_entry_price, mp.activation_threshold_pct,
        )

    async def _activate_trailing_stop(self, mp: MonitoredPosition, current_pct: float) -> None:
        """Cancel bracket legs and submit a trailing stop order.

        Safety protocol:
        1. Cancel TP leg first (check result — abort if fail to avoid orphaned orders)
        2. Mark intent in Redis BEFORE cancelling SL (crash recovery can detect this)
        3. Cancel SL leg (abort if fail — bracket protection remains)
        4. Submit trailing stop immediately
        5. If trailing stop fails, emergency close (position must never be naked)
        """
        symbol = mp.symbol

        # Step 1: Cancel take-profit leg — abort if this fails (avoid orphaned TP)
        if mp.take_profit_leg_id:
            tp_cancelled = await self._broker.cancel_order_by_id(mp.take_profit_leg_id)
            if not tp_cancelled:
                logger.error(
                    "ABORT trailing stop: could not cancel TP leg for %s (bracket remains intact)",
                    symbol,
                )
                return

        # Step 2: Persist intent — if we crash after SL cancel, recovery knows to
        # either re-submit a trailing stop or emergency close
        mp.trailing_stop_activated = True  # Mark intent
        mp.activated_at = datetime.utcnow().isoformat()
        await self._persist_state()

        # Step 3: Cancel stop-loss leg (critical — if this fails, abort)
        if mp.stop_loss_leg_id:
            cancelled = await self._broker.cancel_order_by_id(mp.stop_loss_leg_id)
            if not cancelled:
                # Rollback intent — bracket SL still protects us
                mp.trailing_stop_activated = False
                mp.activated_at = None
                await self._persist_state()
                logger.error(
                    "ABORT trailing stop: could not cancel SL leg for %s (bracket protection remains)",
                    symbol,
                )
                return

        # Step 4: Submit trailing stop — position is unprotected, do this immediately
        result = await self._broker.submit_trailing_stop_order(
            symbol=symbol,
            side=mp.side,
            qty=mp.qty,
            trail_percent=mp.trail_percent,
        )

        if result.status == "failed":
            # Emergency: brackets cancelled but trailing stop failed — close position NOW
            logger.critical(
                "TRAILING STOP FAILED for %s after cancelling brackets. Emergency close.",
                symbol,
            )
            await self._broker.close_position(symbol)
            await self._on_position_closed(mp, reason="trailing_stop_submission_failed_emergency_close")
            return

        # Step 5: Record trailing stop order ID
        mp.trailing_stop_order_id = result.order_id or ""
        await self._persist_state()

        # Step 5: Publish event
        await self.publish_event(PipelineEvent(
            event_type=PipelineEventType.TRAILING_STOP_ACTIVATED,
            memo_id=UUID(mp.memo_id),
            symbol=symbol,
            agent_id=self.agent_id,
            data={
                "unrealized_pct": f"{current_pct:.2f}",
                "trail_percent": str(mp.trail_percent),
                "trailing_stop_order_id": mp.trailing_stop_order_id,
                "peak_unrealized_pct": f"{mp.highest_unrealized_pct:.2f}",
            },
        ))
        logger.info(
            "TRAILING STOP ACTIVATED: %s at %.2f%% unrealized (trail=%.1f%%)",
            symbol, current_pct, mp.trail_percent,
        )

    async def _on_position_closed(self, mp: MonitoredPosition, reason: str) -> None:
        """Handle position closure."""
        await self.publish_event(PipelineEvent(
            event_type=PipelineEventType.POSITION_CLOSED,
            memo_id=UUID(mp.memo_id),
            symbol=mp.symbol,
            agent_id=self.agent_id,
            data={
                "reason": reason,
                "trailing_stop_was_active": str(mp.trailing_stop_activated),
                "peak_unrealized_pct": f"{mp.highest_unrealized_pct:.2f}",
            },
        ))
        logger.info(
            "Position closed: %s (%s), reason=%s, peak=%.2f%%",
            mp.symbol, mp.memo_id, reason, mp.highest_unrealized_pct,
        )

    async def _log_activity(self, mp: MonitoredPosition, unrealized_pct: float) -> None:
        """Publish monitoring activity to the position_monitor signal stream."""
        await self.publish_signal(
            STREAMS.get("position_monitor", "qe:signals:position_monitor"),
            {
                "agent_id": self.agent_id,
                "symbol": mp.symbol,
                "memo_id": mp.memo_id,
                "unrealized_pct": f"{unrealized_pct:.2f}",
                "peak_pct": f"{mp.highest_unrealized_pct:.2f}",
                "trailing_active": str(mp.trailing_stop_activated),
                "threshold": str(mp.activation_threshold_pct),
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    # ─── State persistence ───

    async def _persist_state(self) -> None:
        """Save monitored positions to Redis for crash recovery."""
        redis = self.bus.redis
        if self._monitored:
            data = {mid: mp.model_dump_json() for mid, mp in self._monitored.items()}
            await redis.hset(MONITOR_STATE_KEY, mapping=data)
        else:
            await redis.delete(MONITOR_STATE_KEY)

    async def _recover_state(self) -> None:
        """Recover monitored positions from Redis on startup.

        Handles crash recovery: if a position was mid-activation (trailing_stop_activated=True
        but no trailing_stop_order_id), the SL bracket was likely cancelled and the position
        is unprotected. Submit a trailing stop or emergency close.
        """
        redis = self.bus.redis
        raw = await redis.hgetall(MONITOR_STATE_KEY)
        for memo_id, json_str in raw.items():
            try:
                mp = MonitoredPosition.model_validate_json(json_str)
                self._monitored[memo_id] = mp
            except Exception:
                logger.warning("Could not recover position for memo %s", memo_id)

        if self._monitored:
            logger.info("Recovered %d monitored positions from Redis", len(self._monitored))

        # Crash recovery: fix positions left unprotected mid-activation
        for memo_id, mp in list(self._monitored.items()):
            if mp.trailing_stop_activated and not mp.trailing_stop_order_id:
                logger.warning(
                    "CRASH RECOVERY: %s was mid-activation with no trailing stop order. "
                    "Attempting to submit trailing stop.",
                    mp.symbol,
                )
                position = await self._broker.get_open_position(mp.symbol)
                if position is None:
                    logger.info("Position %s already closed, cleaning up", mp.symbol)
                    self._monitored.pop(memo_id, None)
                    continue

                result = await self._broker.submit_trailing_stop_order(
                    symbol=mp.symbol,
                    side=mp.side,
                    qty=mp.qty,
                    trail_percent=mp.trail_percent,
                )
                if result.status == "failed":
                    logger.critical(
                        "CRASH RECOVERY FAILED for %s — emergency close", mp.symbol,
                    )
                    await self._broker.close_position(mp.symbol)
                    self._monitored.pop(memo_id, None)
                else:
                    mp.trailing_stop_order_id = result.order_id or ""
                    logger.info(
                        "CRASH RECOVERY: trailing stop submitted for %s (order=%s)",
                        mp.symbol, mp.trailing_stop_order_id,
                    )

            await self._persist_state()


async def main() -> None:
    from quantum_edge.utils.logging import setup_logging

    setup_logging()
    agent = PositionMonitor()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
