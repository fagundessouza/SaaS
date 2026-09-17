"""Ponto de entrada da API HTTP.

Rodar com: `uv run uvicorn api.main:app --reload`
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

import model_registry  # noqa: F401 — registra todo model em Base.metadata
from api.v1 import (
    auth,
    companies,
    health,
    jobs,
    knowledge,
    notifications,
    opportunities,
    tenants,
    tenders,
    users,
)
from core.observability.logging import configure_logging, get_logger
from core.observability.metrics import http_request_duration_seconds, http_requests_total
from core.storage.client import get_storage_client

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    configure_logging()
    get_storage_client().ensure_bucket()
    logger.info("api.startup")
    yield
    logger.info("api.shutdown")


app = FastAPI(title="Licitacoes Backend", lifespan=lifespan)


@app.middleware("http")
async def observability_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = str(uuid.uuid4())
    started_at = time.monotonic()

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)

    response = await call_next(request)

    duration = time.monotonic() - started_at
    route = request.scope.get("route")
    route_path = route.path if route is not None else request.url.path
    http_requests_total.labels(
        method=request.method, path=route_path, status_code=response.status_code
    ).inc()
    http_request_duration_seconds.labels(method=request.method, path=route_path).observe(duration)
    response.headers["X-Request-Id"] = request_id
    return response


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(tenants.router)
app.include_router(companies.router)
app.include_router(jobs.router)
app.include_router(knowledge.router)
app.include_router(tenders.router)
app.include_router(opportunities.router)
app.include_router(notifications.router)
