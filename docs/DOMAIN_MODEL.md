# Modelo de Domínio

## Bounded contexts

O prompt mestre propõe `core / platform / domains(procurement) / api`. Isso é uma separação de
camadas técnicas, não de bounded contexts de domínio. Para o modelo de domínio, os contextos reais
são:

| Bounded context | Responsabilidade | Aggregate roots |
|---|---|---|
| **Identity & Tenancy** | Quem é o tenant, quem são seus usuários, o que podem fazer | `Tenant`, `User`, `Role` |
| **Billing** | O que o tenant contratou e pode usar | `Subscription`, `Plan`, `Entitlement` |
| **Company Profile** | Quem é a empresa do tenant, para efeito de matching e habilitação | `CompanyProfile` |
| **Knowledge (Global)** | Conhecimento público processado uma vez, reutilizável entre tenants | `Document` (global), `LegalSource` |
| **Procurement** | O núcleo do domínio: editais, itens, requisitos, oportunidades | `Tender`, `Opportunity` |
| **Analysis** | Diagnósticos derivados de uma oportunidade para um tenant específico | `Analysis` |
| **Pricing** | Precificação e viabilidade econômica, por tenant | `PriceAnalysis` |
| **Assistant** | Interações conversacionais contextuais | `AssistantSession` |
| **Notification** | Entrega de alertas por canal | `Alert`, `Notification` |
| **Feedback & Learning** | Correção humana que ajusta o sistema | `Feedback`, `Decision` |

Cada bounded context tem seu próprio ciclo de vida e não deve compartilhar tabelas diretamente com
outro — comunicação entre contextos é via evento de domínio ou API interna, nunca leitura direta de
tabela de outro contexto (isso é o que permite `platform/knowledge` evoluir sem quebrar
`domains/procurement`, por exemplo).

## Regra geral de tenant scoping

Toda entidade abaixo é marcada como:

- **GLOBAL** — sem `tenant_id`, compartilhada entre todos os tenants (é conteúdo público).
- **TENANT** — `tenant_id` obrigatório, não-nulo, indexado, e parte de toda chave de partição/query.
- **DERIVADA** — não tem `tenant_id` próprio, mas herda o isolamento do agregado pai (ex.: um chunk
  de análise pertence à `Analysis`, que é `TENANT`).

## Entidades principais

### Identity & Tenancy

**`Tenant`** (GLOBAL por definição — é a raiz de isolamento, não tem tenant_id, tem `id`)
- Ciclo de vida: `trial → active → suspended → cancelled`.
- Dono de: todos os agregados `TENANT` abaixo, via `tenant_id`.

**`User`** (TENANT)
- Pertence a exatamente um `Tenant` (não há usuários multi-tenant nesta v1 — um humano com acesso a
  duas empresas cria dois usuários; simplifica isolamento e é aceitável para o perfil de cliente
  alvo).
- Tem um `Role` (RBAC simples: `owner`, `admin`, `member` — ver [SECURITY_MODEL.md](SECURITY_MODEL.md)).

**`Role` / `Permission`** (TENANT, mas o catálogo de permissões possíveis é GLOBAL/estático no
código, não uma tabela dinâmica — YAGNI: não construir um motor de permissões customizável antes de
haver demanda real).

### Billing

**`Plan`** (GLOBAL — catálogo de planos oferecidos pela plataforma)
**`Subscription`** (TENANT) — liga um `Tenant` a um `Plan` vigente, com datas de início/fim/renovação.
**`Entitlement`** (DERIVADA de `Subscription`) — limites materializados do plano (nº de usuários,
nº de oportunidades monitoradas simultaneamente, canais de notificação disponíveis, retenção de
histórico). Recalculado quando a `Subscription` muda, nunca editado diretamente.
**`Usage`** (TENANT) — contadores de consumo (análises geradas no período, documentos processados)
usados para enforcement de `Entitlement` e para `cost_per_tenant` (seção 10T).

### Company Profile

**`CompanyProfile`** (TENANT, um por tenant — é o "quem somos" que alimenta o matching)
- `cnpj`, `cnaes[]`, `regions[]`, `products[]`, `services[]`, capacidade operacional declarada.
- Relaciona-se com `Certificate[]` e `Attestation[]` (documentos que comprovam habilitação).

**`Certificate`** (TENANT) — certidão (fiscal, trabalhista, etc.). Tem `status` conforme seção 10K
(`VALID | EXPIRED | NOT_FOUND | SOURCE_UNAVAILABLE | PENDING_VALIDATION | AMBIGUOUS |
REQUIRES_MANUAL_REVIEW`) e histórico de verificações (`CertificateValidationLog`, cada linha com
timestamp, fonte consultada e resultado bruto — nunca sobrescreve, sempre acrescenta).

**`Attestation`** (TENANT) — atestado de capacidade técnica. Documento + metadados estruturados
(objeto atestado, órgão emissor, valor, período).

