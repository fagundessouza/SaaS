"""Composition root do processo worker — papel equivalente ao de api/main.py para o processo
HTTP. Fica fora de qualquer pacote em camadas de proposito: e o unico lugar autorizado a
combinar jobs genericos de `core/jobs` com jobs de dominio de `domains/*`, porque `core/` nao
pode depender de `domains/` (ver ADR-0001 e o contrato de camadas em pyproject.toml).

Rodar com: `uv run arq worker.WorkerSettings`
"""

from __future__ import annotations

from arq import cron
from arq.connections import RedisSettings

import model_registry  # noqa: F401 — garante que todo model esteja registrado no Base
from core.config import get_settings
from core.jobs.generic_jobs import dispatch_outbox_job, shutdown, startup
from domains.procurement.companies.jobs import enrich_company_profile_job


class WorkerSettings:
    functions = [enrich_company_profile_job]
    cron_jobs = [cron(dispatch_outbox_job, second={0, 10, 20, 30, 40, 50})]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
