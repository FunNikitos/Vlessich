"""Parser unit tests (Stage 12)."""
from __future__ import annotations

import pytest

from app.services.ruleset.parsers import (
    ParsedRuleset,
    RulesetParseError,
    parse_antifilter,
    parse_by_kind,
    parse_custom_yaml,
    parse_v2fly_geosite,
)


def test_antifilter_happy_path() -> None:
    raw = "# header\n\nsber.ru\nYANDEX.RU\ngosuslugi.ru  # comment\n"
    r = parse_antifilter(raw)
    assert isinstance(r, ParsedRuleset)
    assert r.domains == ("sber.ru", "yandex.ru", "gosuslugi.ru")
    assert r.skipped == 0


def test_antifilter_skips_invalid() -> None:
    raw = "sber.ru\n!!bad!!\n-leading.com\ntrailing-.ru\n"
    r = parse_antifilter(raw)
    assert "sber.ru" in r.domains
    assert r.skipped == 3


def test_antifilter_dedup_preserves_order() -> None:
    raw = "a.ru\nb.ru\na.ru\nc.ru\nb.ru\n"
    r = parse_antifilter(raw)
    assert r.domains == ("a.ru", "b.ru", "c.ru")


def test_v2fly_prefixes_and_attributes() -> None:
    raw = (
        "domain:youtube.com\n"
        "full:facebook.com @cn\n"
        "example.org @!ads\n"
        "regexp:^.*\\.test$\n"
        "keyword:ads\n"
        "include:other-category\n"
        "# comment line\n"
    )
    r = parse_v2fly_geosite(raw)
    assert r.domains == ("youtube.com", "facebook.com", "example.org")
    # regexp + keyword + include → 3 skipped
    assert r.skipped == 3
    assert any("include" in w for w in r.warnings)


def test_v2fly_empty_yields_empty() -> None:
    r = parse_v2fly_geosite("")
    assert r.domains == ()
    assert r.skipped == 0


def test_custom_yaml_happy_path() -> None:
    raw = "domains:\n  - sber.ru\n  - GOSUSLUGI.RU\n"
    r = parse_custom_yaml(raw)
    assert r.domains == ("sber.ru", "gosuslugi.ru")


def test_custom_yaml_empty_document() -> None:
    r = parse_custom_yaml("")
    assert r.domains == ()


def test_custom_yaml_rejects_non_mapping() -> None:
    with pytest.raises(RulesetParseError):
        parse_custom_yaml("- a.ru\n- b.ru\n")


def test_custom_yaml_rejects_bad_domains_type() -> None:
    with pytest.raises(RulesetParseError):
        parse_custom_yaml("domains: sber.ru\n")


def test_custom_yaml_skips_non_strings() -> None:
    raw = "domains:\n  - sber.ru\n  - 42\n  - null\n"
    r = parse_custom_yaml(raw)
    assert r.domains == ("sber.ru",)
    assert r.skipped == 2


def test_parse_by_kind_dispatch() -> None:
    r = parse_by_kind("antifilter", "sber.ru\n")
    assert r.domains == ("sber.ru",)
    with pytest.raises(RulesetParseError):
        parse_by_kind("unknown", "")


def test_custom_ru_yaml_file_parses() -> None:
    from pathlib import Path

    path = (
        Path(__file__).resolve().parent.parent.parent
        / "infra"
        / "smart-routing"
        / "custom-ru.yml"
    )
    raw = path.read_text(encoding="utf-8")
    r = parse_custom_yaml(raw)
    assert r.domain_count >= 20
    assert "sber.ru" in r.domains
    assert "gosuslugi.ru" in r.domains
