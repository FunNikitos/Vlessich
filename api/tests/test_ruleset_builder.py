"""Builder unit tests (Stage 12)."""
from __future__ import annotations

import json

import pytest
import yaml

from app.services.ruleset.builder import (
    SnapshotBundle,
    UnsupportedProfile,
    build_clash_rules,
    build_singbox_route,
    render_clash_yaml,
    render_singbox_json,
)


def _bundle() -> SnapshotBundle:
    return SnapshotBundle(
        ru_domains=("sber.ru", "yandex.ru", "gosuslugi.ru"),
        ads_domains=("doubleclick.net", "googleadservices.com"),
    )


def test_singbox_full_profile_has_both_rules() -> None:
    route = build_singbox_route(_bundle(), "full")
    assert route["final"] == "proxy"
    tags = [rs["tag"] for rs in route["rule_set"]]
    assert "vlessich-ru" in tags and "vlessich-ads" in tags
    outbounds = [r["outbound"] for r in route["rules"]]
    # ads rule must come BEFORE ru so blocking wins on ru TLDs.
    assert outbounds.index("block") < outbounds.index("direct")


def test_singbox_smart_profile_no_ads() -> None:
    route = build_singbox_route(_bundle(), "smart")
    tags = [rs["tag"] for rs in route["rule_set"]]
    assert tags == ["vlessich-ru"]


def test_singbox_adblock_profile_no_ru() -> None:
    route = build_singbox_route(_bundle(), "adblock")
    tags = [rs["tag"] for rs in route["rule_set"]]
    assert tags == ["vlessich-ads"]


def test_singbox_plain_profile_has_empty_rules() -> None:
    route = build_singbox_route(_bundle(), "plain")
    assert route["rules"] == []
    assert route["rule_set"] == []
    assert route["final"] == "proxy"


def test_singbox_domains_sorted() -> None:
    route = build_singbox_route(_bundle(), "smart")
    # inner rule list should be sorted alphabetically
    inner = route["rule_set"][0]["rules"][0]["domain_suffix"]
    assert inner == sorted(inner)


def test_unknown_profile_raises() -> None:
    with pytest.raises(UnsupportedProfile):
        build_singbox_route(_bundle(), "crazy")


def test_render_singbox_json_is_deterministic() -> None:
    a = render_singbox_json(_bundle(), "full")
    b = render_singbox_json(_bundle(), "full")
    assert a == b
    parsed = json.loads(a)
    assert parsed["route"]["final"] == "proxy"


def test_clash_rules_contain_reject_and_direct_and_match() -> None:
    block = build_clash_rules(_bundle(), "full")
    rules = block["rules"]
    assert any(r.startswith("DOMAIN-SUFFIX,doubleclick.net,REJECT") for r in rules)
    assert any(r.startswith("DOMAIN-SUFFIX,sber.ru,DIRECT") for r in rules)
    assert rules[-1] == "MATCH,PROXY"


def test_clash_plain_only_match() -> None:
    block = build_clash_rules(_bundle(), "plain")
    assert block["rules"] == ["MATCH,PROXY"]


def test_render_clash_yaml_is_valid_yaml() -> None:
    text = render_clash_yaml(_bundle(), "full")
    doc = yaml.safe_load(text)
    assert "rules" in doc
    assert doc["rules"][-1] == "MATCH,PROXY"


def test_dod_sber_direct_youtube_proxy() -> None:
    """TZ §16 DoD: sber.ru direct, everything else (youtube.com) proxy."""
    bundle = SnapshotBundle(ru_domains=("sber.ru",))
    route = build_singbox_route(bundle, "full")
    # sber.ru is in the ru rule-set, routed direct.
    ru_rules = [rs for rs in route["rule_set"] if rs["tag"] == "vlessich-ru"][0]
    assert "sber.ru" in ru_rules["rules"][0]["domain_suffix"]
    direct_rule = next(r for r in route["rules"] if r["outbound"] == "direct")
    assert direct_rule["rule_set"] == "vlessich-ru"
    # Default → proxy. No rule for youtube.com means it falls through.
    assert route["final"] == "proxy"
