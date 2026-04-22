"""Tests for ``MockRemnawaveClient``."""
from __future__ import annotations

import uuid

import pytest

from app.services.remnawave import MockRemnawaveClient


@pytest.mark.asyncio
async def test_create_user_produces_unique_tokens() -> None:
    client = MockRemnawaveClient()
    a = await client.create_user(uuid.uuid4(), "month", 30)
    b = await client.create_user(uuid.uuid4(), "month", 30)
    assert a.sub_token != b.sub_token
    assert len(a.sub_token) == 64


@pytest.mark.asyncio
async def test_extend_user_moves_expiry_forward() -> None:
    client = MockRemnawaveClient()
    u = await client.create_user(uuid.uuid4(), "month", 3)
    new_exp = await client.extend_user(u.remna_user_id, 30)
    assert new_exp > u.expires_at


@pytest.mark.asyncio
async def test_extend_unknown_user_raises() -> None:
    client = MockRemnawaveClient()
    with pytest.raises(KeyError):
        await client.extend_user("remna-missing", 30)


@pytest.mark.asyncio
async def test_revoke_then_url_raises() -> None:
    client = MockRemnawaveClient()
    u = await client.create_user(uuid.uuid4(), "month", 3)
    await client.revoke_user(u.remna_user_id)
    with pytest.raises(KeyError):
        await client.get_subscription_url(u.remna_user_id)


@pytest.mark.asyncio
async def test_create_user_rejects_nonpositive_ttl() -> None:
    client = MockRemnawaveClient()
    with pytest.raises(ValueError, match="ttl_days"):
        await client.create_user(uuid.uuid4(), "trial", 0)
