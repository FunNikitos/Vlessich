"""Prometheus metrics for the API process (Stage 6).

Single module-level registry + instruments. The ``/metrics`` endpoint in
``app.main`` exposes ``prometheus_client.REGISTRY`` which automatically
includes everything declared here.

Conventions:
- All metric names start with ``vlessich_``.
- Histogram for HTTP latency uses default buckets.
- Counters use enumerated label values; never put unbounded user data
  (tg_id, ip) in labels.
"""
from __future__ import annotations

from typing import Final

from prometheus_client import Counter, Gauge, Histogram

# HTTP request latency, labelled by route template (NOT raw path) so
# cardinality stays bounded. ``status`` is the integer HTTP status
# rendered as a string.
HTTP_REQUEST_DURATION_SECONDS: Final = Histogram(
    "vlessich_http_request_duration_seconds",
    "HTTP request duration (seconds), labelled by route template.",
    labelnames=("method", "path_template", "status"),
)

# Admin login outcomes. Result is one of:
#   success | fail | captcha_fail | rate_limited
ADMIN_LOGIN_TOTAL: Final = Counter(
    "vlessich_admin_login_total",
    "Admin login attempts by outcome.",
    labelnames=("result",),
)

# Domain-level subscription events (Stage 1+). Event is one of:
#   issued | revoked | expired_auto
SUBSCRIPTION_EVENTS_TOTAL: Final = Counter(
    "vlessich_subscription_events_total",
    "Subscription lifecycle events.",
    labelnames=("event",),
)

# Stage 10: MTProto rotation broadcast pipeline.
# status: ok | failed | cooldown | duplicate | throttled
MTPROTO_BROADCAST_SENT_TOTAL: Final = Counter(
    "vlessich_mtproto_broadcast_sent_total",
    "MTProto rotation broadcast DM dispatch outcomes.",
    labelnames=("status",),
)
# result: rotated | skipped | error
MTPROTO_AUTO_ROTATION_TOTAL: Final = Counter(
    "vlessich_mtproto_auto_rotation_total",
    "Cron-driven MTProto shared-secret rotation outcomes.",
    labelnames=("result",),
)
# Age of the currently-ACTIVE shared MTProto secret in seconds.
# Updated by the rotator worker after each tick.
MTPROTO_SHARED_SECRET_AGE_SECONDS: Final = Gauge(
    "vlessich_mtproto_shared_secret_age_seconds",
    "Age (seconds) of the currently-ACTIVE shared MTProto secret.",
)


__all__ = [
    "HTTP_REQUEST_DURATION_SECONDS",
    "ADMIN_LOGIN_TOTAL",
    "SUBSCRIPTION_EVENTS_TOTAL",
    "MTPROTO_BROADCAST_SENT_TOTAL",
    "MTPROTO_AUTO_ROTATION_TOTAL",
    "MTPROTO_SHARED_SECRET_AGE_SECONDS",
]
