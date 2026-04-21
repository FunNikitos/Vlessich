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

from prometheus_client import Counter, Histogram

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


__all__ = [
    "HTTP_REQUEST_DURATION_SECONDS",
    "ADMIN_LOGIN_TOTAL",
    "SUBSCRIPTION_EVENTS_TOTAL",
]
