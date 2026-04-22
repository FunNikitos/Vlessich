"""Pure-python parsers for ruleset feeds (sans-I/O).

Each parser takes the raw bytes already decoded as ``str`` and returns
:class:`ParsedRuleset` with normalized lowercase domains, dedup'd while
preserving first-seen order. Parsers DO NOT touch the network or DB —
they're trivially testable and worker-agnostic.

Supported formats (TZ §8.2):

* ``antifilter``    — line-oriented ``.lst`` (``# comments``, blanks).
* ``v2fly_geosite`` — line-oriented ``data/category-*`` from
  ``v2fly/domain-list-community``. Supports prefixes ``domain:`` / ``full:``
  (treated as exact suffix match) and ``keyword:`` (skipped — singbox
  rule_set semantics differ; we only emit suffix rules here).
  ``regexp:`` lines are skipped for the same reason.
* ``custom``        — local YAML (``infra/smart-routing/custom-ru.yml``)
  with shape ``{domains: [str, ...]}``. Comments / inline ``#`` allowed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml


_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(?:\.(?!-)[a-z0-9-]{1,63}(?<!-))+$"
)


class RulesetParseError(ValueError):
    """Raised when a payload is structurally invalid (not parseable at all)."""


@dataclass(frozen=True, slots=True)
class ParsedRuleset:
    """Normalized output of any parser."""

    kind: str
    domains: tuple[str, ...]
    skipped: int = 0
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def domain_count(self) -> int:
        return len(self.domains)


def _normalize_domain(raw: str) -> str | None:
    """Strip whitespace, lowercase, drop trailing dot; return None if invalid."""
    d = raw.strip().rstrip(".").lower()
    if not d:
        return None
    if not _DOMAIN_RE.match(d):
        return None
    return d


def _dedup_keep_order(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for d in items:
        if d in seen:
            continue
        seen.add(d)
        out.append(d)
    return tuple(out)


def parse_antifilter(raw: str) -> ParsedRuleset:
    """Parse ``community.antifilter.network`` ``.lst`` payload."""
    domains: list[str] = []
    skipped = 0
    for line in raw.splitlines():
        # Strip inline comments AND surrounding whitespace.
        s = line.split("#", 1)[0].strip()
        if not s:
            continue
        d = _normalize_domain(s)
        if d is None:
            skipped += 1
            continue
        domains.append(d)
    return ParsedRuleset(
        kind="antifilter",
        domains=_dedup_keep_order(domains),
        skipped=skipped,
    )


def parse_v2fly_geosite(raw: str) -> ParsedRuleset:
    """Parse a ``v2fly/domain-list-community/data/category-*`` file.

    Lines beginning with ``regexp:`` or ``keyword:`` are intentionally
    skipped — singbox rule_set ``domain_suffix`` cannot represent them
    losslessly, and including substrings would risk over-blocking. The
    skipped count is surfaced so admin can decide whether to enrich.

    Inline comments after ``@`` (attribute tags like ``@cn``) are dropped
    — we treat the whole file as the requested category already.
    """
    domains: list[str] = []
    skipped = 0
    warnings: list[str] = []
    for line in raw.splitlines():
        s = line.split("#", 1)[0].strip()
        if not s:
            continue
        # v2fly attribute tags: "example.com @cn @!ads"
        s = s.split("@", 1)[0].strip()
        if not s:
            continue
        if s.startswith(("regexp:", "keyword:")):
            skipped += 1
            continue
        if s.startswith("domain:"):
            s = s[len("domain:") :].strip()
        elif s.startswith("full:"):
            s = s[len("full:") :].strip()
        elif s.startswith("include:"):
            # include:another-category — out of scope for sans-I/O parser.
            warnings.append(f"include directive ignored: {s}")
            skipped += 1
            continue
        d = _normalize_domain(s)
        if d is None:
            skipped += 1
            continue
        domains.append(d)
    return ParsedRuleset(
        kind="v2fly_geosite",
        domains=_dedup_keep_order(domains),
        skipped=skipped,
        warnings=tuple(warnings),
    )


def parse_custom_yaml(raw: str) -> ParsedRuleset:
    """Parse local ``infra/smart-routing/custom-ru.yml`` payload.

    Expected shape::

        domains:
          - sber.ru
          - gosuslugi.ru
    """
    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:  # noqa: BLE001
        raise RulesetParseError(f"invalid YAML: {exc}") from exc
    if doc is None:
        return ParsedRuleset(kind="custom", domains=())
    if not isinstance(doc, dict):
        raise RulesetParseError("custom YAML must be a mapping")
    items = doc.get("domains", [])
    if not isinstance(items, list):
        raise RulesetParseError("custom YAML 'domains' must be a list")
    domains: list[str] = []
    skipped = 0
    for item in items:
        if not isinstance(item, str):
            skipped += 1
            continue
        d = _normalize_domain(item)
        if d is None:
            skipped += 1
            continue
        domains.append(d)
    return ParsedRuleset(
        kind="custom",
        domains=_dedup_keep_order(domains),
        skipped=skipped,
    )


_PARSERS = {
    "antifilter": parse_antifilter,
    "v2fly_geosite": parse_v2fly_geosite,
    "custom": parse_custom_yaml,
}


def parse_by_kind(kind: str, raw: str) -> ParsedRuleset:
    """Dispatch by source kind. Raises ``RulesetParseError`` for unknown kinds."""
    parser = _PARSERS.get(kind)
    if parser is None:
        raise RulesetParseError(f"unknown ruleset kind: {kind!r}")
    return parser(raw)
