"""Smart-routing internal endpoints (Stage 12).

Two HMAC-protected endpoints called by the bot during the ``/config`` flow:

* ``POST /internal/smart_routing/config`` — given ``tg_id`` + ``fmt``,
  return the rendered routing config (singbox JSON or clash YAML) for
  the user's current subscription profile.
* ``POST /internal/smart_routing/set_profile`` — change the current
  subscription's ``routing_profile`` (and mirror the legacy ``adblock``
  / ``smart_routing`` bool flags so existing Mini-App toggles agree).

Both gate on ``API_SMART_ROUTING_ENABLED``; off → ``409
SMART_ROUTING_DISABLED``.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiCode, api_error
from app.models import RulesetSnapshot, RulesetSource, Subscription
from app.schemas import (
    SetRoutingProfileIn,
    SetRoutingProfileOut,
    SmartRoutingConfigIn,
    SmartRoutingConfigOut,
)
from app.security import verify_internal_signature
from app.services.ruleset.builder import (
    SnapshotBundle,
    UnsupportedProfile,
    render_clash_yaml,
    render_singbox_json,
)
from app.services.ruleset.parsers import RulesetParseError, parse_by_kind

router = APIRouter(
    prefix="/internal/smart_routing",
    tags=["internal", "smart-routing"],
    dependencies=[Depends(verify_internal_signature)],
)


_PROFILE_TO_FLAGS: dict[str, tuple[bool, bool]] = {
    # (smart_routing, adblock)
    "full": (True, True),
    "smart": (True, False),
    "adblock": (False, True),
    "plain": (False, False),
}


def _ensure_enabled(settings: Settings) -> None:
    if not settings.smart_routing_enabled:
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiCode.SMART_ROUTING_DISABLED,
            "Smart routing is disabled.",
        )


async def _load_active_subscription(
    session: AsyncSession, tg_id: int
) -> Subscription:
    sub = await session.scalar(
        select(Subscription).where(
            Subscription.user_id == tg_id,
            Subscription.status.in_(("ACTIVE", "TRIAL")),
        )
    )
    if sub is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            ApiCode.NO_SUBSCRIPTION,
            "Active subscription not found.",
        )
    return sub


async def _load_current_bundle(session: AsyncSession) -> SnapshotBundle:
    """Aggregate current snapshots across enabled sources by category."""
    rows = (
        await session.execute(
            select(RulesetSource, RulesetSnapshot)
            .join(
                RulesetSnapshot,
                (RulesetSnapshot.source_id == RulesetSource.id)
                & (RulesetSnapshot.is_current.is_(True)),
            )
            .where(RulesetSource.is_enabled.is_(True))
        )
    ).all()
    ru: list[str] = []
    ads: list[str] = []
    for src, snap in rows:
        try:
            parsed = parse_by_kind(src.kind, snap.raw)
        except RulesetParseError:
            # Snapshot was accepted at fetch-time, but if the parser is
            # now stricter we skip silently rather than 500.
            continue
        if src.category == "ads":
            ads.extend(parsed.domains)
        else:
            ru.extend(parsed.domains)
    return SnapshotBundle(ru_domains=tuple(ru), ads_domains=tuple(ads)).normalize()


@router.post("/config", response_model=SmartRoutingConfigOut)
async def get_config(
    payload: SmartRoutingConfigIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SmartRoutingConfigOut:
    _ensure_enabled(settings)
    sub = await _load_active_subscription(session, payload.tg_id)
    bundle = await _load_current_bundle(session)
    try:
        if payload.fmt == "singbox":
            body = render_singbox_json(bundle, sub.routing_profile)
        else:
            body = render_clash_yaml(bundle, sub.routing_profile)
    except UnsupportedProfile as exc:
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiCode.INVALID_ROUTING_PROFILE,
            "Invalid routing profile on subscription.",
        ) from exc
    return SmartRoutingConfigOut(
        profile=sub.routing_profile,  # type: ignore[arg-type]
        fmt=payload.fmt,
        body=body,
        ru_count=len(bundle.ru_domains),
        ads_count=len(bundle.ads_domains),
        generated_at=datetime.now(UTC),
    )


@router.post("/set_profile", response_model=SetRoutingProfileOut)
async def set_profile(
    payload: SetRoutingProfileIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SetRoutingProfileOut:
    _ensure_enabled(settings)
    if payload.profile not in _PROFILE_TO_FLAGS:
        raise api_error(
            status.HTTP_400_BAD_REQUEST,
            ApiCode.INVALID_ROUTING_PROFILE,
            "Unknown routing profile.",
        )
    sub = await _load_active_subscription(session, payload.tg_id)
    sr, ab = _PROFILE_TO_FLAGS[payload.profile]
    sub.routing_profile = payload.profile
    sub.smart_routing = sr
    sub.adblock = ab
    await session.flush()
    return SetRoutingProfileOut(
        subscription_id=str(sub.id),
        profile=payload.profile,
        adblock=ab,
        smart_routing=sr,
    )
