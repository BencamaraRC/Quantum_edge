"""Agent 3: Events Engine — Calendar + historical event reactions (60s cycle).

Tracks earnings, FOMC, economic releases, FDA decisions.
Uses Agent 6 event fingerprints for historical pattern matching.
Publishes: qe:signals:events
Updates context: qe:state:calendar
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import httpx

from quantum_edge.core.base_agent import BaseAgent
from quantum_edge.core.config import settings
from quantum_edge.core.message_bus import STREAMS
from quantum_edge.models.events import PipelineEvent, PipelineEventType
from quantum_edge.models.memo import AgentSignal, Conviction, Direction
from quantum_edge.models.signals import EventSignal

logger = logging.getLogger(__name__)

# Event types and their typical market impacts
EVENT_IMPACT = {
    "earnings": "high",
    "fomc": "high",
    "cpi": "high",
    "nfp": "high",
    "ppi": "medium",
    "gdp": "medium",
    "retail_sales": "medium",
    "housing": "low",
    "fda_decision": "high",
    "ex_dividend": "low",
}


class EventsEngine(BaseAgent):
    agent_id = "agent_03"
    agent_name = "events_engine"
    consumer_group = "cg:agent_03_events_engine"
    subscribe_streams = [STREAMS["phase"]]
    cycle_seconds = 60.0

    def __init__(self) -> None:
        super().__init__()
        self._http_client: httpx.AsyncClient | None = None
        self._cached_events: dict[str, list[EventSignal]] = {}
        self._last_fetch: datetime | None = None

    async def on_start(self) -> None:
        self._http_client = httpx.AsyncClient(timeout=30.0)
        logger.info("Events Engine started")

    async def on_stop(self) -> None:
        if self._http_client:
            await self._http_client.aclose()

    async def on_cycle(self) -> None:
        """Fetch upcoming events and publish signals for nearby events."""
        # Refresh event cache every 5 minutes
        if self._last_fetch is None or (datetime.utcnow() - self._last_fetch).seconds > 300:
            await self._refresh_events()
            self._last_fetch = datetime.utcnow()

        # Publish signals for events happening within next 24 hours
        now = datetime.utcnow()
        upcoming_events: list[EventSignal] = []

        for symbol, events in self._cached_events.items():
            for event in events:
                hours_until = (event.event_time - now).total_seconds() / 3600
                if 0 < hours_until <= 24:
                    event.days_until = hours_until / 24
                    # Avoid entries within 2 hours of high-impact events
                    event.avoid_entry = (
                        hours_until <= 2 and event.impact_level == "high"
                    )
                    upcoming_events.append(event)

                    await self.publish_signal(
                        STREAMS["events"],
                        {
                            "agent_id": self.agent_id,
                            "symbol": symbol,
                            "signal_type": "event_calendar",
                            "event_type": event.event_type,
                            "event_name": event.event_name,
                            "impact_level": event.impact_level,
                            "hours_until": str(hours_until),
                            "avoid_entry": str(event.avoid_entry),
                            "fingerprint_match": str(event.fingerprint_match),
                            "timestamp": datetime.utcnow().isoformat(),
                        },
                    )

        # Update calendar context
        await self.update_context(
            "calendar",
            {
                "upcoming_high_impact": [
                    {
                        "symbol": e.symbol,
                        "event_type": e.event_type,
                        "event_name": e.event_name,
                        "hours_until": e.days_until * 24,
                    }
                    for e in upcoming_events
                    if e.impact_level == "high"
                ],
                "avoid_symbols": [
                    e.symbol for e in upcoming_events if e.avoid_entry
                ],
                "last_update": datetime.utcnow().isoformat(),
            },
        )

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
        signal = self._produce_signal(symbol, pass_number)

        from uuid import UUID
        await self.publish_event(PipelineEvent(
            event_type=PipelineEventType.SIGNAL_RECEIVED,
            memo_id=UUID(memo_id),
            symbol=symbol,
            agent_id=self.agent_id,
            pass_number=pass_number,
            data={"agent_id": self.agent_id, "symbol": symbol, "signal": signal.model_dump_json()},
        ))
        logger.info("Published signal for %s (pass %d, memo %s)", symbol, pass_number, memo_id)

    def _produce_signal(self, symbol: str, pass_number: int) -> AgentSignal:
        """Produce an AgentSignal based on upcoming events for the symbol."""
        events = self._cached_events.get(symbol, [])
        now = datetime.utcnow()

        # Find upcoming high-impact events
        high_impact = [
            e for e in events
            if e.impact_level == "high" and (e.event_time - now).total_seconds() > 0
        ]

        if high_impact:
            nearest = min(high_impact, key=lambda e: e.event_time)
            hours_until = (nearest.event_time - now).total_seconds() / 3600

            # If event is very close (< 2h), signal caution
            if hours_until < 2:
                score = -0.5  # Avoid entering
                direction = Direction.LONG  # Neutral bias
                conviction = Conviction.HIGH
                rationale = f"High-impact event imminent: {nearest.event_name} in {hours_until:.1f}h"
            else:
                score = 0.1  # Slight positive — catalysts can be good
                direction = Direction.LONG
                conviction = Conviction.LOW
                rationale = f"Upcoming event: {nearest.event_name} in {hours_until:.1f}h"
        else:
            # No events — neutral signal
            score = 0.2  # Slightly positive (no event risk)
            direction = Direction.LONG
            conviction = Conviction.LOW
            rationale = "No upcoming high-impact events"

        return AgentSignal(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            symbol=symbol,
            direction=direction,
            conviction=conviction,
            score=score,
            pass_number=pass_number,
            rationale=rationale,
            metadata={"high_impact_count": len(high_impact)},
        )

    async def _refresh_events(self) -> None:
        """Fetch events from Finnhub economic calendar and earnings calendar."""
        self._cached_events.clear()

        if not settings.finnhub_api_key or self._http_client is None:
            logger.warning("Finnhub API key not set, skipping event fetch")
            return

        try:
            # Economic calendar
            today = datetime.utcnow().strftime("%Y-%m-%d")
            next_week = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d")

            resp = await self._http_client.get(
                "https://finnhub.io/api/v1/calendar/economic",
                params={"from": today, "to": next_week, "token": settings.finnhub_api_key},
            )
            if resp.status_code == 200:
                data = resp.json()
                for event in data.get("economicCalendar", []):
                    event_type = self._classify_event(event.get("event", ""))
                    signal = EventSignal(
                        symbol="SPY",  # Economic events affect broad market
                        event_type=event_type,
                        event_name=event.get("event", "Unknown"),
                        event_time=datetime.fromisoformat(event["time"]) if event.get("time") else datetime.utcnow(),
                        impact_level=EVENT_IMPACT.get(event_type, "medium"),
                        days_until=0,
                    )
                    self._cached_events.setdefault("SPY", []).append(signal)

            # Earnings calendar
            resp = await self._http_client.get(
                "https://finnhub.io/api/v1/calendar/earnings",
                params={"from": today, "to": next_week, "token": settings.finnhub_api_key},
            )
            if resp.status_code == 200:
                data = resp.json()
                for earnings in data.get("earningsCalendar", []):
                    symbol = earnings.get("symbol", "")
                    if symbol:
                        signal = EventSignal(
                            symbol=symbol,
                            event_type="earnings",
                            event_name=f"{symbol} Earnings",
                            event_time=datetime.fromisoformat(earnings["date"]) if earnings.get("date") else datetime.utcnow(),
                            impact_level="high",
                            days_until=0,
                        )
                        self._cached_events.setdefault(symbol, []).append(signal)

        except Exception:
            logger.exception("Failed to refresh events")

    def _classify_event(self, event_name: str) -> str:
        """Classify an economic event by name."""
        name_lower = event_name.lower()
        if "fomc" in name_lower or "fed" in name_lower or "interest rate" in name_lower:
            return "fomc"
        if "cpi" in name_lower or "consumer price" in name_lower:
            return "cpi"
        if "nonfarm" in name_lower or "employment" in name_lower or "jobs" in name_lower:
            return "nfp"
        if "gdp" in name_lower:
            return "gdp"
        if "retail" in name_lower:
            return "retail_sales"
        if "ppi" in name_lower or "producer price" in name_lower:
            return "ppi"
        if "housing" in name_lower:
            return "housing"
        return "economic_release"


async def main() -> None:
    from quantum_edge.utils.logging import setup_logging

    setup_logging()
    agent = EventsEngine()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
