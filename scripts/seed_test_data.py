"""Seed test data — populates Redis + TimescaleDB with realistic investment memos."""

from __future__ import annotations

import asyncio
import random
import sys
from datetime import datetime, timedelta
from uuid import uuid4

from quantum_edge.core.config import settings
from quantum_edge.core.context_store import ContextStore
from quantum_edge.core.memo_store import MemoStore
from quantum_edge.core.message_bus import MessageBus
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

# ─── Agent metadata ───

AGENTS = [
    ("agent_01", "News Scanner"),
    ("agent_02", "Market Data"),
    ("agent_03", "Events Engine"),
    ("agent_04", "Momentum Bot"),
    ("agent_05", "Risk Guard"),
    ("agent_06", "Data Scientist"),
    ("agent_07", "Smart Money"),
]

RATIONALES = {
    "agent_01": [
        "Strong positive sentiment across major financial outlets",
        "Mixed news coverage; earnings guidance lifted slightly",
        "Negative press on regulatory concerns",
        "Bullish analyst upgrades from Goldman and JPMorgan",
    ],
    "agent_02": [
        "Volume 2.3x 20-day average; price above VWAP",
        "Consolidation near resistance; declining volume",
        "Breakout above 50-day MA on heavy volume",
        "Gap down on earnings miss; selling pressure evident",
    ],
    "agent_03": [
        "Earnings in 3 days; implied vol elevated",
        "No near-term catalysts; low event risk",
        "Fed meeting this week; sector rotation expected",
        "Product launch event scheduled; call skew rising",
    ],
    "agent_04": [
        "RSI 62, MACD bullish crossover, VWAP reclaimed",
        "Momentum fading; RSI divergence at 71",
        "Strong trend continuation; all MAs aligned bullish",
        "Bearish engulfing on daily; momentum shifting",
    ],
    "agent_05": [
        "Position within risk limits; Kelly fraction 0.04",
        "Correlated exposure at 12%; within threshold",
        "Daily loss budget sufficient; no circuit breaker risk",
        "VETOED: correlated tech exposure exceeds 15% limit",
    ],
    "agent_06": [
        "Regime: Trending Bull (p=0.82); vol forecast 14.2%",
        "HMM state 2: mean-reverting; reduced conviction",
        "Anomaly score low; standard market conditions",
        "Regime shift detected; transitioning to high-vol",
    ],
    "agent_07": [
        "Unusual call sweep: $2.1M Jan 200C; institutional accumulation",
        "Dark pool prints above ask; smart money buying",
        "Options flow neutral; no unusual activity",
        "Put/call ratio spiking; hedging activity detected",
    ],
}


def make_signal(
    agent_id: str,
    agent_name: str,
    symbol: str,
    direction: Direction,
    score: float,
    pass_number: int,
) -> AgentSignal:
    return AgentSignal(
        agent_id=agent_id,
        agent_name=agent_name,
        symbol=symbol,
        direction=direction,
        conviction=_score_to_conviction(score),
        score=score,
        pass_number=pass_number,
        rationale=random.choice(RATIONALES.get(agent_id, ["Signal generated"])),
        idempotency_key=f"{agent_id}-{symbol}-p{pass_number}-{uuid4().hex[:8]}",
    )


def _score_to_conviction(score: float) -> Conviction:
    abs_score = abs(score)
    if abs_score >= 0.8:
        return Conviction.VERY_HIGH
    if abs_score >= 0.6:
        return Conviction.HIGH
    if abs_score >= 0.4:
        return Conviction.MEDIUM
    return Conviction.LOW


def make_signals(symbol: str, direction: Direction, base_score: float, pass_number: int) -> list[AgentSignal]:
    signals = []
    for agent_id, agent_name in AGENTS:
        noise = random.uniform(-0.15, 0.15)
        score = max(-1.0, min(1.0, base_score + noise))
        if direction == Direction.SHORT:
            score = -abs(score)
        signals.append(make_signal(agent_id, agent_name, symbol, direction, score, pass_number))
    return signals


