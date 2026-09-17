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
from domains.notifications.consumer import consume_notification_events_job
from domains.procurement.companies.jobs import enrich_company_profile_job
from domains.procurement.opportunities.jobs import run_opportunity_matching_job
from ingestion.pipeline.jobs import run_pncp_ingestion_job


class WorkerSettings:
    functions = [
        enrich_company_profile_job,
        run_pncp_ingestion_job,
        run_opportunity_matching_job,
        consume_notification_events_job,
    ]
    cron_jobs = [
        cron(dispatch_outbox_job, second={0, 10, 20, 30, 40, 50}),
        # Defasado 5s do despacho do outbox, para o evento ja estar no stream quando o
        # consumidor rodar (Fase 10 — ver domains/notifications/consumer.py).
        cron(consume_notification_events_job, second={5, 15, 25, 35, 45, 55}),
        # A cada 30min: PNCP nao oferece webhook, so polling. Lookback de 48h em
        # ingestion/pipeline/jobs.py cobre gaps entre ciclos sem depender de precisao de minuto.
        cron(run_pncp_ingestion_job, minute={0, 30}),
        # Defasado 15min da ingestao, para casar sobre editais ja ingeridos no ciclo anterior.
        # Sem acoplamento direto entre os jobs de proposito (ver domains/procurement/
        # opportunities/jobs.py): um ciclo de ingestao que falha nao impede o matching de rodar.
        cron(run_opportunity_matching_job, minute={15, 45}),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
