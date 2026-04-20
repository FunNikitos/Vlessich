"""FastAPI app factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from app.config import get_settings
from app.db import close_engine, init_engine
from app.logging import log, setup_logging
from app.routers import codes, health, internal, mtproto, public, subscriptions, trials


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    init_engine(settings.database_url)
    log.info("api.start", env=settings.env)
    try:
        yield
    finally:
        await close_engine()
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

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:  # noqa: D401
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