def make_score(direction: Direction, composite: float, threshold: float) -> MemoScore:
    return MemoScore(
        composite_score=composite,
        direction=direction,
        conviction=_score_to_conviction(composite),
        regime_weight_applied="trending_bull",
        component_scores={
            "news": round(random.uniform(0.5, 0.9), 2),
            "market_data": round(random.uniform(0.5, 0.9), 2),
            "events": round(random.uniform(0.3, 0.7), 2),
            "momentum": round(random.uniform(0.5, 0.9), 2),
            "risk": round(random.uniform(0.4, 0.8), 2),
            "data_science": round(random.uniform(0.5, 0.9), 2),
            "smart_money": round(random.uniform(0.4, 0.9), 2),
        },
        threshold=threshold,
        passed=composite >= threshold,
    )


def make_context_snapshot() -> ContextSnapshot:
    return ContextSnapshot(
        regime={"regime": "trending_bull", "probability": 0.82, "hmm_state": 1},
        volatility={"vix": 14.2, "realized_30d": 12.8, "forecast": 15.1},
        macro={"gdp_growth": 2.8, "unemployment": 3.7, "cpi_yoy": 3.1, "fed_rate": 5.25},
        calendar={"next_fomc": "2026-04-02", "earnings_this_week": ["AAPL", "MSFT", "AMZN"]},
        portfolio={
            "equity": 102450.75,
            "cash": 76838.06,
            "buying_power": 76838.06,
            "daily_pnl": 1250.30,
            "open_positions": 4,
        },
    )


# ─── Memo builders ───

def build_active_memos() -> list[InvestmentMemo]:
    now = datetime.utcnow()
    memos = []

    # NVDA — just started, collecting pass 1 signals
    m = InvestmentMemo(
        symbol="NVDA",
        phase=MemoPhase.SIGNAL_COLLECTION_PASS1,
        pass1_signals=make_signals("NVDA", Direction.LONG, 0.72, 1)[:3],
        pass1_context=make_context_snapshot(),
        created_at=now - timedelta(minutes=1),
        updated_at=now - timedelta(seconds=30),
    )
    memos.append(m)

    # MSFT — past pass 1, awaiting smart money validation
    m = InvestmentMemo(
        symbol="MSFT",
        phase=MemoPhase.SMART_MONEY_VALIDATION,
        pass1_signals=make_signals("MSFT", Direction.LONG, 0.74, 1),
        pass1_score=make_score(Direction.LONG, 0.74, 0.65),
        pass1_context=make_context_snapshot(),
        created_at=now - timedelta(minutes=5),
        updated_at=now - timedelta(minutes=2),
    )
    memos.append(m)

    # AAPL — deep in pipeline, at technical evaluation
    m = InvestmentMemo(
        symbol="AAPL",
        phase=MemoPhase.TECHNICAL_EVALUATION,
        version=2,
        pass1_signals=make_signals("AAPL", Direction.LONG, 0.78, 1),
        pass2_signals=make_signals("AAPL", Direction.LONG, 0.81, 2),
        pass1_score=make_score(Direction.LONG, 0.78, 0.65),
        pass2_score=make_score(Direction.LONG, 0.81, 0.75),
        smart_money=SmartMoneySignal(
            score=0.76,
            direction=Direction.LONG,
            sources=["unusual_whales", "options_flow"],
            unusual_options=[{"strike": 200, "expiry": "2026-04-18", "premium": 2100000, "type": "call_sweep"}],
            institutional_flow={"net_buying": 15200000, "dark_pool_pct": 0.42},
            social_sentiment={"score": 0.68, "volume": "high"},
        ),
        pass1_context=make_context_snapshot(),
        pass2_context=make_context_snapshot(),
        created_at=now - timedelta(minutes=8),
        updated_at=now - timedelta(minutes=1),
    )
    memos.append(m)

    # PLTR — at risk check gate
    m = InvestmentMemo(
        symbol="PLTR",
        phase=MemoPhase.RISK_CHECK,
        version=2,
        pass1_signals=make_signals("PLTR", Direction.LONG, 0.69, 1),
        pass2_signals=make_signals("PLTR", Direction.LONG, 0.77, 2),
        pass1_score=make_score(Direction.LONG, 0.69, 0.65),
        pass2_score=make_score(Direction.LONG, 0.77, 0.75),
        smart_money=SmartMoneySignal(
            score=0.62,
            direction=Direction.LONG,
            sources=["options_flow"],
            institutional_flow={"net_buying": 4800000, "dark_pool_pct": 0.31},
        ),
        technical_eval=TechnicalEvaluation(
            vwap_signal=0.7,
            rsi_signal=0.6,
            macd_signal=0.8,
            entry_price=26.50,
            stop_loss=25.10,
            take_profit=29.80,
            risk_reward_ratio=2.36,
            passed=True,
        ),
        pass1_context=make_context_snapshot(),
        pass2_context=make_context_snapshot(),
        created_at=now - timedelta(minutes=10),
        updated_at=now - timedelta(seconds=45),
    )
    memos.append(m)

    return memos


