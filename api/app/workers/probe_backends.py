"""Probe backend implementations (Stage 5 + Stage 7).

The prober consumes any object satisfying the ``ProbeBackend`` Protocol
defined in ``app.workers.prober``. Two implementations live here:

* ``TcpProbeBackend`` — control-plane TCP-connect (default, drives BURN).
* ``HttpProxyProbeBackend`` — issues a GET via residential RU proxy
  (``API_RU_PROXY_URL``). Any HTTP response (2xx..5xx) counts as
  reachable: in RU the failure mode is TCP RST / DNS poison, not
  application-level errors. Telemetry only — does not influence BURN
  state (see ``Prober._apply``).

Both backends are pure-asyncio and time themselves via ``time.monotonic``.
Errors are truncated to ``_MAX_ERROR_LEN`` characters to stay within the
``NodeHealthProbe.error`` Text column without ballooning audit volumes.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Final

import httpx

_MAX_ERROR_LEN: Final = 256


@dataclass(slots=True, frozen=True)
class ProbeResult:
    ok: bool
    latency_ms: int | None
    error: str | None


class TcpProbeBackend:
    """Pure TCP connect, no TLS, no payload."""

    def __init__(self, timeout_sec: float) -> None:
        self._timeout = timeout_sec

    async def probe(self, hostname: str, port: int) -> ProbeResult:
        started = time.monotonic()
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(hostname, port),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            return ProbeResult(ok=False, latency_ms=None, error="timeout")
        except OSError as exc:
            msg = str(exc) or exc.__class__.__name__
            return ProbeResult(
                ok=False, latency_ms=None, error=msg[:_MAX_ERROR_LEN]
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            # Best-effort close; we still recorded a successful connect.
            pass
        return ProbeResult(ok=True, latency_ms=latency_ms, error=None)


class HttpProxyProbeBackend:
    """GET via a residential proxy (Stage 7).

    Reachability semantics: any HTTP response (no transport error) =
    ``ok=True``. We do not interpret status codes — a 502 from the
    upstream still proves the node is reachable from inside RU.

    Implementation notes:
    - Single shared ``httpx.AsyncClient`` per backend instance, reused
      across probes (connection pooling, lower handshake cost).
    - Non-2xx responses do NOT raise — we use ``client.get`` and only
      treat ``httpx.HTTPError`` (network-level) as failure.
    - Scheme is ``http`` (not https): TLS adds noise; we want raw
      reachability. The probed port is still the node's TLS port (443
      by default) — most modern nodes return a TLS handshake error
      page or 400, which counts as reachable.
    """

    def __init__(
        self,
        proxy_url: str,
        timeout_sec: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            proxy=proxy_url,
            timeout=timeout_sec,
            verify=False,
            # Limit retries — we want a single attempt per tick.
            transport=httpx.AsyncHTTPTransport(retries=0, verify=False),
        )

    async def probe(self, hostname: str, port: int) -> ProbeResult:
        url = f"http://{hostname}:{port}/"
        started = time.monotonic()
        try:
            await self._client.get(url)
        except httpx.HTTPError as exc:
            msg = str(exc) or exc.__class__.__name__
            return ProbeResult(
                ok=False, latency_ms=None, error=msg[:_MAX_ERROR_LEN]
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        return ProbeResult(ok=True, latency_ms=latency_ms, error=None)

    async def aclose(self) -> None:
        await self._client.aclose()


__all__ = [
    "ProbeResult",
    "TcpProbeBackend",
    "HttpProxyProbeBackend",
]
