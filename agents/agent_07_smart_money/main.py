"""Agent 7: Smart Money — Yahoo Finance options flow, institutional data, social sentiment.

Tracks institutional ownership changes, unusual options volume,
and social sentiment via free APIs. Activated between Pass 1 and Pass 2.

Publishes: qe:signals:smart_money
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
import yfinance as yf

from uuid import UUID

from quantum_edge.core.base_agent import BaseAgent
from quantum_edge.core.config import settings
from quantum_edge.core.message_bus import STREAMS
from quantum_edge.models.events import PipelineEvent, PipelineEventType
from quantum_edge.models.memo import Direction, SmartMoneySignal

logger = logging.getLogger(__name__)


class SmartMoney(BaseAgent):
    agent_id = "agent_07"
    agent_name = "smart_money"
    consumer_group = "cg:agent_07_smart_money"
    subscribe_streams = [STREAMS["phase"]]
    cycle_seconds = 300.0  # Long cycle — mainly triggered by pipeline events

    def __init__(self) -> None:
        super().__init__()
        self._http_client: httpx.AsyncClient | None = None

    async def on_start(self) -> None:
        self._http_client = httpx.AsyncClient(timeout=30.0)
        logger.info("Smart Money agent started (Yahoo Finance + social sentiment)")

    async def on_stop(self) -> None:
        if self._http_client:
            await self._http_client.aclose()

    async def on_cycle(self) -> None:
        """Background scan — main work is event-driven via pipeline phase."""
        pass

    async def on_message(self, stream: str, msg_id: str, data: dict[str, str]) -> None:
        """Respond to pipeline phase events (smart money validation trigger)."""
        event_type = data.get("event_type", "")
        if event_type == "phase_advance":
            phase = data.get("phase", "")
            if phase == "smart_money_validation":
                symbol = data.get("symbol", "")
                memo_id = data.get("memo_id", "")
                if symbol and memo_id:
                    await self._validate(symbol, memo_id)

    async def _validate(self, symbol: str, memo_id: str) -> None:
        """Run full smart money validation for a symbol."""
        logger.info("Smart money validation for %s (memo %s)", symbol, memo_id)

        try:
            # Gather data from multiple sources (run in parallel via threads for sync yfinance)
            loop = asyncio.get_event_loop()
            options_fut = loop.run_in_executor(None, self._fetch_options_flow_sync, symbol)
            institutional_fut = loop.run_in_executor(None, self._fetch_institutional_sync, symbol)
            social_fut = self._fetch_social_sentiment(symbol)

            options_data, institutional, social = await asyncio.gather(
                options_fut, institutional_fut, social_fut
            )

            # Compute composite smart money score
            score, direction = self._score_smart_money(options_data, institutional, social)

            signal = SmartMoneySignal(
                score=score,
                direction=direction,
                sources=self._active_sources(options_data, institutional, social),
                unusual_options=options_data.get("alerts", []),
                institutional_flow=institutional,
                social_sentiment=social,
                timestamp=datetime.now(timezone.utc),
            )

            await self.publish_signal(
                STREAMS["smart_money"],
                {
                    "agent_id": self.agent_id,
                    "symbol": symbol,
                    "memo_id": memo_id,
                    "signal_type": "smart_money",
                    "score": str(score),
                    "direction": direction.value,
                    "data": signal.model_dump_json(),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

            # Publish SMART_MONEY_COMPLETE event so coordinator advances
            await self.publish_event(PipelineEvent(
                event_type=PipelineEventType.SMART_MONEY_COMPLETE,
                memo_id=UUID(memo_id),
                symbol=symbol,
                agent_id=self.agent_id,
                data={
                    "score": str(score),
                    "direction": direction.value,
                    "signal": signal.model_dump_json(),
                },
            ))

            logger.info(
                "Smart money score for %s: %.2f (%s) — options=%.2f, inst=%.2f, social=%.2f",
                symbol,
                score,
                direction.value,
                options_data.get("net_score", 0),
                institutional.get("net_institutional_change", 0),
                social.get("sentiment_score", 0),
            )

        except Exception:
            logger.exception("Smart money validation failed for %s", symbol)

    def _fetch_options_flow_sync(self, symbol: str) -> dict[str, Any]:
        """Fetch options flow data from Yahoo Finance (synchronous)."""
        try:
            ticker = yf.Ticker(symbol)
            expirations = ticker.options
            if not expirations:
                return {"alerts": [], "total_premium": 0, "net_score": 0}

            # Check nearest expiration for unusual activity
            nearest = expirations[0]
            chain = ticker.option_chain(nearest)
            calls = chain.calls
            puts = chain.puts

            if calls.empty and puts.empty:
                return {"alerts": [], "total_premium": 0, "net_score": 0}

            # Compute call vs put volume ratio
            call_volume = int(calls["volume"].sum()) if "volume" in calls.columns else 0
            put_volume = int(puts["volume"].sum()) if "volume" in puts.columns else 0
            total_volume = call_volume + put_volume

            # Compute call vs put open interest
            call_oi = int(calls["openInterest"].sum()) if "openInterest" in calls.columns else 0
            put_oi = int(puts["openInterest"].sum()) if "openInterest" in puts.columns else 0
            total_oi = call_oi + put_oi

            # Put/Call ratio (< 0.7 = bullish, > 1.0 = bearish)
            pc_ratio = put_volume / call_volume if call_volume > 0 else 1.0

            # Volume vs OI ratio — high volume relative to OI = unusual activity
            vol_oi_ratio = total_volume / total_oi if total_oi > 0 else 0

            # Find unusual contracts (volume > 5x open interest)
            alerts = []
            for _, row in calls.iterrows():
                if row.get("volume", 0) > 0 and row.get("openInterest", 0) > 0:
                    ratio = row["volume"] / row["openInterest"]
                    if ratio > 5:
                        alerts.append({
                            "type": "call",
                            "strike": float(row["strike"]),
                            "volume": int(row["volume"]),
                            "oi": int(row["openInterest"]),
                            "ratio": round(ratio, 1),
                            "sentiment": "bullish",
                        })
            for _, row in puts.iterrows():
                if row.get("volume", 0) > 0 and row.get("openInterest", 0) > 0:
                    ratio = row["volume"] / row["openInterest"]
                    if ratio > 5:
                        alerts.append({
                            "type": "put",
                            "strike": float(row["strike"]),
                            "volume": int(row["volume"]),
                            "oi": int(row["openInterest"]),
                            "ratio": round(ratio, 1),
                            "sentiment": "bearish",
                        })

            # Net score: bullish if more call activity, bearish if more puts
            if total_volume > 0:
                net_score = (call_volume - put_volume) / total_volume  # [-1, 1]
            else:
                net_score = 0.0

            # Adjust for unusual alerts
            bullish_alerts = sum(1 for a in alerts if a["sentiment"] == "bullish")
            bearish_alerts = sum(1 for a in alerts if a["sentiment"] == "bearish")
            if bullish_alerts + bearish_alerts > 0:
                alert_bias = (bullish_alerts - bearish_alerts) / (bullish_alerts + bearish_alerts)
                net_score = net_score * 0.6 + alert_bias * 0.4

            logger.info(
                "Options flow %s: P/C=%.2f, vol=%d, alerts=%d, net_score=%.2f",
                symbol, pc_ratio, total_volume, len(alerts), net_score,
            )

            return {
                "alerts": alerts[:10],  # Cap at 10
                "total_premium": total_volume,
                "pc_ratio": round(pc_ratio, 3),
                "vol_oi_ratio": round(vol_oi_ratio, 3),
                "call_volume": call_volume,
                "put_volume": put_volume,
                "net_score": round(net_score, 4),
            }

        except Exception:
            logger.warning("Yahoo Finance options fetch failed for %s", symbol)
            return {"alerts": [], "total_premium": 0, "net_score": 0}

    def _fetch_institutional_sync(self, symbol: str) -> dict[str, Any]:
        """Fetch institutional ownership data from Yahoo Finance (synchronous)."""
        try:
            ticker = yf.Ticker(symbol)
            holders = ticker.institutional_holders

            if holders is None or holders.empty:
                return {
                    "net_institutional_change": 0.0,
                    "top_holders_change": 0.0,
                    "13f_filings_recent": 0,
                    "institutional_pct": 0.0,
                }

            # Get institutional ownership percentage
            info = ticker.info or {}
            inst_pct = info.get("heldPercentInstitutions", 0) or 0

            # Check for recent changes in top holders
            # Yahoo provides "% Out" and "Value" columns
            total_shares = 0
            num_holders = len(holders)
            if "Shares" in holders.columns:
                total_shares = int(holders["Shares"].sum())

            # Use insider transactions as a proxy for institutional sentiment
            insider_txns = ticker.insider_transactions
            net_insider = 0.0
            if insider_txns is not None and not insider_txns.empty:
                # Count buys vs sells in recent transactions
                for _, txn in insider_txns.head(20).iterrows():
                    text = str(txn.get("Transaction", "")).lower()
                    shares = txn.get("Shares", 0) or 0
                    if "purchase" in text or "buy" in text:
                        net_insider += shares
                    elif "sale" in text or "sell" in text:
                        net_insider -= shares

            # Normalize insider activity to [-1, 1]
            if net_insider != 0:
                net_change = max(-1.0, min(1.0, net_insider / 100000))
            else:
                net_change = 0.0

            logger.info(
                "Institutional %s: pct=%.1f%%, holders=%d, insider_net=%.0f",
                symbol, inst_pct * 100, num_holders, net_insider,
            )

            return {
                "net_institutional_change": net_change,
                "top_holders_change": 0.0,
                "13f_filings_recent": num_holders,
                "institutional_pct": inst_pct,
                "insider_net_shares": net_insider,
            }

        except Exception:
            logger.warning("Yahoo Finance institutional fetch failed for %s", symbol)
            return {
                "net_institutional_change": 0.0,
                "top_holders_change": 0.0,
                "13f_filings_recent": 0,
            }

    async def _fetch_social_sentiment(self, symbol: str) -> dict[str, Any]:
        """Fetch social sentiment from StockTwits (free, no auth required)."""
        if self._http_client is None:
            return {"mentions_24h": 0, "sentiment_score": 0.0, "trending": False}

        try:
            resp = await self._http_client.get(
                f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json",
                params={"filter": "top", "limit": 30},
            )

            if resp.status_code != 200:
                return {"mentions_24h": 0, "sentiment_score": 0.0, "trending": False}

            data = resp.json()
            messages = data.get("messages", [])
            symbol_info = data.get("symbol", {})

            if not messages:
                return {"mentions_24h": 0, "sentiment_score": 0.0, "trending": False}

            # Count bullish vs bearish sentiment tags
            bullish = 0
            bearish = 0
            for msg in messages:
                sentiment = msg.get("entities", {}).get("sentiment")
                if sentiment:
                    if sentiment.get("basic") == "Bullish":
                        bullish += 1
                    elif sentiment.get("basic") == "Bearish":
                        bearish += 1

            total_tagged = bullish + bearish
            if total_tagged > 0:
                sentiment_score = (bullish - bearish) / total_tagged  # [-1, 1]
            else:
                sentiment_score = 0.0

            trending = symbol_info.get("is_following", False) or len(messages) > 20

            logger.info(
                "Social %s: mentions=%d, bullish=%d, bearish=%d, score=%.2f",
                symbol, len(messages), bullish, bearish, sentiment_score,
            )

            return {
                "mentions_24h": len(messages),
                "sentiment_score": sentiment_score,
                "trending": trending,
                "bullish_count": bullish,
                "bearish_count": bearish,
            }

        except Exception:
            logger.warning("StockTwits fetch failed for %s", symbol)
            return {"mentions_24h": 0, "sentiment_score": 0.0, "trending": False}

    def _score_smart_money(
        self,
        options: dict[str, Any],
        institutional: dict[str, Any],
        social: dict[str, Any],
    ) -> tuple[float, Direction]:
        """Compute composite smart money score from all sources."""
        total_score = 0.0
        weights_sum = 0.0

        # Options flow (weight: 0.5) — strongest signal
        options_score = options.get("net_score", 0)
        if options_score != 0:
            total_score += options_score * 0.5
            weights_sum += 0.5

        # Institutional flow (weight: 0.3)
        inst_change = institutional.get("net_institutional_change", 0)
        if inst_change != 0:
            inst_score = min(1.0, max(-1.0, inst_change))
            total_score += inst_score * 0.3
            weights_sum += 0.3

        # Social sentiment (weight: 0.2)
        social_score = social.get("sentiment_score", 0)
        if social_score != 0:
            total_score += social_score * 0.2
            weights_sum += 0.2

        final_score = total_score / weights_sum if weights_sum > 0 else 0.0
        direction = Direction.LONG if final_score >= 0 else Direction.SHORT

        return max(-1.0, min(1.0, final_score)), direction

    def _active_sources(
        self,
        options: dict[str, Any],
        institutional: dict[str, Any],
        social: dict[str, Any],
    ) -> list[str]:
        """List which data sources contributed non-zero data."""
        sources = []
        if options.get("net_score", 0) != 0:
            sources.append("yahoo_options")
        if institutional.get("net_institutional_change", 0) != 0:
            sources.append("yahoo_institutional")
        if social.get("sentiment_score", 0) != 0:
            sources.append("stocktwits")
        return sources or ["none"]


async def main() -> None:
    from quantum_edge.utils.logging import setup_logging

    setup_logging()
    agent = SmartMoney()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
