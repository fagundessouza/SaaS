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

ingestion_items_fetched_total = Counter(
    "ingestion_items_fetched_total",
    "Total de itens (editais) buscados com sucesso de uma fonte de ingestao",
    ["source"],
)

ingestion_errors_total = Counter(
    "ingestion_errors_total",
    "Total de falhas de fetch/parse durante a ingestao — usado para detectar fonte degradada "
    "(ver docs/00-CRITICAL_ANALYSIS.md, risco 4: falha silenciosa de ingestao)",
    ["source"],
)

tenders_created_total = Counter(
    "tenders_created_total",
    "Total de Tender novos criados a partir da ingestao",
    ["source"],
)

tenders_updated_total = Counter(
    "tenders_updated_total",
    "Total de TenderVersion novas criadas para Tender ja existentes (retificacao)",
    ["source"],
)

tender_documents_stored_total = Counter(
    "tender_documents_stored_total",
    "Total de documentos de edital baixados e armazenados",
    ["source", "status"],
)

document_processing_total = Counter(
    "document_processing_total",
    "Total de documentos processados pelo Document Intelligence, por metodo e qualidade "
    "resultante (ver ai_platform/documents/service.py)",
    ["method", "quality"],
)

document_processing_cache_hits_total = Counter(
    "document_processing_cache_hits_total",
    "Total de documentos reaproveitados do Global Processing Cache (ADR-0005) sem reprocessar",
)

document_processing_duration_seconds = Histogram(
    "document_processing_duration_seconds",
    "Duracao do processamento de um documento (extracao nativa ou OCR)",
    ["method"],
)

knowledge_chunks_indexed_total = Counter(
    "knowledge_chunks_indexed_total",
    "Total de chunks indexados no Global Knowledge Layer (Qdrant)",
)

knowledge_indexing_cache_hits_total = Counter(
    "knowledge_indexing_cache_hits_total",
    "Total de DocumentVersion cuja indexacao foi reaproveitada (ja indexada antes)",
)

knowledge_indexing_duration_seconds = Histogram(
    "knowledge_indexing_duration_seconds",
    "Duracao de chunking + embedding + upsert de uma DocumentVersion",
)

knowledge_search_duration_seconds = Histogram(
    "knowledge_search_duration_seconds",
    "Duracao de uma busca semantica no Global Knowledge Layer",
)

tender_items_stored_total = Counter(
    "tender_items_stored_total",
    "Total de TenderItem criados/atualizados a partir da ingestao (Fase 6)",
    ["source"],
)

requirements_extracted_total = Counter(
    "requirements_extracted_total",
    "Total de Requirement extraidos do texto de edital, por categoria classificada (Fase 6)",
    ["category"],
)

opportunities_created_total = Counter(
    "opportunities_created_total",
    "Total de Opportunity criadas pelo Opportunity Engine (Fase 7)",
)

opportunity_match_evaluations_total = Counter(
    "opportunity_match_evaluations_total",
    "Total de avaliacoes de match (Tender x tenant) por desfecho — a razao rejected/matched e o "
    "sinal de que o funil deterministico esta barrando volume antes do custo de IA (ver "
    "docs/00-CRITICAL_ANALYSIS.md, risco 5)",
    ["outcome"],
)
