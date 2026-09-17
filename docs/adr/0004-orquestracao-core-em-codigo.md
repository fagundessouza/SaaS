# ADR-0004: Pipeline de domínio crítico em código versionado; n8n restrito a automações auxiliares

## Status
Aceito

## Contexto
A especificação lista n8n como ferramenta de automação/integração e desenha pipelines (ingestão →
matching → análise → notificação) que poderiam, na prática, ser implementados como workflows
visuais no n8n. Isso é arriscado para o núcleo do produto: dificulta testes automatizados de
regressão (exigidos pela seção 26 do prompt mestre), dificulta revisão de código em PR, e aumenta o
risco de bug de isolamento de tenant dentro de um workflow compartilhado (ver
[00-CRITICAL_ANALYSIS.md](../00-CRITICAL_ANALYSIS.md), seção 3).

## Decisão
O pipeline de domínio (ingestão, matching, análise, geração de dossiê, decisão de notificar) é
implementado como código Python versionado, orquestrado por fila de jobs assíncrona (Redis-backed:
Arq ou RQ). n8n é mantido no stack, mas restrito a automações **auxiliares e não-críticas**: glue de
onboarding, notificações internas ao time de suporte, sincronizações administrativas. n8n consome
eventos de domínio via webhook exposto pelo `core/events`, mas o domínio nunca depende de um
workflow n8n para funcionar corretamente.

## Alternativas consideradas
- **n8n como orquestrador do pipeline crítico**: rejeitado pelos motivos de testabilidade,
  revisão e risco de isolamento acima.
- **Motor de workflow dedicado (ex.: Temporal)** para o pipeline crítico: considerado mais robusto
  a longo prazo (retries, compensação, visibilidade de execução de longa duração), mas adiciona
  complexidade operacional não justificada no volume atual — fila de jobs simples é suficiente para
  o MVP. Revisar esta decisão (novo ADR) se a complexidade de orquestração (múltiplos passos com
  compensação, workflows de longa duração) crescer além do que uma fila simples suporta bem.

## Consequências
- Pipeline crítico é testável, revisável e auditável como qualquer outro código do domínio.
- n8n permanece útil para o time de operações/suporte sem virar dependência estrutural do produto.
