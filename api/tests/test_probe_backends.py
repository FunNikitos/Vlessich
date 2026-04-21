"""Unit tests for Stage 7 probe backends.

* ``TcpProbeBackend`` — driven against an ephemeral asyncio TCP server
  running on ``127.0.0.1`` (real connect, no mocks). Failure path uses
  a closed port number.
* ``HttpProxyProbeBackend`` — driven via ``httpx.MockTransport`` so we
  exercise the response / error branches without real network or proxy.

No DB or settings dependency: these tests only need the backend
classes.
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault("API_ADMIN_JWT_SECRET", "j" * 32)

import httpx
import pytest

from app.workers.probe_backends import (
    HttpProxyProbeBackend,
    TcpProbeBackend,
)


@asynccontextmanager
async def _ephemeral_tcp_server() -> AsyncIterator[int]:
    """Start an asyncio TCP echo server on 127.0.0.1, yield its port."""

    async def handler(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            writer.close()
        except OSError:
            pass

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    sock = server.sockets[0]
    port = sock.getsockname()[1]
    try:
        yield port
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_tcp_backend_ok_against_real_listener() -> None:
    async with _ephemeral_tcp_server() as port:
        backend = TcpProbeBackend(timeout_sec=2.0)
        result = await backend.probe("127.0.0.1", port)
    assert result.ok is True
    assert result.latency_ms is not None
    assert result.latency_ms >= 0
    assert result.error is None


@pytest.mark.asyncio
async def test_tcp_backend_failure_on_closed_port() -> None:
    # Port 1 is reserved + nothing listens on it on test runners.
    backend = TcpProbeBackend(timeout_sec=1.0)
    result = await backend.probe("127.0.0.1", 1)
    assert result.ok is False
    assert result.latency_ms is None
    assert result.error is not None


@pytest.mark.asyncio
async def test_http_proxy_backend_treats_any_response_as_ok() -> None:
    # MockTransport returns 502 — RU backend must still flag this as
    # reachable because the box answered HTTP at all.
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(502, text="bad gateway")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = HttpProxyProbeBackend(
        proxy_url="http://unused:0", timeout_sec=2.0, client=client
    )
    try:
        result = await backend.probe("node.example.com", 443)
    finally:
        await backend.aclose()
    assert result.ok is True
    assert result.latency_ms is not None
    assert result.error is None


@pytest.mark.asyncio
async def test_http_proxy_backend_transport_error_is_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("blocked by DPI", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = HttpProxyProbeBackend(
        proxy_url="http://unused:0", timeout_sec=2.0, client=client
    )
    try:
        result = await backend.probe("node.example.com", 443)
    finally:
        await backend.aclose()
    assert result.ok is False
    assert result.latency_ms is None
    assert result.error is not None
    assert "blocked" in result.error.lower()
