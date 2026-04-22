"""Stage 12: smart-routing ruleset subsystem.

Public surface (sans-I/O modules):

* :mod:`.parsers` — pure-python parsers for antifilter / v2fly geosite /
  custom YAML payloads. Input ``str``, output normalized ``ParsedRuleset``.
* :mod:`.builder` — assemble singbox JSON / clash YAML routing configs
  from current ``RulesetSnapshot`` rows + per-subscription profile.
* :mod:`.puller` — async fetch+upsert helper used by the
  ``ruleset_puller`` worker and admin "force-pull" endpoint.
"""
from __future__ import annotations

from .parsers import (
    ParsedRuleset,
    RulesetParseError,
    parse_antifilter,
    parse_custom_yaml,
    parse_v2fly_geosite,
    parse_by_kind,
)

__all__ = [
    "ParsedRuleset",
    "RulesetParseError",
    "parse_antifilter",
    "parse_custom_yaml",
    "parse_v2fly_geosite",
    "parse_by_kind",
]
