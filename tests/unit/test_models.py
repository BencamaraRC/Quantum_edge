"""Unit tests for Pydantic models."""

from datetime import datetime
from uuid import uuid4

import pytest

from quantum_edge.models.memo import (
    AgentSignal,
    ContextSnapshot,
    Conviction,
    Direction,
    ExecutionResult,
    InvestmentMemo,
    MemoPhase,
    MemoScore,
    RiskCheckResult,
    SmartMoneySignal,
    TechnicalEvaluation,
)
from quantum_edge.models.portfolio import PortfolioState, Position
from quantum_edge.models.signals import (
    EventSignal,
    MarketDataSignal,
    NewsSignal,
    RegimeSignal,
    TechnicalSignal,
)
from quantum_edge.models.events import (
    ContextUpdateEvent,
    PipelineEvent,
    PipelineEventType,
)


class TestInvestmentMemo:
    def test_create_memo(self):
        memo = InvestmentMemo(symbol="AAPL")
        assert memo.symbol == "AAPL"
        assert memo.version == 1
        assert memo.phase == MemoPhase.SIGNAL_COLLECTION_PASS1
        assert not memo.is_terminal()

    def test_advance_phase(self):
        memo = InvestmentMemo(symbol="AAPL")
        memo.advance_phase(MemoPhase.PASS1_SCORING)
        assert memo.phase == MemoPhase.PASS1_SCORING

    def test_is_terminal(self):
        memo = InvestmentMemo(symbol="AAPL")
        assert not memo.is_terminal()
        memo.advance_phase(MemoPhase.COMPLETED)
        assert memo.is_terminal()

    def test_terminal_phases(self):
        for phase in [MemoPhase.COMPLETED, MemoPhase.CANCELLED, MemoPhase.REJECTED, MemoPhase.TIMED_OUT]:
            memo = InvestmentMemo(symbol="AAPL", phase=phase)
            assert memo.is_terminal()

    def test_memo_serialization(self):
        memo = InvestmentMemo(symbol="NVDA")
        json_str = memo.model_dump_json()
        restored = InvestmentMemo.model_validate_json(json_str)
        assert restored.symbol == "NVDA"
        assert restored.memo_id == memo.memo_id


class TestAgentSignal:
    def test_create_signal(self):
        signal = AgentSignal(
            agent_id="agent_01",
            agent_name="news_scanner",
            symbol="TSLA",
            direction=Direction.LONG,
            conviction=Conviction.HIGH,
            score=0.85,
            pass_number=1,
        )
        assert signal.score == 0.85
        assert signal.direction == Direction.LONG

    def test_score_bounds(self):
        with pytest.raises(Exception):
            AgentSignal(
                agent_id="agent_01",
                agent_name="news_scanner",
                symbol="TSLA",
                direction=Direction.LONG,
                conviction=Conviction.HIGH,
                score=1.5,  # Out of bounds
                pass_number=1,
            )


class TestMemoScore:
    def test_create_score(self):
        score = MemoScore(
            composite_score=0.72,
            direction=Direction.LONG,
            conviction=Conviction.HIGH,
            threshold=0.65,
            passed=True,
        )
        assert score.passed
        assert score.composite_score == 0.72


class TestContextSnapshot:
    def test_empty_snapshot(self):
        snap = ContextSnapshot()
        assert snap.regime == {}
        assert snap.portfolio == {}


class TestPortfolioState:
    def test_portfolio_with_positions(self):
        pos = Position(
            symbol="AAPL",
            qty=100,
            side="long",
            avg_entry_price=150.0,
            current_price=155.0,
            market_value=15500.0,
            unrealized_pl=500.0,
            unrealized_pl_pct=3.33,
            cost_basis=15000.0,
        )
        portfolio = PortfolioState(
            equity=100000.0,
            cash=84500.0,
            buying_power=169000.0,
            portfolio_value=100000.0,
            positions=[pos],
        )
        assert portfolio.has_position("AAPL")
        assert not portfolio.has_position("MSFT")
        assert portfolio.position_for("AAPL") is not None

    def test_to_context_dict(self):
        portfolio = PortfolioState(
            equity=100000.0,
            cash=50000.0,
            buying_power=100000.0,
            portfolio_value=100000.0,
        )
        ctx = portfolio.to_context_dict()
        assert ctx["equity"] == "100000.0"
        assert ctx["circuit_breaker_active"] == "False"


class TestPipelineEvent:
    def test_serialize_deserialize(self):
        event = PipelineEvent(
            event_type=PipelineEventType.SIGNAL_RECEIVED,
            memo_id=uuid4(),
            symbol="AAPL",
            agent_id="agent_01",
            pass_number=1,
        )
        stream_dict = event.to_stream_dict()
        restored = PipelineEvent.from_stream_dict(stream_dict)
        assert restored.event_type == PipelineEventType.SIGNAL_RECEIVED
        assert restored.symbol == "AAPL"
        assert restored.agent_id == "agent_01"

    def test_context_update_event(self):
        event = ContextUpdateEvent(
            domain="regime",
            agent_id="agent_06",
            data={"regime": "trending_bull", "probability": 0.85},
        )
        stream_dict = event.to_stream_dict()
        restored = ContextUpdateEvent.from_stream_dict(stream_dict)
        assert restored.domain == "regime"
        assert restored.data["regime"] == "trending_bull"


class TestSignalModels:
    def test_news_signal(self):
        signal = NewsSignal(
            symbol="AAPL",
            headline="Apple beats earnings expectations",
            source="reuters",
            sentiment_score=0.85,
            sentiment_label="positive",
            relevance_score=0.9,
            finbert_confidence=0.92,
            published_at=datetime.utcnow(),
        )
        assert signal.sentiment_score == 0.85

    def test_regime_signal(self):
        signal = RegimeSignal(
            regime="trending_bull",
            regime_probability=0.85,
            hmm_state=0,
            transition_probability=0.1,
            vol_forecast=0.18,
        )
        assert signal.regime == "trending_bull"

    def test_technical_signal(self):
        signal = TechnicalSignal(
            symbol="AAPL",
            rsi_14=55.0,
            macd_value=1.5,
            macd_signal=1.2,
            macd_histogram=0.3,
            vwap=150.0,
            price_vs_vwap=0.5,
            bb_upper=155.0,
            bb_lower=145.0,
            bb_position=0.5,
            atr_14=3.0,
            adx=25.0,
            volume_ratio=1.2,
        )
        assert signal.rsi_14 == 55.0


class TestRiskCheckResult:
    def test_approved(self):
        result = RiskCheckResult(
            approved=True,
            position_size_shares=50,
            position_size_dollars=7500.0,
            kelly_fraction=0.03,
            risk_checks={"circuit_breaker": True, "daily_loss_limit": True},
        )
        assert result.approved
        assert result.position_size_shares == 50

    def test_vetoed(self):
        result = RiskCheckResult(
            approved=False,
            veto_reason="Daily loss limit exhausted",
            risk_checks={"daily_loss_limit": False},
        )
        assert not result.approved
        assert result.veto_reason is not None
