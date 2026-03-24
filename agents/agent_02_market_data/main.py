"""Agent 2: Market Data — Price/volume/technicals data pipeline (30s cycle).

Simplest agent — pure data collection. Feeds price action to the pipeline.
Publishes: qe:signals:market_data
Context: None (consumer only)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live import StockDataStream
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame

from quantum_edge.core.base_agent import BaseAgent
from quantum_edge.core.config import settings
from quantum_edge.core.message_bus import STREAMS
from quantum_edge.models.events import PipelineEvent, PipelineEventType
from quantum_edge.models.memo import AgentSignal, Conviction, Direction
from quantum_edge.core.strategy import FULL_UNIVERSE
from quantum_edge.models.signals import MarketDataSignal

logger = logging.getLogger(__name__)

# Strategy universe — Mag 7 + all satellite clusters + SPY/QQQ for regime context
DEFAULT_WATCHLIST = sorted(set(FULL_UNIVERSE + ["SPY", "QQQ", "VIXY"]))


class MarketDataAgent(BaseAgent):
    agent_id = "agent_02"
    agent_name = "market_data"
    consumer_group = "cg:agent_02_market_data"
    subscribe_streams = [STREAMS["phase"]]  # Listen for pipeline phase events
    cycle_seconds = 30.0

    def __init__(self) -> None:
        super().__init__()
        self._data_client: StockHistoricalDataClient | None = None
        self._watchlist: list[str] = DEFAULT_WATCHLIST

    async def on_start(self) -> None:
        self._data_client = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
        logger.info("Market Data agent started with %d symbols", len(self._watchlist))

    async def on_stop(self) -> None:
        self._data_client = None

    async def on_cycle(self) -> None:
        """Fetch latest quotes and publish market data signals."""
        if self._data_client is None:
            return

        try:
            # Get latest quotes for watchlist
            request = StockLatestQuoteRequest(symbol_or_symbols=self._watchlist)
            quotes = self._data_client.get_stock_latest_quote(request)

            # Get latest bars for volume/VWAP
            bars_request = StockBarsRequest(
                symbol_or_symbols=self._watchlist,
                timeframe=TimeFrame.Minute,
                limit=1,
            )
            bars = self._data_client.get_stock_bars(bars_request)

            for symbol in self._watchlist:
                quote = quotes.get(symbol)
                bar_data = bars[symbol] if symbol in bars else None
                if quote is None:
                    continue

                latest_bar = bar_data[-1] if bar_data else None

                signal = MarketDataSignal(
                    symbol=symbol,
                    price=float(quote.ask_price + quote.bid_price) / 2,
                    volume=int(latest_bar.volume) if latest_bar else 0,
                    vwap=float(latest_bar.vwap) if latest_bar and hasattr(latest_bar, "vwap") else 0,
                    bid=float(quote.bid_price),
                    ask=float(quote.ask_price),
                    spread=float(quote.ask_price - quote.bid_price),
                    daily_high=float(latest_bar.high) if latest_bar else 0,
                    daily_low=float(latest_bar.low) if latest_bar else 0,
                    daily_open=float(latest_bar.open) if latest_bar else 0,
                    prev_close=0,  # Computed from daily bars
                    change_pct=0,
                    relative_volume=1.0,
                    timestamp=datetime.utcnow(),
                )

                await self.publish_signal(
                    STREAMS["market_data"],
                    {
                        "agent_id": self.agent_id,
                        "symbol": symbol,
                        "signal_type": "market_data",
                        "data": signal.model_dump_json(),
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )

        except Exception:
            logger.exception("Market data cycle error")

    async def on_message(self, stream: str, msg_id: str, data: dict[str, str]) -> None:
        """Respond to signal collection phase events."""
        if stream != STREAMS["phase"]:
            return
        if data.get("event_type", "") != "phase_advance":
            return

        import orjson
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
        signal = await self._produce_signal(symbol, pass_number)
        if signal is None:
            return

        from uuid import UUID
        await self.publish_event(PipelineEvent(
            event_type=PipelineEventType.SIGNAL_RECEIVED,
            memo_id=UUID(memo_id),
            symbol=symbol,
            agent_id=self.agent_id,
            pass_number=pass_number,
            data={"agent_id": self.agent_id, "symbol": symbol},
        ))
        logger.info("Published signal for %s (pass %d, memo %s)", symbol, pass_number, memo_id)

    async def _produce_signal(self, symbol: str, pass_number: int) -> AgentSignal | None:
        """Produce an AgentSignal for the given symbol from latest market data."""
        if self._data_client is None:
            return None

        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
            quotes = self._data_client.get_stock_latest_quote(request)
            quote = quotes.get(symbol)
            if quote is None:
                return None

            mid_price = float(quote.ask_price + quote.bid_price) / 2
            spread = float(quote.ask_price - quote.bid_price)
            spread_pct = (spread / mid_price * 100) if mid_price > 0 else 0

            # Get recent bars for momentum assessment
            bars_request = StockBarsRequest(
                symbol_or_symbols=[symbol],
                timeframe=TimeFrame.Minute,
                limit=30,
            )
            bars = self._data_client.get_stock_bars(bars_request)
            bar_list = bars[symbol] if symbol in bars else []

            if len(bar_list) >= 2:
                recent_close = float(bar_list[-1].close)
                earlier_close = float(bar_list[0].close)
                momentum = (recent_close - earlier_close) / earlier_close if earlier_close != 0 else 0.0
            else:
                momentum = 0.0

            # Score based on price momentum
            score = max(-1.0, min(1.0, momentum * 10))  # Scale momentum to [-1, 1]
            direction = Direction.LONG if score >= 0 else Direction.SHORT
            abs_score = abs(score)
            if abs_score >= 0.6:
                conviction = Conviction.HIGH
            elif abs_score >= 0.3:
                conviction = Conviction.MEDIUM
            else:
                conviction = Conviction.LOW

            return AgentSignal(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                symbol=symbol,
                direction=direction,
                conviction=conviction,
                score=score,
                pass_number=pass_number,
                rationale=f"Price momentum: {momentum:.4f}, spread: {spread_pct:.3f}%",
                metadata={"mid_price": mid_price, "spread_pct": spread_pct, "momentum": momentum},
            )
        except Exception:
            logger.exception("Failed to produce signal for %s", symbol)
            return None


async def main() -> None:
    from quantum_edge.utils.logging import setup_logging

    setup_logging()
    agent = MarketDataAgent()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
