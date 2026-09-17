"""Blocos genericos de worker Arq, sem nenhum conhecimento de dominio.

`core/` nao pode importar de `domains/` (ver contrato de camadas em pyproject.toml e
ADR-0001) — por isso o `WorkerSettings` completo (que combina isto com jobs de dominio, como
`domains.procurement.companies.jobs.enrich_company_profile_job`) vive em `backend/worker.py`,
fora de qualquer pacote em camadas, no mesmo papel de "composition root" que `api/main.py`
cumpre para o processo HTTP.
"""

from __future__ import annotations

from typing import Any

from core.events.dispatcher import dispatch_pending_events
from core.observability.logging import configure_logging, get_logger

logger = get_logger(__name__)


async def dispatch_outbox_job(ctx: dict[str, Any]) -> None:
    await dispatch_pending_events()


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    logger.info("worker.startup")


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("worker.shutdown")
