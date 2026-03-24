"""Agent 1: News Scanner — FinBERT NLP sentiment analysis (60s cycle).

Scans financial news feeds, scores sentiment using FinBERT, deduplicates headlines.
Publishes: qe:signals:news
Updates context: qe:state:macro (aggregated market sentiment)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime
from typing import Any

import feedparser
import httpx

from quantum_edge.core.base_agent import BaseAgent
from quantum_edge.core.config import settings
from quantum_edge.core.message_bus import STREAMS
from quantum_edge.models.events import PipelineEvent, PipelineEventType
from quantum_edge.models.memo import AgentSignal, Conviction, Direction

logger = logging.getLogger(__name__)

# RSS feeds for financial news
NEWS_FEEDS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY&region=US&lang=en-US",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://feeds.bloomberg.com/markets/news.rss",
]

# Symbols to filter news for — strategy universe + indices
from quantum_edge.core.strategy import FULL_UNIVERSE
TRACKED_SYMBOLS = set(FULL_UNIVERSE) | {"SPY", "QQQ"}


class NewsScanner(BaseAgent):
    agent_id = "agent_01"
    agent_name = "news_scanner"
    consumer_group = "cg:agent_01_news_scanner"
    subscribe_streams = [STREAMS["phase"]]
    cycle_seconds = 60.0

    def __init__(self) -> None:
        super().__init__()
        self._seen_hashes: set[str] = set()
        self._sentiment_pipeline: Any = None
        self._http_client: httpx.AsyncClient | None = None

    async def on_start(self) -> None:
        self._http_client = httpx.AsyncClient(timeout=30.0)

        # Lazy-load FinBERT for sentiment analysis
        try:
            from transformers import pipeline

            self._sentiment_pipeline = pipeline(
                "sentiment-analysis",
                model="ProsusAI/finbert",
                return_all_scores=True,
            )
            logger.info("FinBERT model loaded")
        except Exception:
            logger.warning("FinBERT not available, using placeholder sentiment")

    async def on_stop(self) -> None:
        if self._http_client:
            await self._http_client.aclose()

    async def on_cycle(self) -> None:
        """Scan news feeds, score sentiment, publish signals."""
        headlines = await self._fetch_headlines()

        for headline in headlines:
            dedup_hash = hashlib.sha256(headline["title"].encode()).hexdigest()[:16]
            if dedup_hash in self._seen_hashes:
                continue
            self._seen_hashes.add(dedup_hash)

            # Limit dedup cache
            if len(self._seen_hashes) > 10000:
                self._seen_hashes = set(list(self._seen_hashes)[-5000:])

            # Score sentiment
            sentiment = self._score_sentiment(headline["title"])

            # Identify relevant symbols
            symbols = self._extract_symbols(headline["title"])
            if not symbols:
                continue

            for symbol in symbols:
                await self.publish_signal(
                    STREAMS["news"],
                    {
                        "agent_id": self.agent_id,
                        "symbol": symbol,
                        "signal_type": "news_sentiment",
                        "headline": headline["title"],
                        "source": headline.get("source", "unknown"),
                        "sentiment_score": str(sentiment["score"]),
                        "sentiment_label": sentiment["label"],
                        "confidence": str(sentiment["confidence"]),
                        "dedup_hash": dedup_hash,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )

        # Update macro context with aggregated sentiment
        if headlines:
            avg_sentiment = self._aggregate_sentiment(headlines)
            await self.update_context(
                "macro",
                {
                    "news_sentiment": avg_sentiment,
                    "headlines_processed": len(headlines),
                    "last_scan": datetime.utcnow().isoformat(),
                },
            )

    async def on_message(self, stream: str, msg_id: str, data: dict[str, str]) -> None:
        """Respond to signal collection phase events."""
        if stream != STREAMS["phase"]:
            return
        event_type = data.get("event_type", "")
        if event_type != "phase_advance":
            return
        to_phase = data.get("data", "")
        # Parse the to_phase from the data JSON
        import orjson
        try:
            event_data = orjson.loads(data.get("data", "{}"))
            if isinstance(event_data, str):
                event_data = orjson.loads(event_data)
            parsed_data = event_data.get("data", event_data)
            to_phase = parsed_data.get("to_phase", "")
        except Exception:
            to_phase = ""

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

        # Publish the SIGNAL_RECEIVED event so the coordinator can track it
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
        """Produce an AgentSignal for the given symbol from recent news."""
        # Score sentiment for the symbol from recent headlines
        headlines = await self._fetch_headlines()
        relevant = [h for h in headlines if symbol in self._extract_symbols(h["title"])]

        if not relevant:
            # No news — produce a neutral signal
            score = 0.0
            label = "neutral"
        else:
            sentiments = [self._score_sentiment(h["title"]) for h in relevant]
            score = sum(s["score"] for s in sentiments) / len(sentiments) if sentiments else 0.0
            label = "positive" if score > 0.1 else ("negative" if score < -0.1 else "neutral")

        if score > 0.3:
            direction = Direction.LONG
            conviction = Conviction.HIGH
        elif score > 0.1:
            direction = Direction.LONG
            conviction = Conviction.MEDIUM
        elif score < -0.3:
            direction = Direction.SHORT
            conviction = Conviction.HIGH
        elif score < -0.1:
            direction = Direction.SHORT
            conviction = Conviction.MEDIUM
        else:
            direction = Direction.LONG
            conviction = Conviction.LOW

        return AgentSignal(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            symbol=symbol,
            direction=direction,
            conviction=conviction,
            score=max(-1.0, min(1.0, score)),
            pass_number=pass_number,
            rationale=f"News sentiment: {label} ({len(relevant)} headlines)",
            metadata={"headline_count": len(relevant), "sentiment_label": label},
        )

    async def _fetch_headlines(self) -> list[dict[str, str]]:
        """Fetch headlines from RSS feeds."""
        headlines: list[dict[str, str]] = []
        for feed_url in NEWS_FEEDS:
            try:
                if self._http_client is None:
                    continue
                resp = await self._http_client.get(feed_url)
                feed = feedparser.parse(resp.text)
                for entry in feed.entries[:20]:
                    headlines.append({
                        "title": entry.get("title", ""),
                        "source": feed_url.split("/")[2],
                        "link": entry.get("link", ""),
                        "published": entry.get("published", ""),
                    })
            except Exception:
                logger.warning("Failed to fetch feed: %s", feed_url)
        return headlines

    def _score_sentiment(self, text: str) -> dict[str, Any]:
        """Score text sentiment using FinBERT or fallback."""
        if self._sentiment_pipeline:
            try:
                result = self._sentiment_pipeline(text[:512])
                scores = {r["label"]: r["score"] for r in result[0]}
                positive = scores.get("positive", 0)
                negative = scores.get("negative", 0)
                neutral = scores.get("neutral", 0)

                if positive > negative and positive > neutral:
                    return {"score": positive, "label": "positive", "confidence": positive}
                elif negative > positive and negative > neutral:
                    return {"score": -negative, "label": "negative", "confidence": negative}
                else:
                    return {"score": 0.0, "label": "neutral", "confidence": neutral}
            except Exception:
                logger.warning("FinBERT scoring failed, using neutral")

        return {"score": 0.0, "label": "neutral", "confidence": 0.5}

    def _extract_symbols(self, text: str) -> list[str]:
        """Extract tracked stock symbols from headline text."""
        text_upper = text.upper()
        return [s for s in TRACKED_SYMBOLS if f" {s} " in f" {text_upper} " or f"${s}" in text_upper]

    def _aggregate_sentiment(self, headlines: list[dict[str, str]]) -> float:
        """Compute average sentiment across all headlines."""
        scores = []
        for h in headlines:
            s = self._score_sentiment(h["title"])
            scores.append(s["score"])
        return sum(scores) / len(scores) if scores else 0.0


async def main() -> None:
    from quantum_edge.utils.logging import setup_logging

    setup_logging()
    agent = NewsScanner()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
