"""Remnawave client interface + in-memory mock.

Stage 1 uses the mock (``MockRemnawaveClient``). Stage 2 will add an HTTP
implementation behind the same ``RemnawaveClient`` ABC so the business layer
stays unchanged.

Contract notes:
- ``sub_token`` is opaque; Mini-App queries sub-Worker with it to fetch the
  actual subscription URL. We return a 64-char hex token here.
- Remna user id is the provider's internal handle; we store it in
  ``subscriptions.remna_user_id`` for later extend/revoke calls.
"""
from __future__ import annotations

import abc
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID


@dataclass(slots=True, frozen=True)
class RemnaUser:
    remna_user_id: str
    sub_token: str
    expires_at: datetime


class RemnawaveClient(abc.ABC):
    @abc.abstractmethod
    async def create_user(
        self, subscription_id: UUID, plan: str, ttl_days: int
    ) -> RemnaUser: ...

    @abc.abstractmethod
    async def extend_user(self, remna_user_id: str, ttl_days: int) -> datetime: ...

    @abc.abstractmethod
    async def revoke_user(self, remna_user_id: str) -> None: ...

    @abc.abstractmethod
    async def get_subscription_url(self, remna_user_id: str) -> str: ...


@dataclass(slots=True)
class _MockRecord:
    remna_user_id: str
    sub_token: str
    plan: str
    expires_at: datetime
    revoked: bool = False


@dataclass(slots=True)
class MockRemnawaveClient(RemnawaveClient):
    """In-memory mock. State is per-instance — inject a singleton via DI."""

    _by_user: dict[str, _MockRecord] = field(default_factory=dict)

    async def create_user(
        self, subscription_id: UUID, plan: str, ttl_days: int
    ) -> RemnaUser:
        if ttl_days <= 0:
            raise ValueError("ttl_days must be positive")
        remna_user_id = f"remna-{subscription_id}"
        sub_token = secrets.token_hex(32)
        expires_at = datetime.now(UTC) + timedelta(days=ttl_days)
        self._by_user[remna_user_id] = _MockRecord(
            remna_user_id=remna_user_id,
            sub_token=sub_token,
            plan=plan,
            expires_at=expires_at,
        )
        return RemnaUser(
            remna_user_id=remna_user_id, sub_token=sub_token, expires_at=expires_at
        )

    async def extend_user(self, remna_user_id: str, ttl_days: int) -> datetime:
        record = self._by_user.get(remna_user_id)
        if record is None or record.revoked:
            raise KeyError(f"remna user {remna_user_id} not found")
        base = max(record.expires_at, datetime.now(UTC))
        record.expires_at = base + timedelta(days=ttl_days)
        return record.expires_at

    async def revoke_user(self, remna_user_id: str) -> None:
        record = self._by_user.get(remna_user_id)
        if record is None:
            return
        record.revoked = True

    async def get_subscription_url(self, remna_user_id: str) -> str:
        record = self._by_user.get(remna_user_id)
        if record is None or record.revoked:
            raise KeyError(f"remna user {remna_user_id} not found")
        return f"https://sub.example.com/{record.sub_token}"


_MOCK_SINGLETON = MockRemnawaveClient()


def get_remnawave() -> RemnawaveClient:
    """FastAPI dependency. Stage 2 swaps this with the HTTP implementation."""
    return _MOCK_SINGLETON