### Knowledge (Global) — ver detalhe em [DATA_AND_KNOWLEDGE_ARCHITECTURE.md](DATA_AND_KNOWLEDGE_ARCHITECTURE.md)

**`Document`** (GLOBAL quando a fonte é pública — ex.: edital publicado, lei; TENANT quando é
documento privado enviado pelo usuário — ex.: atestado, proposta própria). Um `Document` tem
`DocumentVersion[]` — nunca se edita uma versão, cria-se uma nova, ligada por `content_hash` e
`previous_version_id`.

**`DocumentVersion`**
- `extraction_method`, `extraction_quality`, `ocr_required`, `ocr_confidence`, `layout_quality`,
  `table_quality`, `processing_version` (seção 10B) — campos obrigatórios, não opcionais.
- Estado `LOW_EXTRACTION_CONFIDENCE` é um enum de status, não um campo booleano solto, porque afeta
  o que pode ou não ser feito a jusante (bloqueia geração de conclusão de alto risco — ver
  [00-CRITICAL_ANALYSIS.md](00-CRITICAL_ANALYSIS.md) item 2 da seção 6).

**`LegalSource`** (GLOBAL) — norma, acórdão, súmula, jurisprudência. Metadados completos conforme
seção 10G (`court_or_authority`, `document_type`, `process_number`, `decision_number`, `date`,
`theme`, `legal_basis`, `status`, `source_url`, `document_version`). Versionado como `Document`.
`LegalSource.status` inclui `SUPERSEDED` quando uma versão mais nova existe — nunca se apaga a
versão antiga (rastreabilidade histórica).

### Procurement — o núcleo

**`Tender`** (GLOBAL — um edital publicado é informação pública)
- `TenderItem[]` (itens/lotes do edital).
- `Requirement[]` (requisitos extraídos e classificados — habilitação, qualificação técnica,
  qualificação econômico-financeira, fiscal, etc. — ver seção 10C).
- `TenderDocument[]` (anexos: termo de referência, ETP, matriz de riscos, minuta contratual).
- Versionado (`TenderVersion`) porque editais sofrem retificação — uma retificação **não**
  sobrescreve a versão anterior (é o gatilho do evento `TenderUpdated`, ver
  [EVENT_AND_NOTIFICATION_ARCHITECTURE.md](EVENT_AND_NOTIFICATION_ARCHITECTURE.md)).

**`Opportunity`** (TENANT — é a lente de um `Tender` através dos olhos de um tenant específico)
- Relaciona um `Tenant` a um `Tender` com `OpportunityMatch` (o *porquê* do match: quais critérios
  bateram, com que evidência).
- **Não confundir `Tender` com `Opportunity`**: o mesmo edital gera N `Opportunity` diferentes, uma
  por tenant, cada uma com seu próprio ciclo de vida de workflow. Isso é o que faltava no desenho
  original do prompt (ver [00-CRITICAL_ANALYSIS.md](00-CRITICAL_ANALYSIS.md), seção 8, item 2) —
  proposta de ciclo de vida abaixo.

```
Opportunity.status:
  DISCOVERED → UNDER_REVIEW → QUALIFIED → PURSUING → SUBMITTED → WON | LOST | WITHDRAWN
```

- `Opportunity` também carrega `assigned_to: User | null` e `OpportunityComment[]` (colaboração em
  equipe — gap identificado na análise crítica).

**`OpportunityMatch`** (DERIVADA de `Opportunity`) — separa explicitamente, conforme seção 11:
  - `compatibility` (o que bateu: CNAE, objeto, região, valor, prazo).
  - `confidence` (confiança da técnica usada para cada critério — determinística = 1.0, semântica
    = score do modelo, nunca combinadas num único número sem decomposição).

### Analysis — diagnóstico, não é o mesmo agregado que Opportunity

**`Analysis`** (TENANT, um por `Opportunity` quando o usuário aprofunda — não gerado
automaticamente para toda oportunidade descoberta, ver [00-CRITICAL_ANALYSIS.md](00-CRITICAL_ANALYSIS.md)
item 5 da seção 6 sobre custo).
- `Finding[]` — cada achado com `category`, `severity`, `evidence[]`.
- `Evidence` — sempre aponta para `DocumentVersion + page + section + excerpt` (seção 12). Nunca
  existe `Finding` sem pelo menos uma `Evidence`, exceto achados puramente determinísticos (ex.:
  "certidão X vencida em 10 dias"), cuja evidência é o próprio dado estruturado, não um trecho de
  texto.
- `Recommendation` — ação sugerida, sempre com rótulo de força de linguagem (`possível`,
  `identificado`, `recomendado`) proporcional à evidência (seção 14).
- `RiskMatrix` (composta por `Risk[]`, estrutura da seção 10O) é parte de `Analysis`, não uma
  entidade solta.

### Pricing — separado de Analysis por ter regras próprias (determinístico)

