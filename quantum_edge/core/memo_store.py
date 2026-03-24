"""Memo persistence — dual-write to Redis (hot, 24h TTL) + TimescaleDB (permanent)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID

import orjson
import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from quantum_edge.core.config import settings
from quantum_edge.models.memo import InvestmentMemo

logger = logging.getLogger(__name__)

MEMO_KEY_PREFIX = "qe:memo:"
MEMO_TTL = timedelta(hours=24)


class MemoStore:
    """Investment Memo persistence with Redis + TimescaleDB dual-write."""

    def __init__(
        self,
        redis_client: aioredis.Redis | None = None,
        db_url: str | None = None,
    ) -> None:
        self._redis = redis_client
        self._db_url = db_url or settings.database_url
        self._engine = create_async_engine(self._db_url, pool_size=10, max_overflow=5)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def connect(self) -> None:
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                max_connections=20,
            )

    @property
    def redis(self) -> aioredis.Redis:
        if self._redis is None:
            raise RuntimeError("MemoStore not connected.")
        return self._redis

    async def save(self, memo: InvestmentMemo) -> None:
        """Dual-write memo to Redis + TimescaleDB."""
        memo.updated_at = datetime.utcnow()
        memo_json = memo.model_dump_json()

        # Redis: hot storage with TTL
        redis_key = f"{MEMO_KEY_PREFIX}{memo.memo_id}"
        await self.redis.set(redis_key, memo_json, ex=int(MEMO_TTL.total_seconds()))

        # TimescaleDB: permanent storage (upsert)
        async with self._session_factory() as session:
            await session.execute(
                text("""
                    INSERT INTO investment_memos (memo_id, symbol, version, phase, data, created_at, updated_at)
                    VALUES (:memo_id, :symbol, :version, :phase, :data::jsonb, :created_at, :updated_at)
                    ON CONFLICT (memo_id) DO UPDATE SET
                        version = EXCLUDED.version,
                        phase = EXCLUDED.phase,
                        data = EXCLUDED.data,
                        updated_at = EXCLUDED.updated_at
                """),
                {
                    "memo_id": str(memo.memo_id),
                    "symbol": memo.symbol,
                    "version": memo.version,
                    "phase": memo.phase.value,
                    "data": memo_json,
                    "created_at": memo.created_at,
                    "updated_at": memo.updated_at,
                },
            )
            await session.commit()

        logger.debug("Memo saved: %s (phase=%s)", memo.memo_id, memo.phase)

    async def get(self, memo_id: UUID) -> InvestmentMemo | None:
        """Get memo from Redis first, fall back to TimescaleDB."""
        redis_key = f"{MEMO_KEY_PREFIX}{memo_id}"

        # Try Redis first
        raw = await self.redis.get(redis_key)
        if raw:
            return InvestmentMemo.model_validate_json(raw)

        # Fall back to TimescaleDB
        async with self._session_factory() as session:
            result = await session.execute(
                text("SELECT data FROM investment_memos WHERE memo_id = :memo_id"),
                {"memo_id": str(memo_id)},
            )
            row = result.fetchone()
            if row:
                memo = InvestmentMemo.model_validate_json(row[0])
                # Re-populate Redis cache
                await self.redis.set(
                    redis_key,
                    memo.model_dump_json(),
                    ex=int(MEMO_TTL.total_seconds()),
                )
                return memo

        return None

    async def get_active_memos(self) -> list[InvestmentMemo]:
        """Get all non-terminal memos from TimescaleDB."""
        terminal_phases = ("completed", "cancelled", "rejected", "timed_out")
        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT data FROM investment_memos
                    WHERE phase NOT IN :phases
                    ORDER BY created_at DESC
                """),
                {"phases": terminal_phases},
            )
            return [InvestmentMemo.model_validate_json(row[0]) for row in result.fetchall()]

    async def get_recent(self, limit: int = 50) -> list[InvestmentMemo]:
        """Get most recent memos."""
        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT data FROM investment_memos
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"limit": limit},
            )
            return [InvestmentMemo.model_validate_json(row[0]) for row in result.fetchall()]

    async def get_all_from_redis(self) -> list[InvestmentMemo]:
        """Scan all memo keys in Redis. Used as fallback when DB is unavailable."""
        keys = []
        async for key in self.redis.scan_iter(match=f"{MEMO_KEY_PREFIX}*", count=100):
            keys.append(key)
        if not keys:
            return []
        values = await self.redis.mget(keys)
        memos = []
        for raw in values:
            if raw:
                memos.append(InvestmentMemo.model_validate_json(raw))
        return memos

    async def close(self) -> None:
        await self._engine.dispose()
        if self._redis:
            await self._redis.aclose()
