"""Metricas Prometheus minimas da Fase 1 — expandidas por camada nas fases seguintes
(ver docs/OBSERVABILITY.md para o catalogo completo alvo, incluindo cost governance).
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

http_requests_total = Counter(
    "http_requests_total",
    "Total de requisicoes HTTP",
    ["method", "path", "status_code"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "Latencia de requisicoes HTTP",
    ["method", "path"],
)

jobs_processed_total = Counter(
    "jobs_processed_total",
    "Total de jobs assincronos processados",
    ["job_type", "status"],
)

job_duration_seconds = Histogram(
    "job_duration_seconds",
    "Duracao de execucao de job assincrono",
    ["job_type"],
)

outbox_events_dispatched_total = Counter(
    "outbox_events_dispatched_total",
    "Total de eventos de dominio despachados do outbox para o event bus",
)
