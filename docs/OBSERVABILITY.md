# Observabilidade

## Princípio

O sistema precisa responder, sem investigação manual em código, três perguntas recorrentes:

1. "Por que ficou lento?"
2. "Por que essa oportunidade apareceu?" / "por que essa oportunidade não apareceu?"
3. "Quanto custou processar isto?"

As duas primeiras exigem tracing correlacionado ponta a ponta (um `trace_id` por requisição/job,
propagado por toda a cadeia ingestão → matching → análise → notificação). A terceira exige cost
governance como métrica de primeira classe, não um relatório manual de fatura de provedor.

## Métricas

| Categoria | Métricas | Uso |
|---|---|---|
| Latência de API | p50/p90/p95/p99 por endpoint | SLO de UI (ver performance budget em DATA_AND_KNOWLEDGE_ARCHITECTURE.md) |
| Ingestão | volume ingerido por fonte/período vs. linha de base esperada, taxa de erro de fetch, taxa de erro de parsing | Detectar fonte degradada/mudança de schema silenciosa (risco #4 da análise crítica) |
| Retrieval/reranking | latência, hit rate (resultado usado vs. descartado) | Calibrar quando reranking realmente muda o resultado (custo vs. benefício) |
| LLM | latência, tokens de entrada/saída, custo estimado por chamada, provider, modelo | Base de cost governance |
| Matching | taxa de match determinístico → semântico, falsos positivos/negativos reportados via feedback | Qualidade do Opportunity Engine |
| Jobs/filas | profundidade de fila, tempo de espera, taxa de retry/falha | Saúde do processamento assíncrono |
| Webhooks/notificações | taxa de entrega por canal, falhas, tempo até entrega | SLA de notificação (crítica não pode atrasar) |
| Custo | `cost_per_document`, `cost_per_analysis`, `cost_per_opportunity`, `cost_per_tenant`, `cost_per_feature` (seção 10T) | Unit economics por tenant e por feature |

## Cost governance — estrutura de dado, não relatório manual

Toda chamada a um provider de IA (LLM, embedding, reranking, OCR/vision externo) registra:

```
provider, model, tokens_in, tokens_out, estimated_cost,
tenant_id, feature (ex: "opportunity_matching" | "legal_analysis" | "pricing"),
latency_ms, cache_hit: bool
```

Isso permite responder diretamente "quanto custa analisar esta oportunidade" agregando os registros
por `opportunity_id`, e alimenta a decisão de gating de custo (seção 5 da análise crítica): se o
custo por análise estiver subindo sem correspondência em conversão/valor percebido, é sinal para
revisar o funil (mais filtro determinístico antes do LLM, mais cache).

## Explicabilidade como métrica, não só como feature de UX

- Todo `OpportunityMatch` grava os critérios que pesaram na decisão (determinísticos e semânticos)
  — isso é o que sustenta "por que apareceu".
- Para "por que não apareceu", o filtro determinístico registra, por tenant e por `Tender`
  descartado, o critério que reprovou (não é preciso rodar o matching semântico completo para
  responder isso — o filtro determinístico já sabe o motivo da reprovação por construção).

## Testes de regressão como parte da observabilidade

Não confundir observabilidade em produção com testes — mas ambos usam os mesmos artefatos: um
conjunto de casos reais (edital + resultado esperado de matching, análise, extração) versionado,
usado tanto em CI (regressão) quanto como baseline de comparação quando a qualidade em produção cai
(ex.: taxa de falso positivo subiu — comparar contra o conjunto de referência para isolar se é
mudança de modelo, de prompt, ou de dado de entrada).

## Alertas operacionais mínimos do MVP

- Volume de ingestão por fonte abaixo de X% da média móvel — indica fonte degradada.
- Taxa de erro de extração de documento acima de threshold — indica pipeline de OCR/parsing
  quebrado, não só documento individual ruim.
- Fila de jobs com profundidade crescente sem dreno — indica worker travado ou subdimensionado.
- Custo diário de IA acima de threshold configurado — corte de segurança antes de surpresa de
  fatura.
- Falha de entrega de notificação crítica (ex.: certidão vencendo) — canal de fallback deve ser
  acionado e a falha deve ser visível, não silenciosa.
