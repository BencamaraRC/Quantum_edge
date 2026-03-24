"""Decision Engine — 3-component composite scoring per strategy document.

Composite formula:
  final_score = (agent_signals × 0.60) + (DS_historical_edge × 0.25) + (smart_money × 0.15)

All three components must contribute positively. No single component can
carry the score to 0.75 alone. Seasonal prior boost of +0.05 applies during
AAPL Oct/Nov and GOOGL April validated windows only.
"""

from __future__ import annotations

import logging
from datetime import datetime
from statistics import mean
from typing import Any

from quantum_edge.core.config import settings
from quantum_edge.core.context_store import ContextStore
from quantum_edge.core.strategy import (
    AGENT_SIGNAL_IDS,
    AGENT_SIGNAL_WEIGHTS,
    COMPONENT_WEIGHTS,
    DS_EDGE_AGENT_ID,
    SMART_MONEY_AGENT_ID,
    seasonal_boost,
    tag_hypotheses,
)
from quantum_edge.models.memo import (
    AgentSignal,
    Conviction,
    Direction,
    InvestmentMemo,
    MemoScore,
)

logger = logging.getLogger(__name__)

# Regime-specific adjustments to agent signal sub-weights
REGIME_SIGNAL_OVERRIDES: dict[str, dict[str, float]] = {
    "trending_bull": {
        "agent_02": 0.35,  # Price action more important in trends
        "agent_04": 0.30,
        "agent_01": 0.20,
        "agent_03": 0.15,
    },
    "trending_bear": {
        "agent_01": 0.30,  # News more important in bear markets
        "agent_04": 0.25,
        "agent_02": 0.25,
        "agent_03": 0.20,
    },
    "high_volatility": {
        "agent_02": 0.25,
        "agent_04": 0.30,
        "agent_01": 0.20,
        "agent_03": 0.25,
    },
    "mean_reverting": {
        "agent_04": 0.35,  # Technicals matter most
        "agent_02": 0.30,
        "agent_01": 0.15,
        "agent_03": 0.20,
    },
}