def build_terminal_memos() -> list[InvestmentMemo]:
    now = datetime.utcnow()
    memos = []

    # META — completed successfully, trade executed
    m = InvestmentMemo(
        symbol="META",
        phase=MemoPhase.COMPLETED,
        version=2,
        pass1_signals=make_signals("META", Direction.LONG, 0.76, 1),
        pass2_signals=make_signals("META", Direction.LONG, 0.83, 2),
        pass1_score=make_score(Direction.LONG, 0.76, 0.65),
        pass2_score=make_score(Direction.LONG, 0.83, 0.75),
        smart_money=SmartMoneySignal(score=0.71, direction=Direction.LONG, sources=["dark_pool"]),
        technical_eval=TechnicalEvaluation(
            entry_price=505.20, stop_loss=498.00, take_profit=520.00,
            risk_reward_ratio=2.06, passed=True,
        ),
        risk_check=RiskCheckResult(
            approved=True, position_size_shares=30, position_size_dollars=15156.00,
            kelly_fraction=0.038, daily_loss_remaining=4800.0, buying_power_available=76000.0,
        ),
        execution=ExecutionResult(
            order_id="ord_meta_001", symbol="META", side="buy", qty=30,
            entry_price=505.20, stop_loss_price=498.00, take_profit_price=520.00,
            status="filled", filled_avg_price=505.35,
        ),
        pass1_context=make_context_snapshot(),
        pass2_context=make_context_snapshot(),
        created_at=now - timedelta(hours=2),
        updated_at=now - timedelta(hours=1, minutes=55),
        completed_at=now - timedelta(hours=1, minutes=55),
    )
    memos.append(m)

    # AMD — completed
    m = InvestmentMemo(
        symbol="AMD",
        phase=MemoPhase.COMPLETED,
        version=2,
        pass1_signals=make_signals("AMD", Direction.LONG, 0.71, 1),
        pass2_signals=make_signals("AMD", Direction.LONG, 0.79, 2),
        pass1_score=make_score(Direction.LONG, 0.71, 0.65),
        pass2_score=make_score(Direction.LONG, 0.79, 0.75),
        smart_money=SmartMoneySignal(score=0.65, direction=Direction.LONG, sources=["options_flow"]),
        technical_eval=TechnicalEvaluation(
            entry_price=120.50, stop_loss=117.00, take_profit=128.00,
            risk_reward_ratio=2.14, passed=True,
        ),
        risk_check=RiskCheckResult(approved=True, position_size_shares=40, position_size_dollars=4820.00),
        execution=ExecutionResult(
            order_id="ord_amd_001", symbol="AMD", side="buy", qty=40,
            entry_price=120.50, status="filled", filled_avg_price=120.55,
        ),
        pass1_context=make_context_snapshot(),
        pass2_context=make_context_snapshot(),
        created_at=now - timedelta(hours=3),
        updated_at=now - timedelta(hours=2, minutes=45),
        completed_at=now - timedelta(hours=2, minutes=45),
    )
    memos.append(m)

    # GOOGL — completed
    m = InvestmentMemo(
        symbol="GOOGL",
        phase=MemoPhase.COMPLETED,
        version=2,
        pass1_signals=make_signals("GOOGL", Direction.LONG, 0.73, 1),
        pass2_signals=make_signals("GOOGL", Direction.LONG, 0.80, 2),
        pass1_score=make_score(Direction.LONG, 0.73, 0.65),
        pass2_score=make_score(Direction.LONG, 0.80, 0.75),
        smart_money=SmartMoneySignal(score=0.69, direction=Direction.LONG, sources=["dark_pool"]),
        technical_eval=TechnicalEvaluation(
            entry_price=140.00, stop_loss=136.50, take_profit=148.00,
            risk_reward_ratio=2.29, passed=True,
        ),
        risk_check=RiskCheckResult(approved=True, position_size_shares=25, position_size_dollars=3500.00),
        execution=ExecutionResult(
            order_id="ord_googl_001", symbol="GOOGL", side="buy", qty=25,
            entry_price=140.00, status="filled", filled_avg_price=140.10,
        ),
        pass1_context=make_context_snapshot(),
        pass2_context=make_context_snapshot(),
        created_at=now - timedelta(hours=4),
        updated_at=now - timedelta(hours=3, minutes=50),
        completed_at=now - timedelta(hours=3, minutes=50),
    )
    memos.append(m)

    # TSLA — rejected at risk check (correlated exposure)
    m = InvestmentMemo(
        symbol="TSLA",
        phase=MemoPhase.REJECTED,
        version=2,
        pass1_signals=make_signals("TSLA", Direction.SHORT, -0.68, 1),
        pass2_signals=make_signals("TSLA", Direction.SHORT, -0.76, 2),
        pass1_score=make_score(Direction.SHORT, 0.68, 0.65),
        pass2_score=make_score(Direction.SHORT, 0.76, 0.75),
        smart_money=SmartMoneySignal(score=-0.55, direction=Direction.SHORT, sources=["options_flow"]),
        technical_eval=TechnicalEvaluation(
            entry_price=252.00, stop_loss=258.00, take_profit=240.00,
            risk_reward_ratio=2.0, passed=True,
        ),
        risk_check=RiskCheckResult(
            approved=False,
            veto_reason="Correlated EV sector exposure at 16.2% exceeds 15% limit",
            position_size_shares=15, position_size_dollars=3780.00,
        ),
        pass1_context=make_context_snapshot(),
        pass2_context=make_context_snapshot(),
        created_at=now - timedelta(hours=1, minutes=30),
        updated_at=now - timedelta(hours=1, minutes=25),
        completed_at=now - timedelta(hours=1, minutes=25),
        cancel_reason="Risk check veto: correlated exposure limit exceeded",
    )
    memos.append(m)

    # SOFI — rejected at pass 1 scoring (score too low)
    m = InvestmentMemo(
        symbol="SOFI",
        phase=MemoPhase.REJECTED,
        version=1,
        pass1_signals=make_signals("SOFI", Direction.LONG, 0.52, 1),
        pass1_score=make_score(Direction.LONG, 0.52, 0.65),
        pass1_context=make_context_snapshot(),
        created_at=now - timedelta(hours=5),
        updated_at=now - timedelta(hours=4, minutes=55),
        completed_at=now - timedelta(hours=4, minutes=55),
        cancel_reason="Pass 1 score 0.52 below threshold 0.65",
    )
    memos.append(m)

    # COIN — timed out during signal collection
    m = InvestmentMemo(
        symbol="COIN",
        phase=MemoPhase.TIMED_OUT,
        version=1,
        pass1_signals=make_signals("COIN", Direction.LONG, 0.45, 1)[:2],
        pass1_context=make_context_snapshot(),
        created_at=now - timedelta(hours=6),
        updated_at=now - timedelta(hours=5, minutes=58),
        completed_at=now - timedelta(hours=5, minutes=58),
        cancel_reason="Signal collection timed out after 120s (only 2/7 agents responded)",
    )
    memos.append(m)

    return memos


