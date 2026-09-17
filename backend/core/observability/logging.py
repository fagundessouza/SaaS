"""Logging estruturado (JSON) com tenant_id e request_id sempre presentes quando disponiveis.

Ver docs/OBSERVABILITY.md. Tracing distribuido completo (OpenTelemetry + backend de tracing) fica
fora do escopo minimo da Fase 1 — aqui entra o suficiente para correlacionar logs por
request_id/tenant_id, que ja responde boa parte de "por que ficou lento" em um monolito.
"""

from __future__ import annotations

import logging

import structlog

from core.config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(format="%(message)s", level=settings.log_level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(settings.log_level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
