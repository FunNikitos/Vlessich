"""Tests for sub_urls builder."""
from __future__ import annotations

from app.services.sub_urls import SUPPORTED_CLIENTS, build_sub_urls


def test_build_sub_urls_all_clients() -> None:
    urls = build_sub_urls("token123", "https://sub.example.com")
    assert set(urls) == set(SUPPORTED_CLIENTS)
    for client in SUPPORTED_CLIENTS:
        assert urls[client] == f"https://sub.example.com/token123?client={client}"


def test_build_sub_urls_strips_trailing_slash() -> None:
    urls = build_sub_urls("t", "https://sub.example.com/")
    assert urls["v2ray"] == "https://sub.example.com/t?client=v2ray"


def test_supported_clients_contains_required() -> None:
    for c in ("v2ray", "clash", "singbox", "surge", "raw"):
        assert c in SUPPORTED_CLIENTS
