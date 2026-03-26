"""Agent 4: Momentum Bot — VWAP/RSI/MACD technical evaluation.

Evaluates trade setups using technical indicators. Adjusts thresholds
based on regime and volatility context from Agent 6.
Publishes: qe:signals:technicals
Reads context: regime, volatility
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from quantum_edge.core.base_agent import BaseAgent
from quantum_edge.core.config import settings
from quantum_edge.core.message_bus import STREAMS
from quantum_edge.models.events import PipelineEvent, PipelineEventType
from quantum_edge.models.memo import (
    AgentSignal,
    Conviction,
    Direction,
    TechnicalEvaluation,
)
from quantum_edge.models.signals import TechnicalSignal

logger = logging.getLogger(__name__)


def compute_rsi(prices: pd.Series, period: int = 14) -> float:
    """Compute RSI from price series."""
    delta = prices.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else 50.0


def compute_macd(
    prices: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[float, float, float]:
    """Compute MACD value, signal line, and histogram."""
    ema_fast = prices.ewm(span=fast).mean()
    ema_slow = prices.ewm(span=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal).mean()
    histogram = macd_line - signal_line
    return (
        float(macd_line.iloc[-1]),
        float(signal_line.iloc[-1]),
        float(histogram.iloc[-1]),
    )


def compute_bollinger(
    prices: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[float, float, float]:
    """Compute Bollinger Bands upper, lower, and position."""
    sma = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    upper = float((sma + std_dev * std).iloc[-1])
    lower = float((sma - std_dev * std).iloc[-1])
    current = float(prices.iloc[-1])
    position = (current - lower) / (upper - lower) if upper != lower else 0.5
    return upper, lower, position


def compute_atr(
    highs: pd.Series,
    lows: pd.Series,
    closes: pd.Series,
    period: int = 14,
) -> float:
    """Compute Average True Range."""
    tr1 = highs - lows
    tr2 = (highs - closes.shift()).abs()
    tr3 = (lows - closes.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return float(tr.rolling(window=period).mean().iloc[-1])


class MomentumBot(BaseAgent):
    agent_id = "agent_04"
    agent_name = "momentum_bot"
    consumer_group = "cg:agent_04_momentum_bot"
    subscribe_streams = [
        STREAMS["phase"],
        STREAMS["market_data"],
        STREAMS["ctx_regime"],
        STREAMS["ctx_volatility"],
    ]
    cycle_seconds = 30.0

    def __init__(self) -> None:
        super().__init__()
        self._price_data: dict[str, pd.DataFrame] = {}
        self._regime: str = "unknown"
        self._vol_forecast: float = 0.2

    async def on_start(self) -> None:
        logger.info("Momentum Bot agent started")

    async def on_stop(self) -> None:
        pass

    async def on_cycle(self) -> None:
        """Compute technical signals for tracked symbols."""
        # Read latest context
        regime_ctx = await self.get_context("regime")
        self._regime = regime_ctx.get("regime", "unknown")

        vol_ctx = await self.get_context("volatility")
        self._vol_forecast = float(vol_ctx.get("vol_forecast", 0.2))

        for symbol, df in self._price_data.items():
            if len(df) < 30:
                continue

            try:
                signal = self._compute_technicals(symbol, df)
                await self.publish_signal(
                    STREAMS["technicals"],
                    {
                        "agent_id": self.agent_id,
                        "symbol": symbol,
                        "signal_type": "technical",
                        "data": signal.model_dump_json(),
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )
            except Exception:
                logger.exception("Technical computation failed for %s", symbol)

    async def on_message(self, stream: str, msg_id: str, data: dict[str, str]) -> None:
        """Ingest context updates, market data, and pipeline events."""
        import orjson

        if stream == STREAMS["ctx_regime"]:
            ctx_data = orjson.loads(data.get("data", "{}"))
            self._regime = ctx_data.get("regime", self._regime)

        elif stream == STREAMS["ctx_volatility"]:
            ctx_data = orjson.loads(data.get("data", "{}"))
            self._vol_forecast = float(ctx_data.get("vol_forecast", self._vol_forecast))

        elif stream == STREAMS["market_data"]:
            # Ingest market data to populate _price_data
            self._ingest_market_data(data)

        elif stream == STREAMS["phase"]:
            if data.get("event_type", "") != "phase_advance":
                return
            try:
                event_data = orjson.loads(data.get("data", "{}"))
                if isinstance(event_data, str):
                    event_data = orjson.loads(event_data)
                parsed_data = event_data.get("data", event_data)
                to_phase = parsed_data.get("to_phase", "")
            except Exception:
                return

            symbol = data.get("symbol", "")
            memo_id = data.get("memo_id", "")

            if to_phase == "technical_evaluation" and symbol and memo_id:
                # Run technical evaluation
                direction_str = parsed_data.get("direction", "long")
                direction = Direction.LONG if direction_str == "long" else Direction.SHORT
                result = await self.evaluate_trade(symbol, direction)

                from uuid import UUID
                await self.publish_event(PipelineEvent(
                    event_type=PipelineEventType.TECHNICAL_COMPLETE,
                    memo_id=UUID(memo_id),
                    symbol=symbol,
                    agent_id=self.agent_id,
                    data={
                        "passed": result.passed,
                        "entry_price": str(result.entry_price),
                        "stop_loss": str(result.stop_loss),
                        "take_profit": str(result.take_profit),
                        "risk_reward_ratio": str(result.risk_reward_ratio),
                    },
                ))
                logger.info("Technical evaluation for %s: passed=%s, R:R=%.2f",
                            symbol, result.passed, result.risk_reward_ratio)

            elif to_phase in ("signal_collection_pass1", "signal_collection_pass2") and symbol and memo_id:
                # Produce AgentSignal for signal collection
                pass_number = 1 if to_phase == "signal_collection_pass1" else 2
                signal = self._produce_signal(symbol, pass_number)
                if signal:
                    from uuid import UUID
                    await self.publish_event(PipelineEvent(
                        event_type=PipelineEventType.SIGNAL_RECEIVED,
                        memo_id=UUID(memo_id),
                        symbol=symbol,
                        agent_id=self.agent_id,
                        pass_number=pass_number,
                        data={"agent_id": self.agent_id, "symbol": symbol, "signal": signal.model_dump_json()},
                    ))

    def _ingest_market_data(self, data: dict[str, str]) -> None:
        """Ingest a market data signal into _price_data DataFrames."""
        symbol = data.get("symbol", "")
        if not symbol:
            return

        try:
            import orjson
            signal_json = data.get("data", "{}")
            signal_data = orjson.loads(signal_json)

            row = {
                "close": float(signal_data.get("price", 0)),
                "high": float(signal_data.get("daily_high", 0)),
                "low": float(signal_data.get("daily_low", 0)),
                "open": float(signal_data.get("daily_open", 0)),
                "volume": int(signal_data.get("volume", 0)),
                "vwap": float(signal_data.get("vwap", 0)),
            }

            if row["close"] <= 0:
                return

            if symbol not in self._price_data:
                self._price_data[symbol] = pd.DataFrame(columns=["open", "high", "low", "close", "volume", "vwap"])

            self._price_data[symbol] = pd.concat(
                [self._price_data[symbol], pd.DataFrame([row])],
                ignore_index=True,
            )

            # Keep bounded at 500 rows
            if len(self._price_data[symbol]) > 500:
                self._price_data[symbol] = self._price_data[symbol].iloc[-250:]

        except Exception:
            logger.debug("Failed to ingest market data for %s", symbol)

    def _produce_signal(self, symbol: str, pass_number: int) -> AgentSignal | None:
        """Produce an AgentSignal from technicals for signal collection phases."""
        df = self._price_data.get(symbol)
        if df is None or len(df) < 5:
            return None

        closes = df["close"]
        current_price = float(closes.iloc[-1])
        prev_price = float(closes.iloc[-2]) if len(closes) >= 2 else current_price
        momentum = (current_price - prev_price) / prev_price if prev_price > 0 else 0

        if len(df) >= 14:
            rsi = compute_rsi(closes)
            rsi_score = (50 - rsi) / -50  # Normalize: RSI>50 = positive
        else:
            rsi_score = 0.0

        score = max(-1.0, min(1.0, (momentum * 5 + rsi_score) / 2))
        direction = Direction.LONG if score >= 0 else Direction.SHORT
        conviction = Conviction.HIGH if abs(score) > 0.5 else (Conviction.MEDIUM if abs(score) > 0.2 else Conviction.LOW)

        return AgentSignal(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            symbol=symbol,
            direction=direction,
            conviction=conviction,
            score=score,
            pass_number=pass_number,
            rationale=f"Technical momentum: {momentum:.4f}",
        )

    def _compute_technicals(self, symbol: str, df: pd.DataFrame) -> TechnicalSignal:
        """Compute all technical indicators for a symbol."""
        closes = df["close"]
        highs = df["high"]
        lows = df["low"]
        volumes = df["volume"]
        current_price = float(closes.iloc[-1])

        rsi = compute_rsi(closes)
        macd_val, macd_sig, macd_hist = compute_macd(closes)
        bb_upper, bb_lower, bb_pos = compute_bollinger(closes)
        atr = compute_atr(highs, lows, closes)

        # VWAP (simplified — intraday)
        typical_price = (highs + lows + closes) / 3
        cum_vol = volumes.cumsum().iloc[-1]
        if cum_vol > 0:
            vwap = float((typical_price * volumes).cumsum().iloc[-1] / cum_vol)
        elif "vwap" in df.columns and float(df["vwap"].iloc[-1]) > 0:
            vwap = float(df["vwap"].iloc[-1])  # Use ingested VWAP from market data
        else:
            vwap = current_price  # Last resort fallback
        price_vs_vwap = ((current_price - vwap) / vwap * 100) if vwap > 0 else 0

        # ADX (simplified)
        adx = 25.0  # Placeholder — full ADX requires DI+/DI-

        # Volume ratio
        avg_vol = float(volumes.rolling(20).mean().iloc[-1])
        vol_ratio = float(volumes.iloc[-1]) / avg_vol if avg_vol > 0 else 1.0

        return TechnicalSignal(
            symbol=symbol,
            rsi_14=rsi,
            macd_value=macd_val,
            macd_signal=macd_sig,
            macd_histogram=macd_hist,
            vwap=vwap,
            price_vs_vwap=price_vs_vwap,
            bb_upper=bb_upper,
            bb_lower=bb_lower,
            bb_position=bb_pos,
            atr_14=atr,
            adx=adx,
            volume_ratio=vol_ratio,
            timestamp=datetime.utcnow(),
        )

    async def evaluate_trade(
        self,
        symbol: str,
        direction: Direction,
    ) -> TechnicalEvaluation:
        """Full technical evaluation for a proposed trade."""
        df = self._price_data.get(symbol)
        if df is None or len(df) < 30:
            return TechnicalEvaluation(passed=False)

        closes = df["close"]
        highs = df["high"]
        lows = df["low"]
        current_price = float(closes.iloc[-1])

        rsi = compute_rsi(closes)
        macd_val, macd_sig, macd_hist = compute_macd(closes)
        atr = compute_atr(highs, lows, closes)

        # Regime-adjusted thresholds
        rsi_overbought = 75 if self._regime == "trending_bull" else 70
        rsi_oversold = 25 if self._regime == "trending_bear" else 30

        # Score individual signals
        vwap_score = 0.0
        rsi_score = 0.0
        macd_score = 0.0

        if direction == Direction.LONG:
            vwap_score = 1.0 if current_price > self._price_data.get(symbol, pd.DataFrame()).get("vwap", current_price) else -0.5
            rsi_score = 1.0 if rsi_oversold < rsi < rsi_overbought else -1.0
            macd_score = 1.0 if macd_hist > 0 else -0.5
        else:
            vwap_score = 1.0 if current_price < self._price_data.get(symbol, pd.DataFrame()).get("vwap", current_price) else -0.5
            rsi_score = 1.0 if rsi > rsi_overbought else -1.0
            macd_score = 1.0 if macd_hist < 0 else -0.5

        # Volatility-adjusted stop/target (Rule 5: min 2.5:1 R:R)
        vol_multiplier = max(1.0, self._vol_forecast / 0.2)
        stop_distance = atr * 2.0 * vol_multiplier
        target_distance = atr * 5.0 * vol_multiplier  # 5.0x ATR for 2.5:1 R:R

        if direction == Direction.LONG:
            stop_loss = current_price - stop_distance
            take_profit = current_price + target_distance
        else:
            stop_loss = current_price + stop_distance
            take_profit = current_price - target_distance

        rr_ratio = target_distance / stop_distance if stop_distance > 0 else 0

        passed = (
            rr_ratio >= 2.5  # Rule 5: minimum 2.5:1 R:R
            and rsi_score > 0
            and (macd_score > 0 or vwap_score > 0)
        )

        return TechnicalEvaluation(
            vwap_signal=vwap_score,
            rsi_signal=rsi_score,
            macd_signal=macd_score,
            entry_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_reward_ratio=rr_ratio,
            passed=passed,
            timestamp=datetime.utcnow(),
        )


async def main() -> None:
    from quantum_edge.utils.logging import setup_logging

    setup_logging()
    agent = MomentumBot()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