**`PriceObservation`** (GLOBAL quando de fonte pública/mercado; TENANT quando é custo interno do
usuário).
**`PriceAnalysis`** (TENANT) — resultado do `Deterministic Pricing Engine` + `Legal Exequibility
Engine` (seções 10L/10M), com as três dimensões sempre separadas no schema, nunca fundidas num só
"preço sugerido":
  - `economic_floor` (do `CompanyProfile` do tenant: custos, impostos, margem mínima).
  - `legal_thresholds[]` (referências a `LegalSource` aplicável ao tipo de contratação).
  - `market_reference` (de `PriceObservation[]`, com metadado de comparabilidade — nunca média cega,
    seção 13).

### Competitors — presente no modelo, e agora também no fluxo (gap corrigido)

**`Competitor`** (TENANT — visão de um concorrente é subjetiva ao tenant que a registra, mesmo que
o CNPJ do concorrente seja público).
**`CompetitorDocument`** (TENANT) — documento de concorrente enviado/coletado, comparado contra
`Requirement` do edital para identificar `DocumentDivergence` (nunca "documento falso", ver seção
15) — `DocumentDivergence` é uma entidade de saída de `Analysis`, com evidência lado a lado.
**`CompetitorHistory`** (nova, endereça o gap 3 da seção 8 da análise crítica) — agregação de
resultados de licitações públicas por concorrente (quem venceu o quê, com que preço, quando esse
dado é público), alimentando inteligência competitiva histórica.

### Assistant

**`AssistantSession`** (TENANT) — amarrada a um `User` e opcionalmente a um contexto (`Opportunity`,
`Tender`, tela atual).
**`AssistantMessage`** (DERIVADA de `AssistantSession`).
Memória de longo prazo do assistente **não** é uma entidade de domínio própria — é uma
responsabilidade da camada `platform/agents` sobre as mesmas fontes (`TenantKnowledge`,
`Feedback`, `Decision`), nunca um "cérebro" paralelo desincronizado do resto do domínio (ver
[UX_AND_ASSISTANT_SPEC.md](UX_AND_ASSISTANT_SPEC.md)).

### Notification

**`Alert`** (TENANT) — regra/evento que gerou a necessidade de notificar (ex.: `CertificateExpiring`,
`OpportunityMatched`).
**`Notification`** (TENANT) — o envio concreto de um `Alert` por um `NotificationChannel`, com
status de entrega. Um `Alert` pode gerar N `Notification` (um por canal habilitado pelo usuário).
**`NotificationChannel`** (TENANT, configuração) — abstração de canal (seção 18/19).

### Feedback & Learning

**`Feedback`** (TENANT) — correção humana sobre uma saída do sistema (ex.: "esta oportunidade não é
relevante"). Sempre referencia o que está corrigindo (`target_type`, `target_id`).
**`Decision`** (TENANT) — decisão de negócio tomada (participar/não participar), correlacionada a
`Opportunity` para fechar o loop de aprendizado (seção 17) — mas **nunca** aplicada automaticamente
a regras jurídicas críticas (seção 17, restrição explícita); só alimenta matching, priorização,
recuperação, UX.
**`AuditLog`** (TENANT) — toda ação sensível (acesso a documento, mudança de permissão, decisão de
negócio) — ver [SECURITY_MODEL.md](SECURITY_MODEL.md).

## Diagrama de relações (alto nível)

```
Tenant 1─N User
Tenant 1─1 CompanyProfile 1─N Certificate
                          1─N Attestation

Tender (GLOBAL) 1─N TenderItem
                1─N Requirement
                1─N TenderDocument → Document → DocumentVersion

Tenant 1─N Opportunity N─1 Tender
Opportunity 1─1 OpportunityMatch
Opportunity 0─1 Analysis 1─N Finding 1─N Evidence → DocumentVersion
                          1─1 RiskMatrix 1─N Risk
Opportunity 0─1 PriceAnalysis

Tenant 1─N Competitor 1─N CompetitorDocument
                       1─1 CompetitorHistory

Tenant 1─N AssistantSession 1─N AssistantMessage
Tenant 1─N Alert 1─N Notification N─1 NotificationChannel
Tenant 1─N Feedback
Tenant 1─N Decision
Tenant 1─N AuditLog
```

## Decisões de ciclo de vida e versionamento (resumo)

- `Tender`, `Document`, `LegalSource`: **imutáveis por versão**. Alterações criam nova versão,
  nunca fazem `UPDATE` destrutivo.
- `Opportunity`, `Analysis`, `PriceAnalysis`: mutáveis dentro do próprio ciclo de vida do tenant,
  mas cada transição de status relevante gera evento de domínio (auditável via `AuditLog`).
- `Certificate`: estado mutável, mas todo resultado de verificação é append-only em
  `CertificateValidationLog` — o estado atual é uma projeção do log, não a fonte da verdade.
