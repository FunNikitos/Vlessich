"""Prometheus metrics for the prober worker (Stage 6).

The prober runs as a separate process. It exposes its own ``/metrics``
endpoint via ``prometheus_client.start_http_server`` (called from
``app.workers.prober.main``). Metrics declared here use the default
global registry so ``start_http_server`` picks them up automatically.
"""
from __future__ import annotations

from typing import Final

from prometheus_client import Counter, Gauge, Histogram

PROBE_DURATION_SECONDS: Final = Histogram(
    "vlessich_probe_duration_seconds",
    "Per-node probe duration (seconds), labelled by outcome and source.",
    labelnames=("ok", "source"),
)

PROBE_TOTAL: Final = Counter(
    "vlessich_probe_total",
    "Total probes executed, labelled by outcome and source.",
    labelnames=("ok", "source"),
)

# One-hot Gauge: for each (node_id, hostname) we set the row matching
# current ``status`` to 1.0 and clear all other status rows to 0.0.
# Cardinality bound: |nodes| * |statuses|. Statuses are small enum.
NODE_STATE: Final = Gauge(
    "vlessich_node_state",
    "Current node state (1.0 if matches label status, 0.0 otherwise).",
    labelnames=("node_id", "hostname", "status"),
)

NODE_BURNED_TOTAL: Final = Counter(
    "vlessich_node_burned_total",
    "Transitions HEALTHY -> BURNED.",
)

NODE_RECOVERED_TOTAL: Final = Counter(
    "vlessich_node_recovered_total",
    "Transitions BURNED -> HEALTHY.",
)


_NODE_STATUSES: Final = ("HEALTHY", "BURNED", "MAINTENANCE")


def set_node_state(node_id: str, hostname: str, status: str) -> None:
    """Set NODE_STATE one-hot: status=1.0, others=0.0 for this node."""
    for candidate in _NODE_STATUSES:
        NODE_STATE.labels(
            node_id=node_id, hostname=hostname, status=candidate
        ).set(1.0 if candidate == status else 0.0)


__all__ = [
    "PROBE_DURATION_SECONDS",
    "PROBE_TOTAL",
    "NODE_STATE",
    "NODE_BURNED_TOTAL",
    "NODE_RECOVERED_TOTAL",
    "set_node_state",
]