class DecisionEngine:
    """Scores investment memos using the 3-component composite formula."""

    def __init__(self, context_store: ContextStore) -> None:
        self.context = context_store

    async def score_pass1(self, memo: InvestmentMemo) -> MemoScore:
        """Score pass 1 signals. Smart money not yet available — redistributed."""
        return await self._score(
            memo=memo,
            signals=memo.pass1_signals,
            threshold=settings.pass1_threshold,
            pass_label="pass1",
            include_smart_money=False,
        )

    async def score_pass2(self, memo: InvestmentMemo) -> MemoScore:
        """Score pass 2 signals with full 3-component formula + direction check."""
        score = await self._score(
            memo=memo,
            signals=memo.pass2_signals,
            threshold=settings.pass2_threshold,
            pass_label="pass2",
            include_smart_money=True,
        )

        # Direction must match pass 1 (existing rule, kept)
        if memo.pass1_score and score.direction != memo.pass1_score.direction:
            score.passed = False
            score.component_scores["direction_mismatch"] = 1.0
            logger.info(
                "Pass 2 direction mismatch: %s vs pass1 %s",
                score.direction,
                memo.pass1_score.direction,
            )

        return score

    async def _score(
        self,
        memo: InvestmentMemo,
        signals: list[AgentSignal],
        threshold: float,
        pass_label: str,
        include_smart_money: bool,
    ) -> MemoScore:
        """Compute 3-component composite score."""
        if not signals:
            return MemoScore(
                composite_score=0.0,
                direction=Direction.LONG,
                conviction=Conviction.LOW,
                threshold=threshold,
                passed=False,
            )

        # Get current regime
        regime_data = await self.context.get("regime")
        current_regime = regime_data.get("regime", "unknown")

        # ─── Component 1: Agent Signals (60%) ───
        agent_signal_scores = self._compute_agent_signals_component(
            signals, current_regime
        )

        # ─── Component 2: DS Historical Edge (25%) ───
        ds_edge_score = self._compute_ds_edge_component(signals)

        # ─── Component 3: Smart Money (15%) ───
        if include_smart_money:
            smart_money_score = self._compute_smart_money_component(signals, memo)
        else:
            smart_money_score = 0.5  # Neutral when not available

        # ─── Weighted composite ───
        if include_smart_money:
            composite = (
                agent_signal_scores * COMPONENT_WEIGHTS["agent_signals"]
                + ds_edge_score * COMPONENT_WEIGHTS["ds_historical_edge"]
                + smart_money_score * COMPONENT_WEIGHTS["smart_money"]
            )
        else:
            # Redistribute smart money weight to other two components
            agent_w = COMPONENT_WEIGHTS["agent_signals"]
            ds_w = COMPONENT_WEIGHTS["ds_historical_edge"]
            total = agent_w + ds_w
            composite = (
                agent_signal_scores * (agent_w / total)
                + ds_edge_score * (ds_w / total)
            )

        # ─── All-positive gate ───
        # All three components must contribute positively (> 0.5 on [0,1] scale)
        all_positive = (
            agent_signal_scores > 0.5
            and ds_edge_score > 0.5
            and (smart_money_score > 0.5 or not include_smart_money)
        )

        # ─── Seasonal prior boost ───
        now = datetime.utcnow()
        direction = self._determine_direction(signals)
        boost = seasonal_boost(memo.symbol, now.month, direction.value)

        # Rule 8: seasonal boost only if DS edge is positive (fundamentals OK)
        if boost > 0 and ds_edge_score <= 0.5:
            boost = 0.0
            logger.info(
                "Seasonal boost suppressed for %s — DS edge negative", memo.symbol
            )

        # Satellite prior boost
        if memo.is_satellite and memo.anchor_symbol:
            boost += settings.satellite_prior_boost

        composite = min(1.0, composite + boost)

        # ─── Conviction from component agreement ───
        conviction = self._determine_conviction(signals, agent_signal_scores, ds_edge_score, smart_money_score)

        # ─── Pass / fail ───
        passed = composite >= threshold and all_positive

        # Build component scores dict for transparency
        component_scores: dict[str, float] = {}
        for signal in signals:
            component_scores[signal.agent_id] = signal.score

        # Tag hypotheses
        num_positive = sum(
            1 for s in signals if s.score > 0
        )
        hypotheses = tag_hypotheses(
            symbol=memo.symbol,
            regime=current_regime,
            is_sat=memo.is_satellite,
            seasonal_applied=boost > 0,
            num_positive_sources=num_positive,
            composite_score=composite,
        )
        memo.hypotheses_tested = hypotheses
        memo.seasonal_boost_applied = boost

        result = MemoScore(
            composite_score=round(composite, 4),
            direction=direction,
            conviction=conviction,
            regime_weight_applied=current_regime,
            component_scores=component_scores,
            threshold=threshold,
            passed=passed,
            scored_at=datetime.utcnow(),
            agent_signals_component=round(agent_signal_scores, 4),
            ds_edge_component=round(ds_edge_score, 4),
            smart_money_component=round(smart_money_score, 4),
            seasonal_boost=round(boost, 4),
            all_components_positive=all_positive,
        )

        logger.info(
            "%s score: %.4f (agents=%.3f, ds=%.3f, sm=%.3f, boost=%.3f, "
            "all_pos=%s, threshold=%.2f, passed=%s, regime=%s)",
            pass_label,
            composite,
            agent_signal_scores,
            ds_edge_score,
            smart_money_score,
            boost,
            all_positive,
            threshold,
            passed,
            current_regime,
        )

        return result

    def _compute_agent_signals_component(
        self, signals: list[AgentSignal], regime: str
    ) -> float:
        """Compute the agent signals component [0, 1] from agents 01, 02, 03, 04."""
        # Get sub-weights, adjusted for regime
        weights = dict(AGENT_SIGNAL_WEIGHTS)
        if regime in REGIME_SIGNAL_OVERRIDES:
            weights = dict(REGIME_SIGNAL_OVERRIDES[regime])

        # Filter to agent signal agents only
        agent_signals = [s for s in signals if s.agent_id in AGENT_SIGNAL_IDS]
        if not agent_signals:
            return 0.5  # Neutral

        # Normalize weights for present agents
        present = {s.agent_id for s in agent_signals}
        total_weight = sum(weights.get(a, 0.1) for a in present)
        if total_weight == 0:
            return 0.5

        weighted_sum = 0.0
        for signal in agent_signals:
            w = weights.get(signal.agent_id, 0.1) / total_weight
            normalized = (signal.score + 1.0) / 2.0  # [-1,1] → [0,1]
            weighted_sum += normalized * w

        return weighted_sum

    def _compute_ds_edge_component(self, signals: list[AgentSignal]) -> float:
        """Compute the DS historical edge component [0, 1] from Agent 06."""
        ds_signals = [s for s in signals if s.agent_id == DS_EDGE_AGENT_ID]
        if not ds_signals:
            return 0.5  # Neutral when absent
        # Use the most recent signal
        signal = ds_signals[-1]
        return (signal.score + 1.0) / 2.0  # [-1,1] → [0,1]

    def _compute_smart_money_component(
        self, signals: list[AgentSignal], memo: InvestmentMemo
    ) -> float:
        """Compute the smart money component [0, 1] from Agent 07."""
        sm_signals = [s for s in signals if s.agent_id == SMART_MONEY_AGENT_ID]
        if sm_signals:
            signal = sm_signals[-1]
            return (signal.score + 1.0) / 2.0

        # Fall back to SmartMoneySignal on the memo
        if memo.smart_money is not None:
            return (memo.smart_money.score + 1.0) / 2.0

        return 0.5  # Neutral

    def _determine_direction(self, signals: list[AgentSignal]) -> Direction:
        """Determine consensus direction by weighted vote."""
        long_weight = 0.0
        short_weight = 0.0
        for s in signals:
            w = AGENT_SIGNAL_WEIGHTS.get(s.agent_id, 0.1)
            if s.direction == Direction.LONG:
                long_weight += w
            else:
                short_weight += w
        return Direction.LONG if long_weight >= short_weight else Direction.SHORT

    def _determine_conviction(
        self,
        signals: list[AgentSignal],
        agent_comp: float,
        ds_comp: float,
        sm_comp: float,
    ) -> Conviction:
        """Determine conviction from component strengths and signal agreement."""
        scores = [s.score for s in signals]
        if not scores:
            return Conviction.LOW

        avg_abs = mean(abs(s) for s in scores)

        # Factor in component agreement
        components_above = sum(1 for c in [agent_comp, ds_comp, sm_comp] if c > 0.6)

        if avg_abs >= 0.8 or components_above == 3:
            return Conviction.VERY_HIGH
        if avg_abs >= 0.6 or components_above >= 2:
            return Conviction.HIGH
        if avg_abs >= 0.4:
            return Conviction.MEDIUM
        return Conviction.LOW
