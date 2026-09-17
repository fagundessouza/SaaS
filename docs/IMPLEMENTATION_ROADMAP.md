# Roadmap de Implementação

## Princípio de sequenciamento

O roadmap original de 16 fases (0–15) é mantido como **sequência de aprofundamento arquitetural**,
mas reordenado para produzir um MVP vendável muito antes da Fase 15. A ideia é um "walking
skeleton": todas as camadas existem desde cedo, rasas; aprofundam com uso real, nunca com
especulação. Ver [00-CRITICAL_ANALYSIS.md](00-CRITICAL_ANALYSIS.md), seção 1.

## Fases

### Fase 0 — Architecture Discovery (esta entrega)
Concluída com este conjunto de documentos. Aprovação do product owner é a condição de saída.

### Fase 1 — Foundation / Core
- Monorepo, convenções (ver [DEVELOPMENT.md](DEVELOPMENT.md)), CI básico (lint, testes, migration
  check).
- `core/tenancy`, `core/events` (outbox), `core/jobs` (fila), `core/storage`, `core/cache`,
  `core/observability` (esqueleto de tracing/métricas desde o início — retrofit depois é caro).
- **Critério de saída**: um serviço HTTP mínimo, multi-tenant de verdade (RLS ativo), com um job
  assíncrono de exemplo rodando fim a fim e visível em métricas.

### Fase 2 — Auth + Multi-tenancy + Subscription
- `User`, `Role`, `Tenant` completos. `Plan`/`Subscription`/`Entitlement` no schema (sem gateway de
  pagamento real — ver item 3 da tabela de ambiguidades em 00-CRITICAL_ANALYSIS.md).
- Onboarding com enriquecimento automático de `CompanyProfile` a partir de CNPJ (gap identificado
  na análise crítica, seção 8, item 4) — **promovido para esta fase** porque afeta ativação desde o
  primeiro uso, não é um "nice to have" tardio.
- **Critério de saída**: uma empresa consegue criar conta e ter `CompanyProfile` parcialmente
  preenchido automaticamente.

### Fase 3 — Ingestion Engine (escopo: PNCP apenas)
- `Connector` interface + implementação PNCP (fonte canônica, ver ADR-0009).
- Pipeline fetch → validação → dedup → hash → versionamento → raw storage.
- **Critério de saída**: editais reais do PNCP aparecem como `Tender` versionado no banco, com
  métricas de volume vs. linha de base.

### Fase 4 — Document Intelligence (escopo mínimo)
- Detecção de qualidade + extração estrutural nativa + um caminho de OCR (não a cadeia completa de
  fallback sofisticada ainda) + `DocumentVersion.extraction_quality` real, não hardcoded.
- **Critério de saída**: um edital real de baixa qualidade digital é processado e corretamente
  marcado como `LOW_EXTRACTION_CONFIDENCE` quando aplicável (validado com casos reais, não
  sintéticos).

### Fase 5 — Knowledge / RAG (Global Layer)
- Chunking estrutural, embeddings, Qdrant (Global collection), retrieval básico.
- **Critério de saída**: busca semântica funcional sobre editais já ingeridos, com citação de
  seção/página.

### Fase 6 — Procurement Domain
- `Tender`, `TenderItem`, `Requirement` extraídos estruturalmente (regra + IA onde exigir
  interpretação, seção 28).
- **Critério de saída**: um edital real tem seus requisitos de habilitação corretamente listados e
  auditáveis contra o texto original.

### Fase 7 — Opportunity Engine (filtro determinístico + matching semântico)
- Matching por `CompanyProfile` (CNAE, região, palavra-chave) primeiro; semântico como refinamento.
- **Marco de MVP interno**: a partir daqui já é possível demonstrar o produto a um design
  partner/cliente piloto — Radar funcional com dados reais, mesmo sem Analysis/Pricing completos.
