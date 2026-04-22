"""Async SQLAlchemy engine + session factory + Redis client."""
from __future__ import annotations

from collections.abc import AsyncIterator

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_redis: Redis | None = None


def init_engine(url: str) -> None:
    global _engine, _sessionmaker
    _engine = create_async_engine(url, pool_pre_ping=True, future=True)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)


def init_redis(url: str) -> None:
    global _redis
    _redis = Redis.from_url(url, decode_responses=True)


async def close_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("DB not initialized (call init_engine on app startup)")
    return _sessionmaker


def get_redis() -> Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialized (call init_redis on app startup)")
    return _redis


async def get_session() -> AsyncIterator[AsyncSession]:
    sm = get_sessionmaker()
    async with sm() as session:
        yield session
