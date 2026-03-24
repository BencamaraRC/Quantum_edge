"""Unit tests for MessageBus using fakeredis."""

import pytest
import fakeredis.aioredis

from quantum_edge.core.message_bus import MessageBus, STREAMS


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest.fixture
async def bus(redis):
    b = MessageBus()
    b._redis = redis
    return b


class TestMessageBus:
    @pytest.mark.asyncio
    async def test_publish(self, bus):
        msg_id = await bus.publish("test:stream", {"key": "value"})
        assert msg_id is not None

    @pytest.mark.asyncio
    async def test_ensure_consumer_group(self, bus):
        await bus.ensure_consumer_group("test:stream", "test_group")
        # Should not raise on second call
        await bus.ensure_consumer_group("test:stream", "test_group")

    @pytest.mark.asyncio
    async def test_publish_and_consume(self, bus):
        stream = "test:stream"
        group = "test_group"
        consumer = "consumer_0"

        await bus.ensure_consumer_group(stream, group)
        await bus.publish(stream, {"msg": "hello"})

        messages = await bus.consume({stream: ">"}, group, consumer, count=10, block_ms=100)
        assert len(messages) == 1
        assert messages[0][2]["msg"] == "hello"

    @pytest.mark.asyncio
    async def test_ack(self, bus):
        stream = "test:stream"
        group = "test_group"
        consumer = "consumer_0"

        await bus.ensure_consumer_group(stream, group)
        await bus.publish(stream, {"msg": "ack_me"})

        messages = await bus.consume({stream: ">"}, group, consumer, count=1, block_ms=100)
        assert len(messages) == 1
        _, msg_id, _ = messages[0]

        await bus.ack(stream, group, msg_id)

    @pytest.mark.asyncio
    async def test_multiple_messages(self, bus):
        stream = "test:stream"
        group = "test_group"
        consumer = "consumer_0"

        await bus.ensure_consumer_group(stream, group)

        for i in range(5):
            await bus.publish(stream, {"idx": str(i)})

        messages = await bus.consume({stream: ">"}, group, consumer, count=10, block_ms=100)
        assert len(messages) == 5

    @pytest.mark.asyncio
    async def test_stream_names_defined(self):
        # Verify all expected streams are defined
        expected = [
            "news", "market_data", "events", "data_science",
            "smart_money", "technicals", "risk",
            "ctx_regime", "ctx_volatility", "ctx_macro", "ctx_calendar", "ctx_portfolio",
            "phase", "memo", "decision", "execution",
            "heartbeat", "errors", "audit",
        ]
        for name in expected:
            assert name in STREAMS, f"Missing stream: {name}"