- **Critério de saída**: taxa de falso positivo/negativo validada manualmente contra um conjunto de
  editais conhecidos de um cliente piloto real.

### Fase 8 — Analysis Engine (escopo mínimo: Findings + Evidence, sem Legal/Pricing ainda)
- Dossiê básico: requisitos, pendências documentais (cruzando `Certificate`/`Attestation` do
  tenant), sem ainda análise jurídica avançada nem preço.
- **Critério de saída**: dossiê de uma oportunidade real mostra pendências corretas e rastreáveis.

### Fase 9 — Assistente (escopo mínimo: contexto de tela + ações da Fase 7/8)
- Botão flutuante, contexto automático, 3–4 ações da lista da seção 16 (não todas de uma vez).
- **Critério de saída**: assistente responde "o que está faltando?" citando evidência real do
  dossiê da Fase 8.

### Fase 10 — Event + Notification Engine (escopo mínimo: email + web push)
- Catálogo de eventos completo desde o início (é barato definir, caro remendar depois), mas só 2
  canais implementados no MVP — WhatsApp entra quando houver validação de custo/demanda (BSP tem
  custo por conversa).
- **Critério de saída**: uma retificação de edital real dispara notificação correta ao tenant
  afetado.

### Fase 11 — Frontend (paralelo às fases 6–10, não sequencial após elas)
- Nota de processo: o frontend **não espera o backend estar 100% pronto** — cresce em paralelo
  contra contratos de API estabilizados desde a Fase 1. Tratar como sequencial (como a lista
  original sugere) atrasaria artificialmente a validação de UX.

### Fase 12 — Legal Intelligence + Pricing Engine (agora sim, aprofundamento)
- Base jurídica curada e versionada (não antes disso — sem isso, é risco de alucinação sem
  mitigação, ver ADR-0006). Deterministic Pricing Engine + Legal Exequibility Engine.
- **Critério de saída**: uma análise de preço real separa corretamente piso econômico, critério
  legal e referência de mercado para um caso real do cliente piloto.

### Fase 13 — Competitive Intelligence (gap da análise crítica, promovido no roadmap)
- `Competitor`, `CompetitorHistory`, comparação documental.
- **Critério de saída**: taxa de vitória histórica por concorrente/órgão visível para pelo menos um
  cliente piloto com dado real suficiente.

### Fase 14 — Feedback + Learning
- Loop de feedback afetando retrieval/matching/priorização (nunca regra jurídica automaticamente,
  ver seção 17).

### Fase 15 — Observability + Security hardening
- Auditoria completa, alertas operacionais, revisão de isolamento de tenant com pentest interno
  antes de qualquer expansão de base de clientes além do piloto.

### Fase 16 — Performance + Hardening / Production Readiness
- Fusão das fases 14–15 originais em uma única fase de hardening final antes de escalar aquisição
  de clientes além dos pilotos.

## O que fica fora do roadmap de 12 meses (explicitamente adiado, não esquecido)

- Cobertura de portais estaduais/municipais fora do PNCP (entra sob demanda real de cliente).
- Document Generation Engine (rascunho de proposta/declarações) — gap real identificado, mas depois
  do MVP core validado.
- Colaboração avançada em equipe (workflow de aprovação multi-usuário) além do RBAC básico.
- Integrações de saída para ERP/sistemas de gestão de contrato do cliente.

## Checkpoints de fase (aplicados a toda fase acima, sem exceção)

Ao final de cada fase, produzir o relatório padrão exigido pela seção 34 do prompt mestre:
`IMPLEMENTADO / TESTADO / PROBLEMAS / RISCOS / DECISÕES / PENDÊNCIAS / PRÓXIMA FASE`. Nenhuma fase é
declarada concluída só porque o código foi escrito — os 9 checks da seção 34 (implementação, testes,
lint, type checking, migration check, integration check, security check, acceptance criteria,
relatório) são condição de saída, não sugestão.
