"""FastAPI app factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from app.config import get_settings
from app.db import close_engine, close_redis, init_engine, init_redis
from app.errors import ApiCode
from app.logging import log, setup_logging
from app.routers import codes, health, internal, mtproto, public, subscriptions, trials, users, webapp
from app.routers.admin import auth as admin_auth
from app.routers.admin import codes as admin_codes
from app.routers.admin import nodes as admin_nodes
from app.routers.admin import stats as admin_stats
from app.routers.admin import subscriptions as admin_subs
from app.routers.admin import views as admin_views


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    init_engine(settings.database_url)
    init_redis(settings.redis_url)
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

    app.include_router(health.router)
    app.include_router(public.router)
    app.include_router(subscriptions.router)
    app.include_router(internal.router)
    app.include_router(codes.router)
    app.include_router(trials.router)
    app.include_router(mtproto.router)
    app.include_router(users.router)
    app.include_router(admin_auth.router)
    app.include_router(admin_codes.router)
    app.include_router(admin_views.users_router)
    app.include_router(admin_views.subs_router)
    app.include_router(admin_views.audit_router)
    app.include_router(admin_subs.router)
    app.include_router(admin_nodes.router)
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
