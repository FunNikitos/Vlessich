"""Contract tests: Mock vs HTTP remnawave client (Stage 2 T3).

The two implementations MUST behave identically for the public interface.
HTTP is exercised through ``respx`` (added to dev deps); when ``respx`` is
not installed locally the HTTP suite is skipped.
"""
from __future__ import annotations

import os

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault(
    "API_DATABASE_URL", "postgresql+asyncpg://vlessich:vlessich@localhost:5432/vlessich"
)

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.services.remnawave import (
    HTTPRemnawaveClient,
    MockRemnawaveClient,
    RemnaUser,
    RemnawaveClient,
)

respx = pytest.importorskip("respx")


@pytest.fixture
def mock_client() -> RemnawaveClient:
    return MockRemnawaveClient()


@pytest.fixture
async def http_client():
    client = HTTPRemnawaveClient(
        base_url="http://remna.test", api_key="test-key", max_retries=1
    )
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_mock_create_extend_revoke(mock_client: RemnawaveClient) -> None:
    sub_id = uuid4()
    user = await mock_client.create_user(sub_id, plan="3m", ttl_days=90)
    assert isinstance(user, RemnaUser)
    assert len(user.sub_token) == 64
    new_exp = await mock_client.extend_user(user.remna_user_id, ttl_days=30)
    assert new_exp > user.expires_at
    await mock_client.revoke_user(user.remna_user_id)
    with pytest.raises(KeyError):
        await mock_client.get_subscription_url(user.remna_user_id)


@pytest.mark.asyncio
async def test_http_create_user(http_client: HTTPRemnawaveClient) -> None:
    sub_id = uuid4()
    expires = (datetime.now(UTC) + timedelta(days=90)).isoformat()
    with respx.mock(base_url="http://remna.test") as router:
        router.post("/api/users").respond(
            200,
            json={
                "id": "remna-abc",
                "sub_token": "f" * 64,
                "expires_at": expires,
            },
        )
        user = await http_client.create_user(sub_id, plan="3m", ttl_days=90)
    assert user.remna_user_id == "remna-abc"
    assert user.sub_token == "f" * 64


@pytest.mark.asyncio
async def test_http_revoke_404_is_silent(http_client: HTTPRemnawaveClient) -> None:
    with respx.mock(base_url="http://remna.test") as router:
        router.delete("/api/users/missing").respond(404)
        await http_client.revoke_user("missing")  # no raise


@pytest.mark.asyncio
async def test_http_extend_404_raises_keyerror(http_client: HTTPRemnawaveClient) -> None:
    with respx.mock(base_url="http://remna.test") as router:
        router.patch("/api/users/missing/extend").respond(404)
        with pytest.raises(KeyError):
            await http_client.extend_user("missing", ttl_days=30)


@pytest.mark.asyncio
async def test_http_5xx_retries_then_fails(http_client: HTTPRemnawaveClient) -> None:
    with respx.mock(base_url="http://remna.test") as router:
        router.post("/api/users").respond(503)
        from app.services.remnawave import RemnawaveError

        with pytest.raises(RemnawaveError):
            await http_client.create_user(uuid4(), plan="3m", ttl_days=90)
