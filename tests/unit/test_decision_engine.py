"""Unit tests for DecisionEngine."""

import pytest
import fakeredis.aioredis

from quantum_edge.core.context_store import ContextStore
from quantum_edge.core.decision_engine import DecisionEngine
from quantum_edge.models.memo import (
    AgentSignal,
    Conviction,
    Direction,
    InvestmentMemo,
    MemoScore,
)


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest.fixture
async def engine(redis):
    ctx = ContextStore(redis_client=redis)
    return DecisionEngine(context_store=ctx)


def make_signal(agent_id: str, score: float, direction: Direction = Direction.LONG) -> AgentSignal:
    return AgentSignal(
        agent_id=agent_id,
        agent_name=agent_id,
        symbol="AAPL",
        direction=direction,
        conviction=Conviction.HIGH if abs(score) > 0.6 else Conviction.MEDIUM,
        score=score,
        pass_number=1,
    )


class TestDecisionEngine:
    @pytest.mark.asyncio
    async def test_score_empty_signals(self, engine):
        memo = InvestmentMemo(symbol="AAPL")
        score = await engine.score_pass1(memo)
        assert score.composite_score == 0.0
        assert not score.passed

    @pytest.mark.asyncio
    async def test_score_strong_bullish(self, engine):
        memo = InvestmentMemo(symbol="AAPL")
        memo.pass1_signals = [
            make_signal("agent_01", 0.8),
            make_signal("agent_02", 0.9),
            make_signal("agent_03", 0.7),
            make_signal("agent_06", 0.85),
        ]
        score = await engine.score_pass1(memo)
        assert score.composite_score > 0.65
        assert score.passed
        assert score.direction == Direction.LONG

    @pytest.mark.asyncio
    async def test_score_weak_signals(self, engine):
        memo = InvestmentMemo(symbol="AAPL")
        memo.pass1_signals = [
            make_signal("agent_01", 0.1),
            make_signal("agent_02", 0.05),
            make_signal("agent_03", -0.1),
            make_signal("agent_06", 0.0),
        ]
        score = await engine.score_pass1(memo)
        assert not score.passed

    @pytest.mark.asyncio
    async def test_score_mixed_directions(self, engine):
        memo = InvestmentMemo(symbol="AAPL")
        memo.pass1_signals = [
            make_signal("agent_01", 0.8, Direction.LONG),
            make_signal("agent_02", -0.7, Direction.SHORT),
            make_signal("agent_03", 0.5, Direction.LONG),
            make_signal("agent_06", -0.6, Direction.SHORT),
        ]
        score = await engine.score_pass1(memo)
        # Mixed signals should reduce score
        assert score.composite_score < 0.65

    @pytest.mark.asyncio
    async def test_pass2_direction_mismatch(self, engine):
        memo = InvestmentMemo(symbol="AAPL")
        memo.pass1_score = MemoScore(
            composite_score=0.72,
            direction=Direction.LONG,
            conviction=Conviction.HIGH,
            threshold=0.65,
            passed=True,
        )
        memo.pass2_signals = [
            make_signal("agent_01", -0.8, Direction.SHORT),
            make_signal("agent_02", -0.9, Direction.SHORT),
            make_signal("agent_03", -0.7, Direction.SHORT),
            make_signal("agent_06", -0.85, Direction.SHORT),
        ]
        score = await engine.score_pass2(memo)
        # Direction mismatch should fail
        assert not score.passed

    @pytest.mark.asyncio
    async def test_regime_aware_weights(self, engine, redis):
        # Set high volatility regime
        await ContextStore(redis_client=redis).update(
            "regime",
            {"regime": "high_volatility"},
            "agent_06",
        )

        memo = InvestmentMemo(symbol="AAPL")
        memo.pass1_signals = [
            make_signal("agent_01", 0.8),
            make_signal("agent_02", 0.5),
            make_signal("agent_03", 0.7),
            make_signal("agent_06", 0.9),  # Gets highest weight in high_vol
        ]
        score = await engine.score_pass1(memo)
        assert score.regime_weight_applied == "high_volatility"
