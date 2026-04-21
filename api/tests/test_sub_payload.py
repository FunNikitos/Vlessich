"""Unit tests for ``app.services.sub_payload`` (Stage 2 T2)."""
from __future__ import annotations

import os

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault(
    "API_DATABASE_URL", "postgresql+asyncpg://vlessich:vlessich@localhost:5432/vlessich"
)

from dataclasses import asdict

from app.services.sub_payload import InboundNode


def test_inbound_node_serializable() -> None:
    node = InboundNode(
        protocol="vless-reality-vision",
        host="1.2.3.4",
        port=443,
        remarks="vlessich-fi-1-vision",
        sni="www.cloudflare.com",
        public_key="",
        short_id="deadbeef",
        flow="xtls-rprx-vision",
        uuid="00000000-0000-0000-0000-000000000000",
    )
    d = asdict(node)
    assert d["protocol"] == "vless-reality-vision"
    assert d["password"] is None
    assert d["alpn"] == []


def test_inbound_node_hysteria2_shape() -> None:
    node = InboundNode(
        protocol="hysteria2",
        host="1.2.3.4",
        port=443,
        remarks="vlessich-fi-1-h2",
        password="secret",
    )
    d = asdict(node)
    assert d["uuid"] is None
    assert d["password"] == "secret"
