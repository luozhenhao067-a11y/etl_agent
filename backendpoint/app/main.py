"""FastAPI application factory for the API-layer-only delivery."""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import benchmarks, connections, design, executions, files, generation, health, pipelines, preparations
from app.config import Settings
from app.container import Container, build_container
from app.core.errors import install_exception_handlers
from app.core.utils import new_correlation_id

_CORRELATION_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

# Spec 8.10 Beat cadence for the Outbox dispatch pass (kernel mode only).
_DISPATCH_INTERVAL_SECONDS = 2.0

_logger = logging.getLogger("etl.dispatch")


def create_app(container: Container | None = None) -> FastAPI:
    resolved = container or build_container(Settings.from_env())
    settings = resolved.settings

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        """Spec 5.5 step 4 / 8.10: a periodic Outbox dispatch pass."""

        dispatcher = resolved.dispatcher
        task = None
        if dispatcher is not None:

            async def _dispatch_loop() -> None:
                while True:
                    try:
                        await dispatcher.dispatch_pending()
                    except Exception:  # noqa: BLE001 - the beat must survive
                        _logger.warning("outbox dispatch pass failed", exc_info=True)
                    await asyncio.sleep(_DISPATCH_INTERVAL_SECONDS)

            task = asyncio.create_task(_dispatch_loop())
        try:
            yield
        finally:
            if task is not None:
                task.cancel()

    app = FastAPI(
        title=settings.api_title,
        lifespan=lifespan,
        version=settings.api_version,
        description=(
            "ETL-Agent control-plane API generated from 接口契约.md v1.0. "
            "Harness, SecretProvider and execution-engine dependencies are "
            "fail-closed Port + Stub implementations."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.container = resolved

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next):
        raw = request.headers.get("X-Correlation-Id")
        if raw is None or raw.strip() == "":
            correlation_id = new_correlation_id()
        else:
            correlation_id = raw.strip()
            if not _CORRELATION_RE.fullmatch(correlation_id):
                generated = new_correlation_id()
                return JSONResponse(
                    status_code=400,
                    content={
                        "error_code": "API-400",
                        "message": "invalid X-Correlation-Id",
                        "correlation_id": generated,
                        "details": {"header": "X-Correlation-Id"},
                    },
                    headers={"X-Correlation-Id": generated},
                )
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Correlation-Id"] = correlation_id
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-Id", "Idempotency-Key"],
        expose_headers=["X-Correlation-Id"],
    )

    install_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(connections.router)
    app.include_router(files.router)
    app.include_router(pipelines.router)
    app.include_router(generation.router)
    app.include_router(design.router)
    app.include_router(preparations.router)
    app.include_router(executions.router)
    app.include_router(benchmarks.router)
    return app


app = create_app()
