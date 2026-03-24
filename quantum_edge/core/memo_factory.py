"""Memo Factory — signal collection → memo assembly + context snapshot freezing."""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID, uuid4

from quantum_edge.core.context_store import ContextStore
from quantum_edge.core.memo_store import MemoStore
from quantum_edge.core.message_bus import STREAMS, MessageBus
from quantum_edge.models.events import PipelineEvent, PipelineEventType
from quantum_edge.models.memo import (
    AgentSignal,
    InvestmentMemo,
    MemoPhase,
    SmartMoneySignal,
)

logger = logging.getLogger(__name__)


class MemoFactory:
    """Assembles InvestmentMemos from collected signals + frozen context snapshots."""

    def __init__(
        self,
        bus: MessageBus,
        memo_store: MemoStore,
        context_store: ContextStore,
    ) -> None:
        self.bus = bus
        self.memo_store = memo_store
        self.context = context_store

    async def create_memo(self, symbol: str) -> InvestmentMemo:
        """Create a new memo and start tracking it."""
        memo = InvestmentMemo(
            memo_id=uuid4(),
            symbol=symbol,
            version=1,
            phase=MemoPhase.SIGNAL_COLLECTION_PASS1,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        await self.memo_store.save(memo)

        # Publish creation event
        await self.bus.publish(
            STREAMS["memo"],
            PipelineEvent(
                event_type=PipelineEventType.MEMO_CREATED,
                memo_id=memo.memo_id,
                symbol=symbol,
            ).to_stream_dict(),
        )

        logger.info("Created memo %s for %s", memo.memo_id, symbol)
        return memo

    async def assemble_v1(
        self,
        memo_id: UUID,
        signals: list[AgentSignal],
    ) -> InvestmentMemo | None:
        """Assemble version 1: Pass 1 signals + frozen context snapshot."""
        memo = await self.memo_store.get(memo_id)
        if memo is None:
            logger.error("Memo %s not found for v1 assembly", memo_id)
            return None

        # Freeze context at this moment
        snapshot = await self.context.snapshot()

        memo.pass1_signals = signals
        memo.pass1_context = snapshot
        memo.version = 1
        memo.updated_at = datetime.utcnow()

        await self.memo_store.save(memo)

        await self.bus.publish(
            STREAMS["memo"],
            PipelineEvent(
                event_type=PipelineEventType.MEMO_UPDATED,
                memo_id=memo.memo_id,
                symbol=memo.symbol,
                pass_number=1,
                data={"signal_count": len(signals)},
            ).to_stream_dict(),
        )

        logger.info("Assembled memo v1 for %s with %d signals", memo.symbol, len(signals))
        return memo

    async def assemble_v2(
        self,
        memo_id: UUID,
        signals: list[AgentSignal],
        smart_money: SmartMoneySignal | None = None,
    ) -> InvestmentMemo | None:
        """Assemble version 2: Pass 2 signals + fresh context + smart money."""
        memo = await self.memo_store.get(memo_id)
        if memo is None:
            logger.error("Memo %s not found for v2 assembly", memo_id)
            return None

        # Freeze fresh context
        snapshot = await self.context.snapshot()

        memo.pass2_signals = signals
        memo.pass2_context = snapshot
        if smart_money:
            memo.smart_money = smart_money
        memo.version = 2
        memo.updated_at = datetime.utcnow()

        await self.memo_store.save(memo)

        await self.bus.publish(
            STREAMS["memo"],
            PipelineEvent(
                event_type=PipelineEventType.MEMO_UPDATED,
                memo_id=memo.memo_id,
                symbol=memo.symbol,
                pass_number=2,
                data={"signal_count": len(signals)},
            ).to_stream_dict(),
        )

        logger.info("Assembled memo v2 for %s with %d signals", memo.symbol, len(signals))
        return memo
