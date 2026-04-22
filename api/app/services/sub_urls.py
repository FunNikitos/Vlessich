"""Build public subscription URLs for VPN clients (Mini-App).

The sub-Worker is the single public edge endpoint that clients hit; the Mini-App
never proxies VPN payloads. The Worker converts ``/{token}?client=<name>`` into
the native subscription format expected by the target VPN app.
"""
from __future__ import annotations

from typing import Final

SUPPORTED_CLIENTS: Final[tuple[str, ...]] = (
    "v2ray",
    "clash",
    "singbox",
    "surge",
    "raw",
)


def build_sub_urls(sub_token: str, base_url: str) -> dict[str, str]:
    """Return ``{client_name: full_url}`` for every supported client."""
    base = base_url.rstrip("/")
    return {client: f"{base}/{sub_token}?client={client}" for client in SUPPORTED_CLIENTS}


__all__ = ["SUPPORTED_CLIENTS", "build_sub_urls"]
