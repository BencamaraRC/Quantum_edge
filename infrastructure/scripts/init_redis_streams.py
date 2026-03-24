"""Initialize all Redis Streams and consumer groups."""

from __future__ import annotations

import asyncio
import sys

import redis.asyncio as aioredis

# All streams and their consumer groups
STREAM_CONFIG: dict[str, list[str]] = {
    # Signal streams
    "qe:signals:news": ["cg:agent_01_news_scanner", "cg:coordinator"],
    "qe:signals:market_data": ["cg:agent_02_market_data", "cg:coordinator"],
    "qe:signals:events": ["cg:agent_03_events_engine", "cg:coordinator"],
    "qe:signals:data_science": ["cg:agent_06_data_scientist", "cg:coordinator"],
    "qe:signals:smart_money": ["cg:agent_07_smart_money", "cg:coordinator"],
    "qe:signals:technicals": ["cg:agent_04_momentum_bot", "cg:coordinator"],
    "qe:signals:risk": ["cg:agent_05_risk_guard", "cg:coordinator"],
    "qe:signals:position_monitor": ["cg:agent_08_position_monitor", "cg:coordinator"],
    # Context streams
    "qe:context:regime": [
        "cg:agent_04_momentum_bot",
        "cg:agent_05_risk_guard",
        "cg:coordinator",
    ],
    "qe:context:volatility": [
        "cg:agent_04_momentum_bot",
        "cg:agent_05_risk_guard",
        "cg:coordinator",
    ],
    "qe:context:macro": [
        "cg:agent_04_momentum_bot",
        "cg:agent_05_risk_guard",
        "cg:coordinator",
    ],
    "qe:context:calendar": [
        "cg:agent_04_momentum_bot",
        "cg:agent_05_risk_guard",
        "cg:coordinator",
    ],
    "qe:context:portfolio": [
        "cg:agent_01_news_scanner",
        "cg:agent_02_market_data",
        "cg:agent_03_events_engine",
        "cg:agent_04_momentum_bot",
        "cg:agent_05_risk_guard",
        "cg:agent_06_data_scientist",
        "cg:agent_07_smart_money",
        "cg:coordinator",
    ],
    # Pipeline control
    "qe:pipeline:phase": [
        "cg:agent_01_news_scanner",
        "cg:agent_02_market_data",
        "cg:agent_03_events_engine",
        "cg:agent_04_momentum_bot",
        "cg:agent_05_risk_guard",
        "cg:agent_06_data_scientist",
        "cg:agent_07_smart_money",
        "cg:agent_08_position_monitor",
        "cg:coordinator",
    ],
    "qe:pipeline:memo": ["cg:coordinator"],
    "qe:pipeline:decision": ["cg:coordinator"],
    "qe:pipeline:execution": ["cg:coordinator", "cg:agent_05_risk_guard", "cg:agent_08_position_monitor"],
    # System
    "qe:system:heartbeat": ["cg:coordinator"],
    "qe:system:errors": ["cg:coordinator"],
    "qe:system:audit": ["cg:coordinator"],
}


async def init_streams(redis_url: str = "redis://localhost:6379/0") -> None:
    """Create all streams and consumer groups."""
    r = aioredis.from_url(redis_url, decode_responses=True)
    await r.ping()
    print(f"Connected to Redis: {redis_url}")

    for stream, groups in STREAM_CONFIG.items():
        for group in groups:
            try:
                await r.xgroup_create(stream, group, id="0", mkstream=True)
                print(f"  Created group {group} on {stream}")
            except aioredis.ResponseError as e:
                if "BUSYGROUP" in str(e):
                    print(f"  Group {group} already exists on {stream}")
                else:
                    raise

    await r.aclose()
    print("All streams and consumer groups initialized.")


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "redis://localhost:6379/0"
    asyncio.run(init_streams(url))
