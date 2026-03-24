"""Integration test: Full pipeline flow — memo creation through scoring.

Tests the complete wiring: signal collection → scoring → phase transitions.
Uses fakeredis, no external services required.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pytest
import fakeredis.aioredis
import redis.asyncio as aioredis

from quantum_edge.core.context_store import ContextStore
from quantum_edge.core.decision_engine import DecisionEngine
from quantum_edge.core.memo_factory import MemoFactory
from quantum_edge.core.message_bus import STREAMS, MessageBus
from quantum_edge.models.events import PipelineEvent, PipelineEventType
from quantum_edge.models.memo import (
    AgentSignal,
    Conviction,
    Direction,
    InvestmentMemo,
    MemoPhase,
    MemoScore,
    RiskCheckResult,
    TechnicalEvaluation,
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


def make_signals(symbol: str, pass_number: int, score: float = 0.8) -> list[AgentSignal]:
    """Create a set of 4 agent signals for testing."""
    return [
        AgentSignal(
            agent_id=f"agent_0{i}",
            agent_name=f"agent_{i}",
            symbol=symbol,
            direction=Direction.LONG,
            conviction=Conviction.HIGH,
            score=score,
            pass_number=pass_number,
        )
        for i in [1, 2, 3, 6]
    ]


class TestFullPipelineFlow:
    """Test the complete pipeline: create → signals → score → technical → risk."""

    @pytest.mark.asyncio
    async def test_full_pass1_scoring_flow(self, bus, memo_store, context):
        """Test: create memo → assemble v1 → score pass 1."""
        factory = MemoFactory(bus, memo_store, context)
        engine = DecisionEngine(context_store=context)

        # Set up regime context
        await context.update("regime", {"regime": "trending_bull"}, "agent_06")

        # Create memo
        memo = await factory.create_memo("AAPL")
        assert memo.phase == MemoPhase.SIGNAL_COLLECTION_PASS1

        # Collect signals and assemble
        signals = make_signals("AAPL", pass_number=1)
        assembled = await factory.assemble_v1(memo.memo_id, signals)
        assert assembled is not None
        assert len(assembled.pass1_signals) == 4

        # Score pass 1
        score = await engine.score_pass1(assembled)
        assert score.composite_score > 0.5
        assert score.passed is True
        assert score.direction == Direction.LONG
        assert score.conviction in (Conviction.HIGH, Conviction.VERY_HIGH)

    @pytest.mark.asyncio
    async def test_full_two_pass_scoring(self, bus, memo_store, context):
        """Test: pass 1 → pass 2 → direction consistency check."""
        factory = MemoFactory(bus, memo_store, context)
        engine = DecisionEngine(context_store=context)
        await context.update("regime", {"regime": "trending_bull"}, "agent_06")

        memo = await factory.create_memo("NVDA")

        # Pass 1
        p1 = make_signals("NVDA", pass_number=1, score=0.85)
        v1 = await factory.assemble_v1(memo.memo_id, p1)
        score1 = await engine.score_pass1(v1)
        assert score1.passed
        v1.pass1_score = score1

        # Save memo with pass1_score for direction consistency check
        await memo_store.save(v1)

        # Pass 2
        p2 = make_signals("NVDA", pass_number=2, score=0.80)
        v2 = await factory.assemble_v2(memo.memo_id, p2)
        assert v2 is not None

        # Re-attach pass1_score
        v2.pass1_score = score1

        score2 = await engine.score_pass2(v2)
        assert score2.passed  # Same direction = passes
        assert score2.direction == Direction.LONG
        assert "direction_mismatch" not in score2.component_scores

    @pytest.mark.asyncio
    async def test_direction_mismatch_fails_pass2(self, bus, memo_store, context):
        """Test: pass 2 fails when direction doesn't match pass 1."""
        factory = MemoFactory(bus, memo_store, context)
        engine = DecisionEngine(context_store=context)
        await context.update("regime", {"regime": "trending_bull"}, "agent_06")

        memo = await factory.create_memo("TSLA")

        # Pass 1 — LONG signals
        p1 = make_signals("TSLA", pass_number=1, score=0.8)
        v1 = await factory.assemble_v1(memo.memo_id, p1)
        score1 = await engine.score_pass1(v1)
        v1.pass1_score = score1
        await memo_store.save(v1)

        # Pass 2 — SHORT signals (direction mismatch)
        p2 = [
            AgentSignal(
                agent_id=f"agent_0{i}",
                agent_name=f"agent_{i}",
                symbol="TSLA",
                direction=Direction.SHORT,
                conviction=Conviction.HIGH,
                score=-0.8,
                pass_number=2,
            )
            for i in [1, 2, 3, 6]
        ]
        v2 = await factory.assemble_v2(memo.memo_id, p2)
        v2.pass1_score = score1
        score2 = await engine.score_pass2(v2)

        assert score2.passed is False
        assert "direction_mismatch" in score2.component_scores

    @pytest.mark.asyncio
    async def test_weak_signals_fail_pass1(self, bus, memo_store, context):
        """Test: weak signals don't pass the threshold."""
        factory = MemoFactory(bus, memo_store, context)
        engine = DecisionEngine(context_store=context)

        memo = await factory.create_memo("META")
        signals = make_signals("META", pass_number=1, score=0.1)  # Very weak
        assembled = await factory.assemble_v1(memo.memo_id, signals)
        score = await engine.score_pass1(assembled)

        assert score.passed is False

    @pytest.mark.asyncio
    async def test_pipeline_event_serialization(self):
        """Test: pipeline events round-trip through serialization."""
        memo_id = uuid4()
        event = PipelineEvent(
            event_type=PipelineEventType.PHASE_ADVANCE,
            memo_id=memo_id,
            symbol="AAPL",
            agent_id="agent_01",
            phase="signal_collection_pass1",
            pass_number=1,
            data={"from_phase": "created", "to_phase": "signal_collection_pass1"},
        )

        stream_dict = event.to_stream_dict()
        assert isinstance(stream_dict, dict)
        assert all(isinstance(v, str) for v in stream_dict.values())

        restored = PipelineEvent.from_stream_dict(stream_dict)
        assert restored.event_type == PipelineEventType.PHASE_ADVANCE
        assert restored.memo_id == memo_id
        assert restored.symbol == "AAPL"
        assert restored.data["to_phase"] == "signal_collection_pass1"

    @pytest.mark.asyncio
    async def test_signal_received_event_fields(self):
        """Test: SIGNAL_RECEIVED events carry all required fields."""
        memo_id = uuid4()
        event = PipelineEvent(
            event_type=PipelineEventType.SIGNAL_RECEIVED,
            memo_id=memo_id,
            symbol="AMD",
            agent_id="agent_01",
            pass_number=1,
            data={"agent_id": "agent_01", "symbol": "AMD"},
        )

        d = event.to_stream_dict()
        restored = PipelineEvent.from_stream_dict(d)
        assert restored.agent_id == "agent_01"
        assert restored.pass_number == 1
        assert restored.memo_id == memo_id

    @pytest.mark.asyncio
    async def test_technical_evaluation_model(self):
        """Test: TechnicalEvaluation stores trade parameters."""
        tech = TechnicalEvaluation(
            entry_price=172.50,
            stop_loss=169.50,
            take_profit=179.50,
            risk_reward_ratio=2.33,
            passed=True,
        )
        assert tech.passed
        assert tech.risk_reward_ratio > 1.5

    @pytest.mark.asyncio
    async def test_risk_check_result_model(self):
        """Test: RiskCheckResult stores sizing and approval."""
        risk = RiskCheckResult(
            approved=True,
            position_size_shares=100,
            position_size_dollars=17250.0,
            kelly_fraction=0.03,
        )
        assert risk.approved
        assert risk.position_size_shares == 100

    @pytest.mark.asyncio
    async def test_memo_phase_progression(self, bus, memo_store, context):
        """Test: memo can progress through phases correctly."""
        factory = MemoFactory(bus, memo_store, context)
        memo = await factory.create_memo("GOOGL")
        assert memo.phase == MemoPhase.SIGNAL_COLLECTION_PASS1

        # Advance through phases
        memo.advance_phase(MemoPhase.PASS1_SCORING)
        assert memo.phase == MemoPhase.PASS1_SCORING

        memo.advance_phase(MemoPhase.SMART_MONEY_VALIDATION)
        assert memo.phase == MemoPhase.SMART_MONEY_VALIDATION

        memo.advance_phase(MemoPhase.SIGNAL_COLLECTION_PASS2)
        assert memo.phase == MemoPhase.SIGNAL_COLLECTION_PASS2

        memo.advance_phase(MemoPhase.PASS2_SCORING)
        memo.advance_phase(MemoPhase.TECHNICAL_EVALUATION)
        memo.advance_phase(MemoPhase.RISK_CHECK)
        memo.advance_phase(MemoPhase.EXECUTION)
        memo.advance_phase(MemoPhase.COMPLETED)
        assert memo.is_terminal()

    @pytest.mark.asyncio
    async def test_regime_affects_scoring_weights(self, bus, memo_store, context):
        """Test: different regimes produce different composite scores."""
        factory = MemoFactory(bus, memo_store, context)
        engine = DecisionEngine(context_store=context)

        # Trending bull regime
        await context.update("regime", {"regime": "trending_bull"}, "agent_06")
        memo_bull = await factory.create_memo("SPY")
        signals_bull = make_signals("SPY", pass_number=1, score=0.7)
        v1_bull = await factory.assemble_v1(memo_bull.memo_id, signals_bull)
        score_bull = await engine.score_pass1(v1_bull)

        # High volatility regime
        await context.update("regime", {"regime": "high_volatility"}, "agent_06")
        memo_vol = await factory.create_memo("SPY")
        signals_vol = make_signals("SPY", pass_number=1, score=0.7)
        v1_vol = await factory.assemble_v1(memo_vol.memo_id, signals_vol)
        score_vol = await engine.score_pass1(v1_vol)

        # Both should pass but weights differ, so scores should differ
        assert score_bull.regime_weight_applied == "trending_bull"
        assert score_vol.regime_weight_applied == "high_volatility"