# ─── Seed functions ───

async def seed_context(ctx: ContextStore) -> None:
    """Populate the context layer with realistic market state."""
    await ctx.update("regime", {
        "regime": "trending_bull",
        "probability": 0.82,
        "hmm_state": 1,
        "vol_forecast": 14.2,
        "anomaly_detected": False,
        "updated_at": datetime.utcnow().isoformat(),
    }, agent_id="agent_06")

    await ctx.update("volatility", {
        "vix": 14.2,
        "vix_change": -0.8,
        "realized_30d": 12.8,
        "realized_10d": 11.5,
        "forecast_5d": 15.1,
        "term_structure": "contango",
    }, agent_id="agent_06")

    await ctx.update("macro", {
        "gdp_growth": 2.8,
        "unemployment": 3.7,
        "cpi_yoy": 3.1,
        "fed_rate": 5.25,
        "next_fomc": "2026-04-02",
        "sentiment": "cautiously_optimistic",
    }, agent_id="agent_03")

    await ctx.update("calendar", {
        "earnings_this_week": ["AAPL", "MSFT", "AMZN", "GOOGL"],
        "economic_events": [
            {"date": "2026-03-24", "event": "Durable Goods Orders"},
            {"date": "2026-03-25", "event": "Consumer Confidence"},
            {"date": "2026-03-27", "event": "GDP Final Q4"},
        ],
        "ex_dividend": ["JPM", "BAC"],
    }, agent_id="agent_03")

    await ctx.update("portfolio", {
        "equity": 102450.75,
        "cash": 76838.06,
        "buying_power": 76838.06,
        "daily_pnl": 1250.30,
        "daily_pnl_pct": 1.24,
        "open_positions": 4,
        "total_exposure_pct": 25.0,
        "circuit_breaker_active": False,
    }, agent_id="agent_05")

    print("  Context layer seeded (regime, volatility, macro, calendar, portfolio)")


