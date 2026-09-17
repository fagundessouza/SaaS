# MicroSaaS de Inteligência em Licitações

Plataforma B2B de inteligência operacional para empresas que participam de licitações públicas no
Brasil. Status atual: **Fase 8 (Analysis Engine) concluída** — ver
[docs/phase-reports/](docs/phase-reports/) para os checkpoints completos (implementado, testado,
problemas encontrados e corrigidos, riscos, pendências) de cada fase.

Código do backend em [backend/](backend/README.md). A Fase 0 (Architecture Discovery) permanece
como referência normativa da arquitetura — nenhuma decisão de código contradiz o que está lá sem
um ADR novo (ver [regra de não-reset](docs/IMPLEMENTATION_ROADMAP.md)).

## Ordem de leitura recomendada

1. [docs/00-CRITICAL_ANALYSIS.md](docs/00-CRITICAL_ANALYSIS.md) — **comece por aqui.** Contradições,
   ambiguidades e riscos identificados na especificação original, e as decisões tomadas para
   resolvê-los. Inclui as quatro análises pedidas: visão consolidada, "o que pode quebrar",
   "o que é Fake AI", "o que falta para ser competitivo".
2. [docs/PRODUCT_VISION.md](docs/PRODUCT_VISION.md) — visão de produto consolidada e métricas de
   sucesso.
3. [docs/DOMAIN_MODEL.md](docs/DOMAIN_MODEL.md) — bounded contexts, entidades, agregados, ciclo de
   vida.
4. [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md) — estilo arquitetural, camadas, fluxo
   de dados ponta a ponta.
5. [docs/DATA_AND_KNOWLEDGE_ARCHITECTURE.md](docs/DATA_AND_KNOWLEDGE_ARCHITECTURE.md) — document
   intelligence, RAG, Global/Tenant Knowledge, cache, legal intelligence, performance budget.
6. [docs/EVENT_AND_NOTIFICATION_ARCHITECTURE.md](docs/EVENT_AND_NOTIFICATION_ARCHITECTURE.md) —
   catálogo de eventos, notification engine, idempotência.
7. [docs/UX_AND_ASSISTANT_SPEC.md](docs/UX_AND_ASSISTANT_SPEC.md) — navegação, progressive
   disclosure, assistente contextual, memória.
8. [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md) — isolamento de tenant (o requisito #1 do
   produto), auth, agentes, LGPD.
9. [docs/OBSERVABILITY.md](docs/OBSERVABILITY.md) — métricas, cost governance, explicabilidade.
10. [docs/IMPLEMENTATION_ROADMAP.md](docs/IMPLEMENTATION_ROADMAP.md) — fases, critérios de saída,
    corte de MVP.
11. [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — estrutura de repositório, convenções, ambiente,
    testes.
12. [docs/adr/](docs/adr/) — decisões arquiteturais registradas (11 ADRs cobrindo os pontos em
    aberto da especificação original e decisões tomadas durante a implementação).
13. [docs/phase-reports/](docs/phase-reports/) — checkpoint de cada fase concluída (seção 34 do
    prompt mestre): implementado, testado, problemas, riscos, decisões, pendências.

## Estado do projeto

- ✅ Fase 0 — Architecture Discovery (documentação acima).
- ✅ Fase 1 — Foundation/Core ([relatório](docs/phase-reports/FASE_1_REPORT.md)).
- ✅ Fase 2 — Auth + Multi-tenancy + Subscription ([relatório](docs/phase-reports/FASE_2_REPORT.md)).
- ✅ Fase 3 — Ingestion Engine — PNCP ([relatório](docs/phase-reports/FASE_3_REPORT.md), código em [backend/](backend/README.md)).
- ✅ Fase 4 — Document Intelligence ([relatório](docs/phase-reports/FASE_4_REPORT.md)).
- ✅ Fase 5 — Knowledge / RAG — Global Layer ([relatório](docs/phase-reports/FASE_5_REPORT.md)).
- ✅ Fase 6 — Procurement Domain ([relatório](docs/phase-reports/FASE_6_REPORT.md)).
- ✅ Fase 7 — Opportunity Engine ([relatório](docs/phase-reports/FASE_7_REPORT.md)).
- ✅ Fase 8 — Analysis Engine ([relatório](docs/phase-reports/FASE_8_REPORT.md)).
- ⏳ Fase 9 — Assistente (próxima).
