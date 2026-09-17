# Arquitetura de Sistema

## Estilo arquitetural: monólito modular, não microsserviços

**Por quê.** Microsserviços resolvem problemas de escala de time e de deploy independente que este
produto não tem ainda (é um time pequeno construindo um MVP). Um monólito modular com fronteiras de
domínio bem definidas (bounded contexts do [DOMAIN_MODEL.md](DOMAIN_MODEL.md)) dá 90% do benefício
de isolamento arquitetural — código não pode importar através de fronteiras de contexto — sem o
custo operacional de N serviços, N pipelines de deploy, e latência de rede entre o que hoje seria
uma chamada de função. Ver [ADR-0001](adr/0001-monorepo-modular-monolith.md).

Isso **não** significa um único processo monolítico em runtime. Significa um único *codebase*
modular com múltiplos *processos* especializados:

```
┌─────────────────────────────────────────────────────────────┐
│                        MONOREPO                              │
│                                                                │
│  backend/           (Python, um único pacote versionado)      │
│    core/            (tenancy, auth, billing, jobs, storage)   │
│    platform/        (ingestion, documents, RAG, llm, agents)  │
│    domains/          procurement/ (o domínio de negócio)      │
│    api/             (HTTP + WebSocket, importa de domains/*)  │
│                                                                │
│  frontend/          (Next.js, workspace separado)              │
│                                                                │
│  ops/               (infra as code, n8n flows auxiliares)     │
└─────────────────────────────────────────────────────────────┘
```

Runtime (múltiplos processos a partir do mesmo código):

```
                     ┌───────────────┐
                     │   API (HTTP/  │  ← síncrono, rápido, nunca chama LLM em linha
                     │   WebSocket)  │
                     └───────┬───────┘
                             │ publica jobs / lê estado
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
      ┌───────────┐  ┌───────────┐  ┌───────────────┐
      │ Ingestion │  │ Analysis  │  │ Notification  │
      │  Worker   │  │  Worker   │  │    Worker     │
      └───────────┘  └───────────┘  └───────────────┘
              │              │              │
              └──────────────┴──────────────┘
                             ▼
                 fila de jobs (Redis/RQ ou Arq)
```

> **Nota de implementação (Fase 1)**: no código, o pacote Python desta camada chama-se
> `ai_platform`, não `platform` — `platform` é um módulo da biblioteca padrão do Python, e um
> pacote local com esse nome pode sombreá-lo (qualquer dependência que faça `import platform`
> internamente resolveria para o pacote errado). O nome conceitual "platform" usado neste documento
> e a intenção arquitetural são os mesmos; só o nome do diretório em `backend/` muda.

## Camadas (revisão crítica da estrutura da seção 6)

A proposta original (`core/platform/domains/api`) é boa como intenção, mas a seção 6 mistura, sob
`platform/`, responsabilidades de infraestrutura genérica (`storage`, `cache`) com pipeline de
domínio de conhecimento (`ingestion`, `embeddings`, `retrieval`). Revisão:

```
backend/
├── core/                      # infraestrutura transversal, sem conhecimento de "licitação"
│   ├── auth/
│   ├── tenancy/                # tenant context, isolamento — usado por TODAS as camadas acima
│   ├── billing/
│   ├── permissions/
│   ├── audit/
│   ├── events/                 # event bus interno (publish/subscribe de domínio)
│   ├── jobs/                   # fila assíncrona, retries, idempotência
│   ├── storage/                # abstração sobre MinIO/S3
│   ├── cache/                  # abstração sobre Redis (multicamada, ver DATA_AND_KNOWLEDGE)
│   └── observability/          # logging, tracing, métricas, cost governance
│
├── platform/                   # capacidades de IA/conhecimento, agnósticas de domínio
│   ├── documents/               # document intelligence: detecção de qualidade, OCR, layout
│   ├── chunking/
│   ├── embeddings/              # EmbeddingProvider interface + implementações
│   ├── retrieval/                # Qdrant + filtros de tenant obrigatórios
│   ├── reranking/
│   ├── llm/                     # LLMProvider interface + implementações
│   ├── agents/                  # ferramentas explícitas, permissões, MCP como camada de tools
│   └── knowledge/                # Global vs Tenant Knowledge Layer (orquestra as acima)
│
├── domains/
│   └── procurement/             # ver DOMAIN_MODEL.md — único bounded context de negócio na v1
│       ├── companies/
│       ├── tenders/
│       ├── opportunities/
│       ├── analysis/
│       ├── pricing/
│       ├── competitors/
│       ├── legal/
│       └── notifications_policy/  # regras de QUANDO alertar (usa core/events + platform)
│
├── ingestion/                   # ficou de fora do platform/ de propósito
│   ├── connectors/               # PNCP first-class, outras fontes plugáveis (Connector interface)
│   └── pipeline/                 # fetch → validation → dedup → hash → versioning → raw storage
│
└── api/
    ├── v1/
    └── websocket/
```

