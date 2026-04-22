"""CLI: idempotently create/update a superadmin account (Stage 13).

Used by scripts/install.sh to bootstrap an admin user after compose up.
Re-runs are safe: if the email already exists, we skip (exit 0) unless
--force-reset-password is passed.

Usage:
    python -m app.scripts.create_admin \\
        --email admin@example.com \\
        --password '<plaintext>' \\
        --role superadmin

Exit codes:
    0  admin created, or already exists (no change)
    0  password reset (with --force-reset-password)
    2  argument / role invalid
    3  DB error
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Literal

from sqlalchemy import select

from app.auth.admin import hash_password
from app.config import get_settings
from app.db import close_engine, get_sessionmaker, init_engine
from app.models import AdminUser

Role = Literal["superadmin", "support", "readonly"]
_ROLES: tuple[Role, ...] = ("superadmin", "support", "readonly")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Create or ensure an admin user")
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--role", default="superadmin", choices=list(_ROLES))
    p.add_argument(
        "--force-reset-password",
        action="store_true",
        help="If user exists, overwrite password_hash (default: leave untouched)",
    )
    return p.parse_args()


async def _run(
    email: str, password: str, role: str, force_reset: bool
) -> int:
    settings = get_settings()
    init_engine(settings.database_url)
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            existing = (
                await session.execute(
                    select(AdminUser).where(AdminUser.email == email)
                )
            ).scalar_one_or_none()

            if existing is None:
                session.add(
                    AdminUser(
                        email=email,
                        password_hash=hash_password(password),
                        role=role,
                        status="ACTIVE",
                    )
                )
                await session.commit()
                print(f"[create_admin] created superadmin={email} role={role}")
                return 0

            if force_reset:
                existing.password_hash = hash_password(password)
                existing.role = role  # type: ignore[assignment]
                existing.status = "ACTIVE"
                await session.commit()
                print(
                    f"[create_admin] reset password for {email} (role={role})"
                )
                return 0

            print(
                f"[create_admin] {email} already exists (role={existing.role},"
                f" status={existing.status}) — no-op"
            )
            return 0
    finally:
        await close_engine()


def main() -> int:
    args = _parse_args()
    if args.role not in _ROLES:
        print(f"invalid role: {args.role}", file=sys.stderr)
        return 2
    try:
        return asyncio.run(
            _run(args.email, args.password, args.role, args.force_reset_password)
        )
    except Exception as exc:  # pragma: no cover - bootstrap CLI
        print(f"[create_admin] error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
