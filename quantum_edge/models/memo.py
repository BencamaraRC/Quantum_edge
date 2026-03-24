"""Investment Memo — central knowledge object for the pipeline."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MemoPhase(StrEnum):
    """Lifecycle phases of an investment memo."""

    SIGNAL_COLLECTION_PASS1 = "signal_collection_pass1"
    PASS1_SCORING = "pass1_scoring"
    SMART_MONEY_VALIDATION = "smart_money_validation"
    SIGNAL_COLLECTION_PASS2 = "signal_collection_pass2"
    PASS2_SCORING = "pass2_scoring"
    TECHNICAL_EVALUATION = "technical_evaluation"
    RISK_CHECK = "risk_check"
    EXECUTION = "execution"
    POSITION_MONITORING = "position_monitoring"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"


class Direction(StrEnum):
    LONG = "long"
    SHORT = "short"


class Conviction(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class AgentSignal(BaseModel):
    """A signal produced by one agent for a single pass."""

    agent_id: str
    agent_name: str
    symbol: str
    direction: Direction
    conviction: Conviction
    score: float = Field(ge=-1.0, le=1.0)
    pass_number: int = Field(ge=1, le=2)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    rationale: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = ""


class ContextSnapshot(BaseModel):
    """Frozen context state at memo assembly time."""

    regime: dict[str, Any] = Field(default_factory=dict)
    volatility: dict[str, Any] = Field(default_factory=dict)
    macro: dict[str, Any] = Field(default_factory=dict)
    calendar: dict[str, Any] = Field(default_factory=dict)
    portfolio: dict[str, Any] = Field(default_factory=dict)
    captured_at: datetime = Field(default_factory=datetime.utcnow)


class MemoScore(BaseModel):
    """Composite score from the Decision Engine."""

    composite_score: float = Field(ge=0.0, le=1.0)
    direction: Direction
    conviction: Conviction
    regime_weight_applied: str = ""
    component_scores: dict[str, float] = Field(default_factory=dict)
    threshold: float = 0.0
    passed: bool = False
    scored_at: datetime = Field(default_factory=datetime.utcnow)

    # 3-component breakdown (strategy formula)
    agent_signals_component: float = 0.0
    ds_edge_component: float = 0.0
    smart_money_component: float = 0.0
    seasonal_boost: float = 0.0
    all_components_positive: bool = False


class SmartMoneySignal(BaseModel):
    """Agent 7 smart money validation result."""

    score: float = Field(ge=-1.0, le=1.0)
    direction: Direction
    sources: list[str] = Field(default_factory=list)
    unusual_options: list[dict[str, Any]] = Field(default_factory=list)
    institutional_flow: dict[str, Any] = Field(default_factory=dict)
    social_sentiment: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class TechnicalEvaluation(BaseModel):
    """Agent 4 technical evaluation result."""

    vwap_signal: float = 0.0
    rsi_signal: float = 0.0
    macd_signal: float = 0.0
    volume_profile: dict[str, Any] = Field(default_factory=dict)
    support_resistance: dict[str, float] = Field(default_factory=dict)
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_reward_ratio: float = 0.0
    passed: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class RiskCheckResult(BaseModel):
    """Agent 5 risk check result (has veto authority)."""

    approved: bool = False
    veto_reason: str | None = None
    position_size_shares: int = 0
    position_size_dollars: float = 0.0
    kelly_fraction: float = 0.0
    risk_checks: dict[str, bool] = Field(default_factory=dict)
    daily_loss_remaining: float = 0.0
    buying_power_available: float = 0.0
    max_position_pct: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ExecutionResult(BaseModel):
    """Order execution details."""

    order_id: str = ""
    broker: str = "alpaca"
    symbol: str = ""
    side: str = ""
    qty: int = 0
    order_type: str = "bracket"
    entry_price: float | None = None
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    status: str = ""
    filled_at: datetime | None = None
    filled_avg_price: float | None = None
    error: str | None = None


class InvestmentMemo(BaseModel):
    """Central knowledge object assembled through the pipeline.

    Version 1 = Pass 1 signals + frozen context.
    Version 2 = Pass 2 signals + fresh context + smart money.
    """

    memo_id: UUID = Field(default_factory=uuid4)
    symbol: str
    version: int = Field(ge=1, le=2, default=1)
    phase: MemoPhase = MemoPhase.SIGNAL_COLLECTION_PASS1

    # Signals from pass 1 and pass 2
    pass1_signals: list[AgentSignal] = Field(default_factory=list)
    pass2_signals: list[AgentSignal] = Field(default_factory=list)

    # Scores
    pass1_score: MemoScore | None = None
    pass2_score: MemoScore | None = None

    # Smart money validation (between passes)
    smart_money: SmartMoneySignal | None = None

    # Technical evaluation (after pass 2)
    technical_eval: TechnicalEvaluation | None = None

    # Risk check (final gate)
    risk_check: RiskCheckResult | None = None

    # Execution
    execution: ExecutionResult | None = None

    # Frozen context snapshots
    pass1_context: ContextSnapshot | None = None
    pass2_context: ContextSnapshot | None = None

    # Lifecycle timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    # Cancellation / rejection
    cancel_reason: str | None = None

    # Strategy layer fields
    is_satellite: bool = False
    anchor_symbol: str | None = None
    anchor_memo_id: UUID | None = None
    seasonal_boost_applied: float = 0.0
    hypotheses_tested: list[str] = Field(default_factory=list)

    def is_terminal(self) -> bool:
        return self.phase in {
            MemoPhase.COMPLETED,
            MemoPhase.CANCELLED,
            MemoPhase.REJECTED,
            MemoPhase.TIMED_OUT,
        }

    def advance_phase(self, new_phase: MemoPhase) -> None:
        self.phase = new_phase
        self.updated_at = datetime.utcnow()