**Justificativa da mudança**: `ingestion` sai de `platform/` porque não é uma capacidade de IA —
é aquisição de dados brutos. Fundi-la com `platform/documents` (que já cuida de qualidade/OCR)
confundiria "buscar o documento" com "entender o documento". `notifications_policy` fica dentro de
`domains/procurement` (decidir *quando* alertar é regra de negócio do domínio) enquanto o
*mecanismo* de entrega (`NotificationChannel`) fica em `core` ou em um módulo `platform/notifications`
compartilhável por outros domínios futuros.

## Fluxo de dados principal (ponta a ponta)

```
PNCP (e outras fontes)
   │
   ▼
[ingestion/connectors] → fetch, valida schema, calcula content_hash
   │
   ▼
[ingestion/pipeline] → dedup (hash já visto?) → versiona → grava raw em MinIO
   │
   ▼
[platform/documents] → detecta qualidade → extrai (nativo ou OCR/vision) → normaliza
   │
   ▼
[platform/chunking] → chunking estrutural (preserva seções do edital, ver DATA_AND_KNOWLEDGE)
   │
   ▼
[platform/embeddings] → embeddings em lote → grava em Qdrant (Global Knowledge, sem tenant_id)
   │
   ▼
[domains/procurement] → cria/atualiza Tender + TenderItem + Requirement (extração estruturada)
   │
   ▼
[core/events] → publica TenderCreated / TenderUpdated
   │
   ▼
[domains/procurement/opportunities] → para cada Tenant ativo:
   │     filtro DETERMINÍSTICO primeiro (CNAE, região, valor, palavra-chave do CompanyProfile)
   │     └── só se passar → matching semântico (embeddings) → OpportunityMatch
   ▼
Opportunity (DISCOVERED) criada para o tenant
   │
   ▼ (usuário abre, ou regra de "match forte" aciona automaticamente)
[domains/procurement/analysis] → Analysis sob demanda:
   │     retrieval (Global + Tenant Knowledge) → reranking → LLM com evidência → Finding[]
   ▼
[domains/procurement/pricing] → Deterministic Pricing Engine (regra) + Market Reference (dados)
   │
   ▼
Decision Dossier montado (10R)
   │
   ▼
[core/events] → AnalysisCompleted
   │
   ▼
[notifications] → Notification Engine → canal preferido do usuário
```

Ponto crítico de design: **o filtro determinístico roda para todo tenant ativo a cada novo
`Tender`, mas a análise LLM completa só roda sob demanda** (usuário abre a oportunidade, ou uma
regra explícita de "match muito forte" a aciona automaticamente). Isso é o que torna o custo de IA
proporcional ao uso real, não ao volume total de publicações do país (ver
[00-CRITICAL_ANALYSIS.md](00-CRITICAL_ANALYSIS.md), risco 5).

## Comunicação entre camadas

- **Dentro do monólito**: chamada de função direta entre módulos de domínio e `platform/`, nunca
  HTTP interno. `core/events` é um event bus *in-process* (com persistência em outbox table no
  Postgres) para desacoplar produtores/consumidores sem exigir uma fila externa para tudo.
- **Para processamento assíncrono pesado** (ingestão, OCR, embeddings em lote, geração de análise):
  fila de jobs (Redis-backed — Arq ou RQ; Celery é overkill para o volume inicial e adiciona
  complexidade operacional desproporcional ao estágio do produto).
- **Para automações auxiliares não-críticas** (seção 3 do documento crítico): n8n, consumindo
  eventos via webhook exposto pelo `core/events`, nunca produzindo eventos que o domínio depende
  para funcionar corretamente.

## Por que não microsserviços agora (trade-offs explícitos)

| Critério | Monólito modular | Microsserviços |
|---|---|---|
| Velocidade de iteração no estágio atual | Alta | Baixa (overhead de N deploys, N contratos de API) |
| Custo operacional (observabilidade, infra) | Baixo | Alto |
| Isolamento de falha entre domínios | Médio (mitigado por workers separados por tipo de carga) | Alto |
| Necessidade real hoje | Não há times múltiplos nem necessidade de deploy independente | — |
| Caminho de migração futuro | `platform/knowledge` e `ingestion` são os candidatos naturais a extrair primeiro, por serem reutilizáveis e terem perfil de carga muito diferente da API síncrona | — |

Migração para serviço separado só se justifica quando houver evidência concreta (não especulativa)
de que um módulo precisa escalar, ser deployado, ou ter SLA independente do resto — registrar como
ADR no momento em que isso acontecer, não antecipar agora.
