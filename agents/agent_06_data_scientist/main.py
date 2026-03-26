"""Agent 6: Data Scientist — HMM regime detection, GARCH volatility, fingerprints.

Core context producer. Publishes regime state and volatility forecasts
that other agents consume for threshold adjustments.
Nightly learning loop at 22:00 ET retrains models.

Publishes: qe:signals:data_science
Updates context: qe:state:regime, qe:state:volatility
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from arch import arch_model

import orjson

from quantum_edge.core.base_agent import BaseAgent
from quantum_edge.core.config import settings
from quantum_edge.core.message_bus import STREAMS
from quantum_edge.models.events import PipelineEvent, PipelineEventType
from quantum_edge.models.memo import AgentSignal, Conviction, Direction
from quantum_edge.models.signals import RegimeSignal

logger = logging.getLogger(__name__)

# HMM regime labels
REGIME_LABELS = {
    0: "trending_bull",
    1: "trending_bear",
    2: "mean_reverting",
    3: "high_volatility",
}


class DataScientist(BaseAgent):
    agent_id = "agent_06"
    agent_name = "data_scientist"
    consumer_group = "cg:agent_06_data_scientist"
    subscribe_streams = [STREAMS["phase"], STREAMS["market_data"]]
    cycle_seconds = 60.0

    def __init__(self) -> None:
        super().__init__()
        self._hmm_model: GaussianHMM | None = None
        self._returns_buffer: list[float] = []  # SPY-only for regime detection
        self._last_prices: dict[str, float] = {}  # per-symbol last price
        self._regime_symbol: str = "SPY"
        self._current_regime: str = "unknown"
        self._vol_forecast: float = 0.0
        self._last_training: datetime | None = None

    async def on_start(self) -> None:
        # Initialize HMM with 4 regimes
        self._hmm_model = GaussianHMM(
            n_components=4,
            covariance_type="full",
            n_iter=100,
            random_state=42,
        )
        logger.info("Data Scientist agent started")

    async def on_stop(self) -> None:
        pass

    async def on_cycle(self) -> None:
        """Run regime detection and volatility forecasting."""
        if len(self._returns_buffer) < 30:
            logger.debug("Insufficient data for regime detection (%d points)", len(self._returns_buffer))
            return

        try:
            returns = np.array(self._returns_buffer[-252:])  # Use up to 1 year

            # ─── HMM Regime Detection ───
            regime_state, regime_prob = self._detect_regime(returns)

            # ─── GARCH Volatility Forecast ───
            vol_forecast, vol_term = self._forecast_volatility(returns)

            # ─── Anomaly Detection ───
            anomaly_score = self._detect_anomaly(returns)

            self._current_regime = REGIME_LABELS.get(regime_state, "unknown")
            self._vol_forecast = vol_forecast

            signal = RegimeSignal(
                regime=self._current_regime,
                regime_probability=float(regime_prob),
                hmm_state=int(regime_state),
                transition_probability=0.0,
                vol_forecast=float(vol_forecast),
                vol_term_structure=vol_term,
                anomaly_score=float(anomaly_score),
                anomaly_detected=anomaly_score > 2.5,
                timestamp=datetime.utcnow(),
            )

            # Publish signal
            await self.publish_signal(
                STREAMS["data_science"],
                {
                    "agent_id": self.agent_id,
                    "signal_type": "regime",
                    "regime": self._current_regime,
                    "regime_probability": str(regime_prob),
                    "vol_forecast": str(vol_forecast),
                    "anomaly_score": str(anomaly_score),
                    "data": signal.model_dump_json(),
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

            # Update context layer (consumed by Agents 4 & 5)
            await self.update_context(
                "regime",
                {
                    "regime": self._current_regime,
                    "regime_probability": regime_prob,
                    "hmm_state": regime_state,
                    "anomaly_detected": anomaly_score > 2.5,
                },
            )

            await self.update_context(
                "volatility",
                {
                    "vol_forecast": vol_forecast,
                    "vol_term_structure": vol_term,
                    "anomaly_score": anomaly_score,
                    "regime": self._current_regime,
                },
            )

        except Exception:
            logger.exception("Regime detection cycle error")

    async def on_message(self, stream: str, msg_id: str, data: dict[str, str]) -> None:
        """Ingest market data for returns buffer and respond to signal collection."""
        if stream == STREAMS["market_data"]:
            try:
                # Agent 2 publishes serialized MarketDataSignal in "data" field
                signal_json = data.get("data", "{}")
                signal_data = orjson.loads(signal_json)
                price = float(signal_data.get("price", 0))
                symbol = signal_data.get("symbol", data.get("symbol", ""))

                if price > 0 and symbol:
                    last = self._last_prices.get(symbol)
                    if last is not None and last > 0:
                        # Only feed SPY returns into the regime/GARCH buffer
                        if symbol == self._regime_symbol:
                            ret = float(np.log(price / last))
                            self._returns_buffer.append(ret)
                            if len(self._returns_buffer) > 5000:
                                self._returns_buffer = self._returns_buffer[-2500:]
                    self._last_prices[symbol] = price
            except (ValueError, KeyError, TypeError):
                pass

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

            if to_phase not in ("signal_collection_pass1", "signal_collection_pass2"):
                return

            symbol = data.get("symbol", "")
            memo_id = data.get("memo_id", "")
            if not symbol or not memo_id:
                return

            pass_number = 1 if to_phase == "signal_collection_pass1" else 2

            # Produce regime-based signal
            if self._current_regime == "trending_bull":
                score = 0.6
                direction = Direction.LONG
            elif self._current_regime == "trending_bear":
                score = -0.6
                direction = Direction.SHORT
            elif self._current_regime == "high_volatility":
                score = -0.3
                direction = Direction.SHORT
            else:
                score = 0.1
                direction = Direction.LONG

            conviction = Conviction.HIGH if abs(score) > 0.5 else Conviction.MEDIUM

            signal = AgentSignal(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                symbol=symbol,
                direction=direction,
                conviction=conviction,
                score=score,
                pass_number=pass_number,
                rationale=f"Regime: {self._current_regime}, vol_forecast: {self._vol_forecast:.4f}",
                metadata={"regime": self._current_regime, "vol_forecast": self._vol_forecast},
            )

            from uuid import UUID
            await self.publish_event(PipelineEvent(
                event_type=PipelineEventType.SIGNAL_RECEIVED,
                memo_id=UUID(memo_id),
                symbol=symbol,
                agent_id=self.agent_id,
                pass_number=pass_number,
                data={"agent_id": self.agent_id, "symbol": symbol, "signal": signal.model_dump_json()},
            ))
            logger.info("Published regime signal for %s (pass %d)", symbol, pass_number)

    def _detect_regime(self, returns: np.ndarray) -> tuple[int, float]:
        """Run HMM regime detection on return series."""
        if self._hmm_model is None:
            return 0, 0.5

        X = returns.reshape(-1, 1)
        try:
            self._hmm_model.fit(X)
            states = self._hmm_model.predict(X)
            probs = self._hmm_model.predict_proba(X)

            current_state = int(states[-1])
            current_prob = float(probs[-1][current_state])
            return current_state, current_prob
        except Exception:
            logger.warning("HMM fitting failed, returning default regime")
            return 0, 0.5

    def _forecast_volatility(self, returns: np.ndarray) -> tuple[float, dict[str, float]]:
        """Run GARCH(1,1) volatility forecast."""
        try:
            scaled_returns = returns * 100  # Scale for GARCH
            model = arch_model(scaled_returns, vol="Garch", p=1, q=1, mean="Zero")
            result = model.fit(disp="off", show_warning=False)

            # Forecast next 5 periods
            forecasts = result.forecast(horizon=5)
            variance = forecasts.variance.iloc[-1].values

            # Annualize: daily vol * sqrt(252)
            daily_vol = np.sqrt(variance[0]) / 100
            annual_vol = float(daily_vol * np.sqrt(252))

            term_structure = {}
            for i, v in enumerate(variance):
                term_structure[f"{i + 1}d"] = float(np.sqrt(v) / 100 * np.sqrt(252))

            return annual_vol, term_structure
        except Exception:
            logger.warning("GARCH fitting failed")
            return 0.2, {"1d": 0.2}

    def _detect_anomaly(self, returns: np.ndarray) -> float:
        """Simple z-score anomaly detection on recent returns."""
        if len(returns) < 20:
            return 0.0
        recent = returns[-5:]
        mean = np.mean(returns[:-5])
        std = np.std(returns[:-5])
        if std == 0:
            return 0.0
        z_scores = np.abs((recent - mean) / std)
        return float(np.max(z_scores))


async def main() -> None:
    from quantum_edge.utils.logging import setup_logging

    setup_logging()
    agent = DataScientist()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
