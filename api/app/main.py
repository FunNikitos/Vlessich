"""FastAPI app factory."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from app.config import get_settings
from app.db import close_engine, close_redis, get_sessionmaker, init_engine, init_redis
from app.errors import ApiCode
from app.logging import log, setup_logging
from app.metrics import HTTP_REQUEST_DURATION_SECONDS
from app.routers import codes, health, internal, mtproto, payments, public, subscriptions, trials, users, webapp
from app.routers.admin import auth as admin_auth
from app.routers.admin import codes as admin_codes
from app.routers.admin import mtproto as admin_mtproto
from app.routers.admin import nodes as admin_nodes
from app.routers.admin import stats as admin_stats
from app.routers.admin import subscriptions as admin_subs
from app.routers.admin import views as admin_views
from app.startup.mtproto_seed import seed_shared_secret


class MetricsMiddleware(BaseHTTPMiddleware):
    """Records request duration into ``HTTP_REQUEST_DURATION_SECONDS``.

    Uses the matched route template (``request.scope["route"].path``) as
    a label to keep cardinality bounded. Unmatched requests (404 before
    routing) are labelled ``__unknown__``.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip the metrics endpoint itself to avoid feedback loops.
        if request.url.path == "/metrics":
            return await call_next(request)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            elapsed = time.perf_counter() - started
            HTTP_REQUEST_DURATION_SECONDS.labels(
                method=request.method.upper(),
                path_template=_route_template(request),
                status="500",
            ).observe(elapsed)
            raise
        elapsed = time.perf_counter() - started
        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=request.method.upper(),
            path_template=_route_template(request),
            status=str(status_code),
        ).observe(elapsed)
        return response


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return "__unknown__"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    init_engine(settings.database_url)
    init_redis(settings.redis_url)
    await seed_shared_secret(get_sessionmaker(), settings)
    log.info("api.start", env=settings.env)
    try:
        yield
    finally:
        await close_engine()
        await close_redis()
        log.info("api.stop")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Vlessich API",
        version="0.1.0",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["*"],
            allow_credentials=False,
        )

    app.add_middleware(MetricsMiddleware)

    app.include_router(health.router)
    app.include_router(public.router)
    app.include_router(subscriptions.router)
    app.include_router(internal.router)
    app.include_router(codes.router)
    app.include_router(trials.router)
    app.include_router(mtproto.router)
    app.include_router(payments.router)
    app.include_router(users.router)
    app.include_router(admin_auth.router)
    app.include_router(admin_codes.router)
    app.include_router(admin_views.users_router)
    app.include_router(admin_views.subs_router)
    app.include_router(admin_views.audit_router)
    app.include_router(admin_subs.router)
    app.include_router(admin_nodes.router)
    app.include_router(admin_mtproto.router)
    app.include_router(admin_stats.router)
    app.include_router(webapp.router)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:  # noqa: D401
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.exception_handler(HTTPException)
    async def _http_exc_handler(_: Request, exc: HTTPException) -> ORJSONResponse:
        """Flatten ``detail={"code","message"}`` to top-level for bot parsing."""
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail and "message" in detail:
            return ORJSONResponse(status_code=exc.status_code, content=detail)
        return ORJSONResponse(
            status_code=exc.status_code,
            content={"code": ApiCode.INTERNAL, "message": str(detail)},
        )

    return app


app = create_app()
