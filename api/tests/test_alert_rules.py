"""Schema / structure validation for Stage 7 alert rules.

Does not require a running Prometheus: we only assert the file is
valid YAML and conforms to the rule-file shape Prometheus expects
(``groups[].rules[]`` with either ``alert`` + ``expr`` or
``record`` + ``expr``). Use ``promtool check rules`` in CI for the
real semantic validation.
"""
from __future__ import annotations

from pathlib import Path

import yaml


_RULES = (
    Path(__file__).resolve().parent.parent.parent
    / "infra"
    / "prometheus"
    / "rules"
    / "vlessich.yml"
)


def test_rules_file_exists() -> None:
    assert _RULES.is_file(), f"missing {_RULES}"


def test_rules_structure() -> None:
    doc = yaml.safe_load(_RULES.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    assert "groups" in doc and isinstance(doc["groups"], list)
    assert doc["groups"], "at least one group expected"

    seen_alerts: set[str] = set()
    for group in doc["groups"]:
        assert "name" in group
        assert "rules" in group and isinstance(group["rules"], list)
        for rule in group["rules"]:
            assert "expr" in rule and rule["expr"].strip()
            if "alert" in rule:
                seen_alerts.add(rule["alert"])
                assert "labels" in rule and "severity" in rule["labels"]
                assert rule["labels"]["severity"] in {
                    "info",
                    "warning",
                    "critical",
                }
                assert "annotations" in rule and "summary" in rule["annotations"]
            else:
                assert "record" in rule

    # Ensure the five Stage-7 alerts we documented are present.
    assert {
        "NodeBurnSpike",
        "ProbeSuccessLow",
        "ProberDown",
        "ApiP95Latency",
        "AdminCaptchaFailSpike",
    } <= seen_alerts


def test_stage12_ruleset_alerts_present() -> None:
    doc = yaml.safe_load(_RULES.read_text(encoding="utf-8"))
    seen = {
        rule["alert"]
        for group in doc["groups"]
        for rule in group["rules"]
        if "alert" in rule
    }
    assert {"RulesetPullFailures", "RulesetStale"} <= seen
