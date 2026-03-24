"""Unit tests for ContextStore using fakeredis."""

from datetime import datetime

import pytest
import fakeredis.aioredis

from quantum_edge.core.context_store import ContextStore


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest.fixture
async def store(redis):
    s = ContextStore(redis_client=redis)
    return s


class TestContextStore:
    @pytest.mark.asyncio
    async def test_update_and_get(self, store):
        await store.update(
            "regime",
            {"regime": "trending_bull", "probability": 0.85},
            "agent_06",
        )
        result = await store.get("regime")
        assert result["regime"] == "trending_bull"
        assert result["probability"] == 0.85

    @pytest.mark.asyncio
    async def test_get_empty(self, store):
        result = await store.get("nonexistent")
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_multi(self, store):
        await store.update("regime", {"regime": "trending_bull"}, "agent_06")
        await store.update("volatility", {"vol_forecast": 0.25}, "agent_06")

        result = await store.get_multi(["regime", "volatility", "macro"])
        assert result["regime"]["regime"] == "trending_bull"
        assert result["volatility"]["vol_forecast"] == 0.25
        assert result["macro"] == {}

    @pytest.mark.asyncio
    async def test_snapshot(self, store):
        await store.update("regime", {"regime": "high_volatility"}, "agent_06")
        await store.update("portfolio", {"equity": "100000"}, "agent_05")

        snapshot = await store.snapshot()
        assert snapshot.regime["regime"] == "high_volatility"
        assert str(snapshot.portfolio["equity"]) == "100000"
        assert snapshot.captured_at is not None

    @pytest.mark.asyncio
    async def test_dual_write_creates_stream_entry(self, store, redis):
        await store.update("regime", {"regime": "trending_bull"}, "agent_06")

        # Verify stream was written
        entries = await redis.xrange("qe:context:regime")
        assert len(entries) == 1

    @pytest.mark.asyncio
    async def test_update_overwrites(self, store):
        await store.update("regime", {"regime": "trending_bull"}, "agent_06")
        await store.update("regime", {"regime": "mean_reverting"}, "agent_06")

        result = await store.get("regime")
        assert result["regime"] == "mean_reverting"

    @pytest.mark.asyncio
    async def test_complex_nested_data(self, store):
        await store.update(
            "volatility",
            {
                "vol_forecast": 0.25,
                "vol_term_structure": {"1d": 0.20, "5d": 0.25},
                "updated": datetime.utcnow().isoformat(),
            },
            "agent_06",
        )
        result = await store.get("volatility")
        assert isinstance(result["vol_term_structure"], dict)
        assert result["vol_term_structure"]["1d"] == 0.20

    @pytest.mark.asyncio
    async def test_delete(self, store):
        await store.update("regime", {"regime": "trending_bull"}, "agent_06")
        await store.delete("regime")
        result = await store.get("regime")
        assert result == {}