async def seed_memos_redis(redis_client) -> None:
    """Write memos directly to Redis (no TimescaleDB required)."""
    from quantum_edge.core.memo_store import MEMO_KEY_PREFIX, MEMO_TTL

    active = build_active_memos()
    terminal = build_terminal_memos()
    all_memos = active + terminal

    for memo in all_memos:
        key = f"{MEMO_KEY_PREFIX}{memo.memo_id}"
        await redis_client.set(key, memo.model_dump_json(), ex=int(MEMO_TTL.total_seconds()))
        status = "ACTIVE" if not memo.is_terminal() else memo.phase.value.upper()
        print(f"  {memo.symbol:6s} | {memo.phase.value:30s} | {status}")

    print(f"  Total: {len(active)} active + {len(terminal)} terminal = {len(all_memos)} memos")


async def main() -> None:
    print("Quantum Edge — Seeding test data (Redis-only)")
    print("=" * 50)

    # Connect to Redis
    bus = MessageBus()
    await bus.connect()
    ctx = ContextStore(redis_client=bus.redis)

    # Initialize Redis streams
    print("\n1. Initializing Redis streams...")
    from infrastructure.scripts.init_redis_streams import init_streams
    await init_streams(settings.redis_url)

    # Seed context layer
    print("\n2. Seeding context layer...")
    await seed_context(ctx)

    # Seed memos to Redis
    print("\n3. Seeding investment memos...")
    await seed_memos_redis(bus.redis)

    # Verify via Redis scan
    print("\n" + "=" * 50)
    from quantum_edge.core.memo_store import MEMO_KEY_PREFIX
    keys = [k async for k in bus.redis.scan_iter(match=f"{MEMO_KEY_PREFIX}*")]
    print(f"Verification: {len(keys)} memos in Redis")
    print("Seed complete!")

    await bus.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
