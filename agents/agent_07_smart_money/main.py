"""Agent 7: Smart Money — Unusual Whales, WhaleWisdom, FinTwit, SweepCast.

Tracks institutional flow, unusual options activity, dark pool data,
and social sentiment. Activated between Pass 1 and Pass 2.

Publishes: qe:signals:smart_money
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx

from uuid import UUID

from quantum_edge.core.base_agent import BaseAgent
from quantum_edge.core.config import settings
from quantum_edge.core.message_bus import STREAMS
from quantum_edge.models.events import PipelineEvent, PipelineEventType
from quantum_edge.models.memo import Direction, SmartMoneySignal
from quantum_edge.models.signals import SmartMoneyRaw

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
        logger.info("Smart Money agent started")

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
            # Gather data from multiple sources
            options_data = await self._fetch_unusual_options(symbol)
            institutional = await self._fetch_institutional_flow(symbol)
            social = await self._fetch_social_sentiment(symbol)

            # Compute composite smart money score
            score, direction = self._score_smart_money(options_data, institutional, social)

            signal = SmartMoneySignal(
                score=score,
                direction=direction,
                sources=["unusual_whales", "institutional_filings", "social_sentiment"],
                unusual_options=options_data.get("alerts", []),
                institutional_flow=institutional,
                social_sentiment=social,
                timestamp=datetime.utcnow(),
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
                    "timestamp": datetime.utcnow().isoformat(),
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
                },
            ))

            logger.info(
                "Smart money score for %s: %.2f (%s)",
                symbol,
                score,
                direction.value,
            )

        except Exception:
            logger.exception("Smart money validation failed for %s", symbol)

    async def _fetch_unusual_options(self, symbol: str) -> dict[str, Any]:
        """Fetch unusual options activity from Unusual Whales API."""
        if not settings.unusual_whales_api_key or self._http_client is None:
            return {"alerts": [], "total_premium": 0}

        try:
            resp = await self._http_client.get(
                f"https://api.unusualwhales.com/api/stock/{symbol}/options-flow",
                headers={"Authorization": f"Bearer {settings.unusual_whales_api_key}"},
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            logger.warning("Unusual Whales API call failed for %s", symbol)

        return {"alerts": [], "total_premium": 0}

    async def _fetch_institutional_flow(self, symbol: str) -> dict[str, Any]:
        """Fetch institutional ownership changes."""
        # In production, this would call WhaleWisdom or SEC EDGAR API
        return {
            "net_institutional_change": 0.0,
            "top_holders_change": 0.0,
            "13f_filings_recent": 0,
        }

    async def _fetch_social_sentiment(self, symbol: str) -> dict[str, Any]:
        """Fetch social media sentiment (FinTwit, Reddit)."""
        # In production, this would aggregate from Twitter/X API, Reddit API, etc.
        return {
            "mentions_24h": 0,
            "sentiment_score": 0.0,
            "trending": False,
            "notable_accounts": [],
        }

    def _score_smart_money(
        self,
        options: dict[str, Any],
        institutional: dict[str, Any],
        social: dict[str, Any],
    ) -> tuple[float, Direction]:
        """Compute composite smart money score from all sources."""
        total_score = 0.0
        weights_sum = 0.0

        # Options flow (weight: 0.5)
        alerts = options.get("alerts", [])
        if alerts:
            bullish = sum(1 for a in alerts if a.get("sentiment") == "bullish")
            bearish = sum(1 for a in alerts if a.get("sentiment") == "bearish")
            total = bullish + bearish
            if total > 0:
                options_score = (bullish - bearish) / total
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


async def main() -> None:
    from quantum_edge.utils.logging import setup_logging

    setup_logging()
    agent = SmartMoney()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
