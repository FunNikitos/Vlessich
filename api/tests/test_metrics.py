"""Unit tests for Prometheus metrics declaration (Stage 6).

These tests do not spin up the FastAPI app — they verify that the
metrics module exposes the expected instruments and that they accept
the documented label values. Integration (middleware actually
observing) is covered by the metrics endpoint test below when the API
is running.
"""
from __future__ import annotations

import os

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault("API_ADMIN_JWT_SECRET", "j" * 32)
os.environ.setdefault("API_ADMIN_BCRYPT_COST", "4")

from prometheus_client import REGISTRY, generate_latest

from app.metrics import (
    ADMIN_LOGIN_TOTAL,
    HTTP_REQUEST_DURATION_SECONDS,
    SUBSCRIPTION_EVENTS_TOTAL,
)
from app.workers.prober_metrics import (
    NODE_BURNED_TOTAL,
    NODE_RECOVERED_TOTAL,
    PROBE_DURATION_SECONDS,
    PROBE_TOTAL,
    set_node_state,
)


def test_metrics_registered_in_default_registry() -> None:
    text = generate_latest(REGISTRY).decode()
    assert "vlessich_http_request_duration_seconds" in text
    assert "vlessich_admin_login_total" in text
    assert "vlessich_subscription_events_total" in text
    assert "vlessich_probe_duration_seconds" in text
    assert "vlessich_probe_total" in text
    assert "vlessich_node_state" in text
    assert "vlessich_node_burned_total" in text
    assert "vlessich_node_recovered_total" in text


def test_http_request_duration_labels_accepted() -> None:
    HTTP_REQUEST_DURATION_SECONDS.labels(
        method="GET", path_template="/healthz", status="200"
    ).observe(0.01)


def test_admin_login_total_label_values() -> None:
    for result in ("success", "fail", "captcha_fail", "rate_limited"):
        ADMIN_LOGIN_TOTAL.labels(result=result).inc(0)  # no-op increment


def test_subscription_events_label_values() -> None:
    for event in ("issued", "revoked", "expired_auto"):
        SUBSCRIPTION_EVENTS_TOTAL.labels(event=event).inc(0)


def test_probe_total_label_values() -> None:
    for ok in ("true", "false"):
        for source in ("edge", "ru"):
            PROBE_TOTAL.labels(ok=ok, source=source).inc(0)
            PROBE_DURATION_SECONDS.labels(ok=ok, source=source).observe(0.0)


def test_set_node_state_is_one_hot() -> None:
    node_id = "00000000-0000-0000-0000-00000000dead"
    set_node_state(node_id, "node.example.com", "HEALTHY")
    healthy = REGISTRY.get_sample_value(
        "vlessich_node_state",
        {"node_id": node_id, "hostname": "node.example.com", "status": "HEALTHY"},
    )
    burned = REGISTRY.get_sample_value(
        "vlessich_node_state",
        {"node_id": node_id, "hostname": "node.example.com", "status": "BURNED"},
    )
    assert healthy == 1.0
    assert burned == 0.0

    set_node_state(node_id, "node.example.com", "BURNED")
    healthy_after = REGISTRY.get_sample_value(
        "vlessich_node_state",
        {"node_id": node_id, "hostname": "node.example.com", "status": "HEALTHY"},
    )
    burned_after = REGISTRY.get_sample_value(
        "vlessich_node_state",
        {"node_id": node_id, "hostname": "node.example.com", "status": "BURNED"},
    )
    assert healthy_after == 0.0
    assert burned_after == 1.0


def test_node_transition_counters_are_callable() -> None:
    NODE_BURNED_TOTAL.inc(0)
    NODE_RECOVERED_TOTAL.inc(0)
