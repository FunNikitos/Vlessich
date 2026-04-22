"""Smart-routing config builder (sans-I/O).

Given the set of current :class:`RulesetSnapshot` rows and a routing
profile, produce engine-specific routing configs:

* singbox JSON (primary; TZ §8.4).
* clash YAML  (fallback for clients without sing-box support).

Design goals:

1. **Deterministic output** — given the same inputs, the builder emits
   byte-identical JSON/YAML. Bucket domains are sorted; top-level keys
   are ordered.
2. **Profile-aware** — ``full`` enables RU-direct + ads-block,
   ``smart`` only RU-direct, ``adblock`` only ads-block, ``plain``
   emits an empty routing block (caller decides to omit entirely).
3. **Sans-I/O** — no DB / HTTP / disk access. Inputs are already
   fetched snapshot rows. Unit tests feed synthetic input.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

import yaml

RoutingProfile = Literal["full", "smart", "adblock", "plain"]

_VALID_PROFILES: frozenset[str] = frozenset(("full", "smart", "adblock", "plain"))


@dataclass(frozen=True, slots=True)
class SnapshotBundle:
    """Parsed snapshot content grouped by category.

    ``ru_domains`` / ``ads_domains`` are pre-merged + deduped tuples
    (caller is responsible for combining multi-source lists). Sorted
    lexicographically by :meth:`normalize` before use.
    """

    ru_domains: tuple[str, ...] = ()
    ads_domains: tuple[str, ...] = ()

    def normalize(self) -> SnapshotBundle:
        return SnapshotBundle(
            ru_domains=tuple(sorted(set(self.ru_domains))),
            ads_domains=tuple(sorted(set(self.ads_domains))),
        )


class UnsupportedProfile(ValueError):
    """Raised when an invalid routing profile string is supplied."""


def _validate(profile: str) -> RoutingProfile:
    if profile not in _VALID_PROFILES:
        raise UnsupportedProfile(f"unknown routing profile: {profile!r}")
    return profile  # type: ignore[return-value]


def _wants_ru(p: RoutingProfile) -> bool:
    return p in ("full", "smart")


def _wants_ads(p: RoutingProfile) -> bool:
    return p in ("full", "adblock")


def build_singbox_route(
    bundle: SnapshotBundle, profile: str
) -> dict[str, object]:
    """Build sing-box ``route`` block.

    Schema matches sing-box 1.10+ with inline ``rules`` referring to
    synthetic rule-set tags we emit under ``rule_set``. Upstream proxy
    outbound is assumed to be ``proxy`` (configured elsewhere in the
    sub payload); ``direct`` and ``block`` are sing-box builtins.

    ``plain`` yields an empty rules/rule_set but still returns the key so
    callers can uniformly merge; the handler decides whether to omit.
    """
    p = _validate(profile)
    b = bundle.normalize()

    rule_sets: list[dict[str, object]] = []
    rules: list[dict[str, object]] = []

    if _wants_ads(p) and b.ads_domains:
        rule_sets.append(
            {
                "tag": "vlessich-ads",
                "type": "inline",
                "format": "source",
                "rules": [
                    {"domain_suffix": list(b.ads_domains)},
                ],
            }
        )
        # Ads rule runs FIRST — blocking takes priority over RU-direct so
        # an ad domain on a RU TLD still gets blocked.
        rules.append({"rule_set": "vlessich-ads", "outbound": "block"})

    if _wants_ru(p) and b.ru_domains:
        rule_sets.append(
            {
                "tag": "vlessich-ru",
                "type": "inline",
                "format": "source",
                "rules": [
                    {"domain_suffix": list(b.ru_domains)},
                ],
            }
        )
        rules.append({"rule_set": "vlessich-ru", "outbound": "direct"})

    route: dict[str, object] = {
        "rule_set": rule_sets,
        "rules": rules,
        "final": "proxy",
        "auto_detect_interface": True,
    }
    return route


def build_clash_rules(bundle: SnapshotBundle, profile: str) -> dict[str, object]:
    """Build Clash/Mihomo ``rules`` + ``rule-providers`` block.

    Clash uses ``DOMAIN-SUFFIX,<domain>,<outbound>`` inline; since v3
    supports ``rule-providers`` with inline provider type we keep the
    groups as inline rules for maximum client compatibility (some
    forks still lack inline providers).

    Outbounds referenced:
      * ``PROXY``  — upstream proxy group (defined elsewhere).
      * ``DIRECT`` — clash builtin.
      * ``REJECT`` — clash builtin (drops the connection).
    """
    p = _validate(profile)
    b = bundle.normalize()

    rules: list[str] = []

    if _wants_ads(p):
        for d in b.ads_domains:
            rules.append(f"DOMAIN-SUFFIX,{d},REJECT")

    if _wants_ru(p):
        for d in b.ru_domains:
            rules.append(f"DOMAIN-SUFFIX,{d},DIRECT")

    # Final fallthrough: everything else → proxy.
    rules.append("MATCH,PROXY")

    return {"rules": rules}


def render_singbox_json(bundle: SnapshotBundle, profile: str) -> str:
    route = build_singbox_route(bundle, profile)
    # Stable, deterministic text form for snapshot testing.
    return json.dumps({"route": route}, sort_keys=True, indent=2, ensure_ascii=False)


def render_clash_yaml(bundle: SnapshotBundle, profile: str) -> str:
    block = build_clash_rules(bundle, profile)
    return yaml.safe_dump(block, sort_keys=False, allow_unicode=True)


__all__ = [
    "RoutingProfile",
    "SnapshotBundle",
    "UnsupportedProfile",
    "build_singbox_route",
    "build_clash_rules",
    "render_singbox_json",
    "render_clash_yaml",
]
