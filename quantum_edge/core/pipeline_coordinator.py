"""Pipeline Coordinator — phase transition state machine with timeouts.

A lightweight Python process (not an agent) that:
- Tracks memo state transitions
- Emits "phase advance" events via Redis Streams
- Enforces timeouts per phase
- Recovers from persisted memo state in TimescaleDB if restarted
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from quantum_edge.core.config import settings
from quantum_edge.core.context_store import ContextStore
from quantum_edge.core.decision_engine import DecisionEngine
from quantum_edge.core.memo_factory import MemoFactory
from quantum_edge.core.memo_store import MemoStore
from quantum_edge.core.message_bus import STREAMS, MessageBus
from quantum_edge.models.events import PipelineEvent, PipelineEventType
from quantum_edge.models.memo import AgentSignal, InvestmentMemo, MemoPhase, SmartMoneySignal

logger = logging.getLogger(__name__)

# Expected signal count per pass (Agents 1, 2, 3, 6)
REQUIRED_PASS_SIGNALS = 4

# Phase timeout configuration
PHASE_TIMEOUTS: dict[MemoPhase, timedelta] = {
    MemoPhase.SIGNAL_COLLECTION_PASS1: timedelta(seconds=settings.signal_collection_timeout_s),
    MemoPhase.PASS1_SCORING: timedelta(seconds=30),
    MemoPhase.SMART_MONEY_VALIDATION: timedelta(seconds=settings.smart_money_timeout_s),
    MemoPhase.SIGNAL_COLLECTION_PASS2: timedelta(seconds=settings.signal_collection_timeout_s),
    MemoPhase.PASS2_SCORING: timedelta(seconds=30),
    MemoPhase.TECHNICAL_EVALUATION: timedelta(seconds=60),
    MemoPhase.RISK_CHECK: timedelta(seconds=30),
    MemoPhase.EXECUTION: timedelta(seconds=30),
    MemoPhase.POSITION_MONITORING: timedelta(hours=8),
}


class ActiveMemo:
    """Tracks an in-flight memo through the pipeline."""

    def __init__(self, memo: InvestmentMemo) -> None:
        self.memo = memo
        self.phase_started_at: datetime = datetime.utcnow()
        self.pass1_signals_received: set[str] = set()  # agent_ids
        self.pass2_signals_received: set[str] = set()

    @property
    def memo_id(self) -> UUID:
        return self.memo.memo_id

    def is_timed_out(self) -> bool:
        timeout = PHASE_TIMEOUTS.get(self.memo.phase)
        if timeout is None:
            return False
        return datetime.utcnow() - self.phase_started_at > timeout

    def reset_phase_timer(self) -> None:
        self.phase_started_at = datetime.utcnow()


class PipelineCoordinator:
    """State machine managing memo lifecycle transitions."""

    def __init__(self) -> None:
        self.bus = MessageBus()
        self.memo_store = MemoStore()
        self.context = ContextStore()
        self.decision_engine = DecisionEngine(self.context)
        self.memo_factory: MemoFactory | None = None
        self.active_memos: dict[UUID, ActiveMemo] = {}
        self._running = False

    async def start(self) -> None:
        """Connect to Redis and start the coordinator loops."""
        await self.bus.connect()
        self.memo_store._redis = self.bus.redis
        self.context._redis = self.bus.redis
        self.memo_factory = MemoFactory(self.bus, self.memo_store, self.context)
        await self._recover_active_memos()
        self._running = True

        tasks = [
            asyncio.create_task(self._event_loop()),
            asyncio.create_task(self._timeout_loop()),
        ]
        logger.info("Pipeline Coordinator started with %d active memos", len(self.active_memos))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def stop(self) -> None:
        self._running = False
        await self.bus.disconnect()
        await self.memo_store.close()

    async def _recover_active_memos(self) -> None:
        """On startup, recover any in-flight memos from DB."""
        try:
            memos = await self.memo_store.get_active_memos()
            for memo in memos:
                self.active_memos[memo.memo_id] = ActiveMemo(memo)
            if memos:
                logger.info("Recovered %d active memos from DB", len(memos))
        except Exception:
            logger.warning("Could not recover memos from DB (might not be initialized)")

    async def _event_loop(self) -> None:
        """Consume pipeline events and drive state transitions."""
        group = "cg:coordinator"
        consumer = "coordinator_0"
        streams = {
            STREAMS["phase"]: ">",
            STREAMS["memo"]: ">",
            STREAMS["decision"]: ">",
            STREAMS["execution"]: ">",
        }

        for stream in streams:
            await self.bus.ensure_consumer_group(stream, group)

        while self._running:
            try:
                messages = await self.bus.consume(streams, group, consumer, count=20, block_ms=1000)
                for stream, msg_id, data in messages:
                    try:
                        await self._handle_event(stream, data)
                    except Exception:
                        logger.exception("Error handling event on %s", stream)
                    await self.bus.ack(stream, group, msg_id)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Coordinator event loop error")
                await asyncio.sleep(1)

    async def _handle_event(self, stream: str, data: dict[str, str]) -> None:
        """Route events to appropriate handlers."""
        event = PipelineEvent.from_stream_dict(data)

        match event.event_type:
            case PipelineEventType.MEMO_CREATED:
                await self._on_memo_created(event)
            case PipelineEventType.SIGNAL_RECEIVED:
                await self._on_signal_received(event)
            case PipelineEventType.PASS1_SCORED:
                await self._on_pass_scored(event, pass_num=1)
            case PipelineEventType.SMART_MONEY_COMPLETE:
                await self._on_smart_money_complete(event)
            case PipelineEventType.PASS2_SCORED:
                await self._on_pass_scored(event, pass_num=2)
            case PipelineEventType.TECHNICAL_COMPLETE:
                await self._on_technical_complete(event)
            case PipelineEventType.RISK_CHECK_COMPLETE:
                await self._on_risk_check_complete(event)
            case PipelineEventType.ORDER_FILLED:
                await self._on_order_filled(event)
            case PipelineEventType.POSITION_CLOSED:
                await self._on_position_closed(event)
            case PipelineEventType.ORDER_REJECTED | PipelineEventType.ORDER_CANCELLED:
                await self._on_order_failed(event)

    async def _on_memo_created(self, event: PipelineEvent) -> None:
        if event.memo_id is None:
            return
        memo = await self.memo_store.get(event.memo_id)
        if memo and not memo.is_terminal():
            active = ActiveMemo(memo)
            self.active_memos[event.memo_id] = active
            logger.info("Tracking new memo: %s (%s)", event.memo_id, event.symbol)

            # Notify agents to start signal collection
            await self.bus.publish(
                STREAMS["phase"],
                PipelineEvent(
                    event_type=PipelineEventType.PHASE_ADVANCE,
                    memo_id=event.memo_id,
                    symbol=memo.symbol,
                    phase=MemoPhase.SIGNAL_COLLECTION_PASS1.value,
                    data={
                        "from_phase": "none",
                        "to_phase": MemoPhase.SIGNAL_COLLECTION_PASS1.value,
                    },
                ).to_stream_dict(),
            )

    async def _on_signal_received(self, event: PipelineEvent) -> None:
        if event.memo_id is None or event.memo_id not in self.active_memos:
            return

        active = self.active_memos[event.memo_id]
        pass_num = event.pass_number or 1
        agent_id = event.agent_id or ""

        # Deserialize signal from event data
        signal_json = event.data.get("signal")
        signal = None
        if signal_json:
            signal = AgentSignal.model_validate_json(signal_json)

        if pass_num == 1:
            active.pass1_signals_received.add(agent_id)
            if signal:
                active.memo.pass1_signals.append(signal)
            if len(active.pass1_signals_received) >= REQUIRED_PASS_SIGNALS:
                # Assemble memo v1 before scoring
                if self.memo_factory:
                    await self.memo_factory.assemble_v1(
                        active.memo_id,
                        active.memo.pass1_signals,
                    )
                    # Reload memo from store
                    refreshed = await self.memo_store.get(active.memo_id)
                    if refreshed:
                        active.memo = refreshed
                await self._advance_phase(active, MemoPhase.PASS1_SCORING)
                # Run scoring immediately (coordinator handles this directly)
                await self._do_scoring(active, pass_num=1)
        elif pass_num == 2:
            active.pass2_signals_received.add(agent_id)
            if signal:
                active.memo.pass2_signals.append(signal)
            if len(active.pass2_signals_received) >= REQUIRED_PASS_SIGNALS:
                # Assemble memo v2 before scoring
                if self.memo_factory:
                    await self.memo_factory.assemble_v2(
                        active.memo_id,
                        active.memo.pass2_signals,
                        active.memo.smart_money,
                    )
                    refreshed = await self.memo_store.get(active.memo_id)
                    if refreshed:
                        active.memo = refreshed
                await self._advance_phase(active, MemoPhase.PASS2_SCORING)
                await self._do_scoring(active, pass_num=2)

    async def _on_pass_scored(self, event: PipelineEvent, pass_num: int) -> None:
        """Handle externally-published scoring events (fallback path)."""
        if event.memo_id is None or event.memo_id not in self.active_memos:
            return

        active = self.active_memos[event.memo_id]
        # Skip if already past scoring phase (coordinator scored inline)
        if pass_num == 1 and active.memo.phase != MemoPhase.PASS1_SCORING:
            return
        if pass_num == 2 and active.memo.phase != MemoPhase.PASS2_SCORING:
            return

        passed = event.data.get("passed", False)
        if not passed:
            await self._cancel_memo(active, f"Pass {pass_num} score below threshold")
            return

        if pass_num == 1:
            await self._advance_phase(active, MemoPhase.SMART_MONEY_VALIDATION)
        elif pass_num == 2:
            await self._advance_phase(active, MemoPhase.TECHNICAL_EVALUATION)

    async def _on_smart_money_complete(self, event: PipelineEvent) -> None:
        if event.memo_id is None or event.memo_id not in self.active_memos:
            return
        active = self.active_memos[event.memo_id]

        # Deserialize SmartMoneySignal from event data
        signal_json = event.data.get("signal")
        if signal_json:
            active.memo.smart_money = SmartMoneySignal.model_validate_json(signal_json)
            await self.memo_store.save(active.memo)

        await self._advance_phase(active, MemoPhase.SIGNAL_COLLECTION_PASS2)

    async def _on_technical_complete(self, event: PipelineEvent) -> None:
        if event.memo_id is None or event.memo_id not in self.active_memos:
            return
        active = self.active_memos[event.memo_id]
        passed = event.data.get("passed", False)
        if not passed:
            await self._cancel_memo(active, "Technical evaluation failed")
            return

        # Store technical eval data on the memo
        from quantum_edge.models.memo import TechnicalEvaluation
        active.memo.technical_eval = TechnicalEvaluation(
            entry_price=float(event.data.get("entry_price", 0)),
            stop_loss=float(event.data.get("stop_loss", 0)),
            take_profit=float(event.data.get("take_profit", 0)),
            risk_reward_ratio=float(event.data.get("risk_reward_ratio", 0)),
            passed=True,
        )
        await self.memo_store.save(active.memo)

        await self._advance_phase(active, MemoPhase.RISK_CHECK)

    async def _on_risk_check_complete(self, event: PipelineEvent) -> None:
        if event.memo_id is None or event.memo_id not in self.active_memos:
            return
        active = self.active_memos[event.memo_id]
        approved = event.data.get("approved", False)
        if not approved:
            reason = event.data.get("veto_reason", "Risk check veto")
            await self._reject_memo(active, reason)
            return

        # Store risk check result on the memo
        from quantum_edge.models.memo import RiskCheckResult
        active.memo.risk_check = RiskCheckResult(
            approved=True,
            position_size_shares=int(event.data.get("position_size_shares", 0)),
            position_size_dollars=float(event.data.get("position_size_dollars", 0)),
            kelly_fraction=float(event.data.get("kelly_fraction", 0)),
        )
        await self.memo_store.save(active.memo)

        await self._advance_phase(active, MemoPhase.EXECUTION)

    async def _on_order_filled(self, event: PipelineEvent) -> None:
        if event.memo_id is None or event.memo_id not in self.active_memos:
            return
        active = self.active_memos[event.memo_id]
        if settings.position_monitor_enabled:
            await self._advance_phase(active, MemoPhase.POSITION_MONITORING)
        else:
            await self._complete_memo(active)

    async def _on_position_closed(self, event: PipelineEvent) -> None:
        if event.memo_id is None or event.memo_id not in self.active_memos:
            return
        active = self.active_memos[event.memo_id]
        await self._complete_memo(active)

    async def _on_order_failed(self, event: PipelineEvent) -> None:
        if event.memo_id is None or event.memo_id not in self.active_memos:
            return
        active = self.active_memos[event.memo_id]
        await self._cancel_memo(active, f"Order failed: {event.data.get('error', 'unknown')}")

    # ─── Scoring logic (coordinator handles this directly) ───

    async def _do_scoring(self, active: ActiveMemo, pass_num: int) -> None:
        """Run decision engine scoring for the given pass."""
        try:
            memo = active.memo
            if pass_num == 1:
                score = await self.decision_engine.score_pass1(memo)
                memo.pass1_score = score
            else:
                score = await self.decision_engine.score_pass2(memo)
                memo.pass2_score = score

            await self.memo_store.save(memo)

            passed = score.passed

            if not passed:
                await self._cancel_memo(active, f"Pass {pass_num} score {score.composite_score:.4f} below threshold")
                return

            if pass_num == 1:
                await self._advance_phase(active, MemoPhase.SMART_MONEY_VALIDATION)
            else:
                await self._advance_phase(active, MemoPhase.TECHNICAL_EVALUATION)

        except Exception:
            logger.exception("Scoring failed for memo %s pass %d", active.memo_id, pass_num)
            await self._cancel_memo(active, f"Scoring error in pass {pass_num}")

    async def _do_execution(self, active: ActiveMemo) -> None:
        """Submit the trade order via broker."""
        try:
            from quantum_edge.broker.alpaca import AlpacaBroker

            memo = active.memo
            tech = memo.technical_eval
            risk = memo.risk_check

            if tech is None or risk is None or not risk.approved:
                await self._cancel_memo(active, "Missing technical eval or risk approval")
                return

            direction = memo.pass2_score.direction if memo.pass2_score else "long"
            side = "long" if direction == "long" or str(direction) == "Direction.LONG" else "short"

            broker = AlpacaBroker()
            await broker.connect()
            try:
                result = await broker.submit_bracket_order(
                    symbol=memo.symbol,
                    side=side,
                    qty=risk.position_size_shares,
                    entry_price=tech.entry_price,
                    stop_loss=tech.stop_loss,
                    take_profit=tech.take_profit,
                )

                memo.execution = result
                await self.memo_store.save(memo)

                if result.status == "failed":
                    await self.bus.publish(
                        STREAMS["execution"],
                        PipelineEvent(
                            event_type=PipelineEventType.ORDER_REJECTED,
                            memo_id=active.memo_id,
                            symbol=memo.symbol,
                            data={"error": result.error or "Order failed"},
                        ).to_stream_dict(),
                    )
                else:
                    # Poll Alpaca for actual fill before publishing ORDER_FILLED
                    fill_status = await self._wait_for_fill(broker, result.order_id or "")
                    if fill_status == "filled":
                        await self.bus.publish(
                            STREAMS["execution"],
                            PipelineEvent(
                                event_type=PipelineEventType.ORDER_FILLED,
                                memo_id=active.memo_id,
                                symbol=memo.symbol,
                                data={"order_id": result.order_id or "", "status": "filled"},
                            ).to_stream_dict(),
                        )
                    elif fill_status in ("cancelled", "expired", "rejected"):
                        await self.bus.publish(
                            STREAMS["execution"],
                            PipelineEvent(
                                event_type=PipelineEventType.ORDER_REJECTED,
                                memo_id=active.memo_id,
                                symbol=memo.symbol,
                                data={"error": f"Order {fill_status}"},
                            ).to_stream_dict(),
                        )
                    else:
                        # Still pending after timeout — publish ORDER_PENDING
                        # Agent 08 will pick it up via cycle polling
                        await self.bus.publish(
                            STREAMS["execution"],
                            PipelineEvent(
                                event_type=PipelineEventType.ORDER_PENDING,
                                memo_id=active.memo_id,
                                symbol=memo.symbol,
                                data={"order_id": result.order_id or "", "status": fill_status},
                            ).to_stream_dict(),
                        )
                        logger.warning(
                            "Order %s still %s after poll timeout — published ORDER_PENDING",
                            result.order_id, fill_status,
                        )
            finally:
                await broker.disconnect()

        except Exception:
            logger.exception("Execution failed for memo %s", active.memo_id)
            await self._cancel_memo(active, "Execution error")

    async def _wait_for_fill(
        self,
        broker: Any,
        order_id: str,
        poll_interval: float = 1.0,
        timeout: float = 30.0,
    ) -> str:
        """Poll Alpaca until order is filled, terminal, or timeout.

        Returns the final order status string.
        """
        if not order_id:
            return "unknown"

        elapsed = 0.0
        while elapsed < timeout:
            try:
                order_info = await broker.get_order_by_id(order_id)
                status = order_info.get("status", "unknown")
                if status in ("filled", "partially_filled"):
                    return "filled"
                if status in ("cancelled", "expired", "rejected", "suspended"):
                    return status
                # Still pending — keep polling
            except Exception:
                logger.warning("Error polling order %s status", order_id)
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        # Timeout — return last known status
        try:
            order_info = await broker.get_order_by_id(order_id)
            return order_info.get("status", "pending")
        except Exception:
            return "pending"

    # ─── State transition helpers ───

    async def _advance_phase(self, active: ActiveMemo, new_phase: MemoPhase) -> None:
        old_phase = active.memo.phase
        active.memo.advance_phase(new_phase)
        active.reset_phase_timer()
        await self.memo_store.save(active.memo)

        # Include additional data for phases that need it
        extra_data: dict[str, Any] = {
            "from_phase": old_phase.value,
            "to_phase": new_phase.value,
        }

        # Pass direction info for technical evaluation
        if new_phase == MemoPhase.TECHNICAL_EVALUATION and active.memo.pass2_score:
            extra_data["direction"] = active.memo.pass2_score.direction.value

        # Pass trade params for risk check
        if new_phase == MemoPhase.RISK_CHECK and active.memo.technical_eval:
            tech = active.memo.technical_eval
            extra_data["entry_price"] = str(tech.entry_price)
            extra_data["stop_loss"] = str(tech.stop_loss)
            extra_data["take_profit"] = str(tech.take_profit)
            if active.memo.pass2_score:
                extra_data["direction"] = active.memo.pass2_score.direction.value
                extra_data["composite_score"] = str(active.memo.pass2_score.composite_score)
                extra_data["conviction"] = active.memo.pass2_score.conviction.value

        await self.bus.publish(
            STREAMS["phase"],
            PipelineEvent(
                event_type=PipelineEventType.PHASE_ADVANCE,
                memo_id=active.memo_id,
                symbol=active.memo.symbol,
                phase=new_phase.value,
                data=extra_data,
            ).to_stream_dict(),
        )
        logger.info("Memo %s: %s → %s", active.memo_id, old_phase, new_phase)

        # Handle phases the coordinator orchestrates directly
        if new_phase == MemoPhase.EXECUTION:
            await self._do_execution(active)

    async def _cancel_memo(self, active: ActiveMemo, reason: str) -> None:
        active.memo.cancel_reason = reason
        active.memo.advance_phase(MemoPhase.CANCELLED)
        active.memo.completed_at = datetime.utcnow()
        await self.memo_store.save(active.memo)
        self.active_memos.pop(active.memo_id, None)

        await self.bus.publish(
            STREAMS["phase"],
            PipelineEvent(
                event_type=PipelineEventType.MEMO_CANCELLED,
                memo_id=active.memo_id,
                symbol=active.memo.symbol,
                data={"reason": reason},
            ).to_stream_dict(),
        )
        logger.info("Memo %s cancelled: %s", active.memo_id, reason)

    async def _reject_memo(self, active: ActiveMemo, reason: str) -> None:
        active.memo.cancel_reason = reason
        active.memo.advance_phase(MemoPhase.REJECTED)
        active.memo.completed_at = datetime.utcnow()
        await self.memo_store.save(active.memo)
        self.active_memos.pop(active.memo_id, None)

        await self.bus.publish(
            STREAMS["phase"],
            PipelineEvent(
                event_type=PipelineEventType.MEMO_REJECTED,
                memo_id=active.memo_id,
                symbol=active.memo.symbol,
                data={"reason": reason},
            ).to_stream_dict(),
        )
        logger.info("Memo %s rejected: %s", active.memo_id, reason)

    async def _complete_memo(self, active: ActiveMemo) -> None:
        active.memo.advance_phase(MemoPhase.COMPLETED)
        active.memo.completed_at = datetime.utcnow()
        await self.memo_store.save(active.memo)
        self.active_memos.pop(active.memo_id, None)

        await self.bus.publish(
            STREAMS["phase"],
            PipelineEvent(
                event_type=PipelineEventType.MEMO_COMPLETED,
                memo_id=active.memo_id,
                symbol=active.memo.symbol,
            ).to_stream_dict(),
        )
        logger.info("Memo %s completed!", active.memo_id)

    async def _timeout_loop(self) -> None:
        """Check for timed-out memos every 5 seconds."""
        while self._running:
            try:
                timed_out = [
                    active
                    for active in list(self.active_memos.values())
                    if active.is_timed_out()
                ]
                for active in timed_out:
                    timed_out_phase = active.memo.phase
                    active.memo.advance_phase(MemoPhase.TIMED_OUT)
                    active.memo.cancel_reason = f"Timed out in phase {timed_out_phase}"
                    active.memo.completed_at = datetime.utcnow()
                    await self.memo_store.save(active.memo)
                    self.active_memos.pop(active.memo_id, None)

                    await self.bus.publish(
                        STREAMS["phase"],
                        PipelineEvent(
                            event_type=PipelineEventType.MEMO_TIMED_OUT,
                            memo_id=active.memo_id,
                            symbol=active.memo.symbol,
                            data={"phase": timed_out_phase.value},
                        ).to_stream_dict(),
                    )
                    logger.warning("Memo %s timed out in phase %s", active.memo_id, timed_out_phase)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Timeout check error")
            await asyncio.sleep(5)
