"""Unit tests for idempotency helpers."""

from uuid import uuid4

import pytest
import fakeredis.aioredis

from quantum_edge.utils.idempotency import check_and_set, make_idempotency_key


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


class TestIdempotency:
    def test_make_key_deterministic(self):
        memo_id = uuid4()
        key1 = make_idempotency_key("agent_01", memo_id, 1, "AAPL")
        key2 = make_idempotency_key("agent_01", memo_id, 1, "AAPL")
        assert key1 == key2

    def test_make_key_unique(self):
        memo_id = uuid4()
        key1 = make_idempotency_key("agent_01", memo_id, 1, "AAPL")
        key2 = make_idempotency_key("agent_02", memo_id, 1, "AAPL")
        assert key1 != key2

    def test_make_key_pass_matters(self):
        memo_id = uuid4()
        key1 = make_idempotency_key("agent_01", memo_id, 1, "AAPL")
        key2 = make_idempotency_key("agent_01", memo_id, 2, "AAPL")
        assert key1 != key2

    @pytest.mark.asyncio
    async def test_check_and_set_new(self, redis):
        is_duplicate = await check_and_set(redis, "new_key")
        assert not is_duplicate

    @pytest.mark.asyncio
    async def test_check_and_set_duplicate(self, redis):
        await check_and_set(redis, "test_key")
        is_duplicate = await check_and_set(redis, "test_key")
        assert is_duplicate

    @pytest.mark.asyncio
    async def test_different_keys_not_duplicate(self, redis):
        await check_and_set(redis, "key_a")
        is_duplicate = await check_and_set(redis, "key_b")
        assert not is_duplicate
