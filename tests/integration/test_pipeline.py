"""Integration test: Full pipeline flow with fakeredis (no DB required)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import pytest
import fakeredis.aioredis
import redis.asyncio as aioredis

from quantum_edge.core.context_store import ContextStore
from quantum_edge.core.decision_engine import DecisionEngine
from quantum_edge.core.memo_factory import MemoFactory
from quantum_edge.core.message_bus import STREAMS, MessageBus
from quantum_edge.models.memo import (
    AgentSignal,
    Conviction,
    Direction,
    InvestmentMemo,
    MemoPhase,
)

MEMO_KEY_PREFIX = "qe:memo:"


class RedisOnlyMemoStore:
    """MemoStore that only uses Redis (no TimescaleDB) for testing."""

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    @property
    def redis(self) -> aioredis.Redis:
        return self._redis

    async def save(self, memo: InvestmentMemo) -> None:
        memo.updated_at = datetime.utcnow()
        key = f"{MEMO_KEY_PREFIX}{memo.memo_id}"
        await self._redis.set(key, memo.model_dump_json(), ex=3600)

    async def get(self, memo_id: UUID) -> InvestmentMemo | None:
        key = f"{MEMO_KEY_PREFIX}{memo_id}"
        raw = await self._redis.get(key)
        if raw:
            return InvestmentMemo.model_validate_json(raw)
        return None

    async def get_active_memos(self) -> list[InvestmentMemo]:
        return []

    async def close(self) -> None:
        pass


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest.fixture
async def bus(redis):
    b = MessageBus()
    b._redis = redis
    return b


@pytest.fixture
async def context(redis):
    return ContextStore(redis_client=redis)


@pytest.fixture
async def memo_store(redis):
    return RedisOnlyMemoStore(redis_client=redis)


class TestPipelineFlow:
    @pytest.mark.asyncio
    async def test_memo_creation(self, bus, memo_store, context):
        factory = MemoFactory(bus, memo_store, context)
        memo = await factory.create_memo("AAPL")

        assert memo.symbol == "AAPL"
        assert memo.phase == MemoPhase.SIGNAL_COLLECTION_PASS1

    @pytest.mark.asyncio
    async def test_memo_v1_assembly(self, bus, memo_store, context):
        factory = MemoFactory(bus, memo_store, context)

        await context.update("regime", {"regime": "trending_bull"}, "agent_06")

        memo = await factory.create_memo("NVDA")
        signals = [
            AgentSignal(
                agent_id=f"agent_0{i}",
                agent_name=f"agent_{i}",
                symbol="NVDA",
                direction=Direction.LONG,
                conviction=Conviction.HIGH,
                score=0.8,
                pass_number=1,
            )
            for i in [1, 2, 3, 6]
        ]

        assembled = await factory.assemble_v1(memo.memo_id, signals)
        assert assembled is not None
        assert len(assembled.pass1_signals) == 4
        assert assembled.pass1_context is not None
        assert assembled.pass1_context.regime["regime"] == "trending_bull"

    @pytest.mark.asyncio
    async def test_decision_engine_scoring(self, redis, bus, memo_store, context):
        factory = MemoFactory(bus, memo_store, context)
        engine = DecisionEngine(context_store=context)

        memo = await factory.create_memo("AAPL")
        signals = [
            AgentSignal(
                agent_id=f"agent_0{i}",
                agent_name=f"agent_{i}",
                symbol="AAPL",
                direction=Direction.LONG,
                conviction=Conviction.HIGH,
                score=0.85,
                pass_number=1,
            )
            for i in [1, 2, 3, 6]
        ]

        assembled = await factory.assemble_v1(memo.memo_id, signals)
        assert assembled is not None

        score = await engine.score_pass1(assembled)
        assert score.composite_score > 0.0
        assert score.passed

    @pytest.mark.asyncio
    async def test_context_snapshot_frozen(self, bus, memo_store, context):
        factory = MemoFactory(bus, memo_store, context)

        await context.update("regime", {"regime": "trending_bull"}, "agent_06")

        memo = await factory.create_memo("TSLA")
        signals = [
            AgentSignal(
                agent_id="agent_01",
                agent_name="news",
                symbol="TSLA",
                direction=Direction.LONG,
                conviction=Conviction.HIGH,
                score=0.8,
                pass_number=1,
            )
        ]

        assembled = await factory.assemble_v1(memo.memo_id, signals)
        assert assembled is not None

        # Change context AFTER assembly
        await context.update("regime", {"regime": "high_volatility"}, "agent_06")

        # Frozen snapshot should still show old regime
        assert assembled.pass1_context is not None
        assert assembled.pass1_context.regime["regime"] == "trending_bull"

        # Current context should show new regime
        current = await context.get("regime")
        assert current["regime"] == "high_volatility"

    @pytest.mark.asyncio
    async def test_memo_v2_assembly(self, bus, memo_store, context):
        factory = MemoFactory(bus, memo_store, context)

        await context.update("regime", {"regime": "trending_bull"}, "agent_06")
        memo = await factory.create_memo("AMD")

        # Pass 1
        p1_signals = [
            AgentSignal(
                agent_id="agent_01", agent_name="news", symbol="AMD",
                direction=Direction.LONG, conviction=Conviction.HIGH,
                score=0.8, pass_number=1,
            )
        ]
        v1 = await factory.assemble_v1(memo.memo_id, p1_signals)
        assert v1 is not None
        assert v1.version == 1

        # Change context between passes
        await context.update("regime", {"regime": "mean_reverting"}, "agent_06")

        # Pass 2
        p2_signals = [
            AgentSignal(
                agent_id="agent_01", agent_name="news", symbol="AMD",
                direction=Direction.LONG, conviction=Conviction.HIGH,
                score=0.75, pass_number=2,
            )
        ]
        v2 = await factory.assemble_v2(memo.memo_id, p2_signals)
        assert v2 is not None
        assert v2.version == 2
        assert len(v2.pass2_signals) == 1

        # V1 context captured trending_bull, V2 should capture mean_reverting
        assert v2.pass1_context.regime["regime"] == "trending_bull"
        assert v2.pass2_context.regime["regime"] == "mean_reverting"
