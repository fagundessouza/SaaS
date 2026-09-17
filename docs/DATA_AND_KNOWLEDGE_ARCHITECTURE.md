# Arquitetura de Dados e Conhecimento

## Document Intelligence — pipeline de qualidade variável

Assume-se, por padrão, que nenhum PDF público brasileiro tem camada textual confiável (seção 10A).

```
DocumentVersion (raw, em MinIO)
        │
        ▼
DETECTAR QUALIDADE
  - tem camada de texto? extraível? proporção texto/página plausível?
  - páginas rotacionadas/tortas? resolução?
        │
        ├── texto suficiente ──► EXTRAÇÃO ESTRUTURAL (parser nativo de PDF)
        │
        └── texto insuficiente
                │
                ▼
            OCR / VISION
                │
                ▼
            LAYOUT ANALYSIS (tabelas, colunas, cabeçalho/rodapé)
                │
                ▼
            STRUCTURE RECOVERY
        │
        ▼
NORMALIZAÇÃO (texto limpo + estrutura de seções)
        │
        ▼
DocumentVersion.extraction_quality registrado
```

### Seleção de ferramentas (critério, não escolha definitiva de fornecedor)

A escolha final de ferramenta de OCR/parsing é uma decisão de implementação (Fase 4), não de
arquitetura — mas o **critério de seleção** é definido agora, para não ser decidido por
familiaridade da equipe:

1. Qualidade em português brasileiro e em tabelas (editais têm tabelas de itens/preços densas).
2. Capacidade de self-hosting (custo variável de OCR em volume nacional não pode depender de custo
   por página de uma API externa sem teto).
3. Licenciamento compatível com uso comercial.
4. Fallback em cadeia: um parser estrutural rápido primeiro (barato), OCR/vision só quando o
   primeiro falha o gate de qualidade — nunca rodar o pipeline mais caro em todo documento por
   padrão.

A interface `DocumentExtractor` é definida na Fase 0 (contrato: input `DocumentVersion` raw, output
texto normalizado + `ExtractionQuality`); a implementação concreta é plugável e comparável via
avaliação com conjunto de documentos reais anotados manualmente (não confiar em benchmark genérico
de terceiros para decidir isso — a distribuição de qualidade de PDF de prefeitura pequena é
diferente de PDF de benchmark acadêmico).

### Document Quality Score — não decorativo

`DocumentVersion` carrega, como campos de primeira classe (não metadado solto):

```
extraction_method: native | ocr | vision | hybrid
extraction_quality: enum { HIGH, MEDIUM, LOW, UNUSABLE }
ocr_required: bool
ocr_confidence: float | null
layout_quality: enum { HIGH, MEDIUM, LOW }
table_quality: enum { HIGH, MEDIUM, LOW, NOT_APPLICABLE }
processing_version: string   # versão do pipeline que gerou esta extração
```

**Regra de bloqueio** (a parte que a especificação original menciona mas não amarra a
consequência): se `extraction_quality in {LOW, UNUSABLE}`, o documento é indexado normalmente para
buscas descritivas (ex.: "sobre o que é este edital"), mas **qualquer** `Finding` de
`Analysis`/`PriceAnalysis` derivado predominantemente desse documento é marcado
`LOW_EXTRACTION_CONFIDENCE=true` e a UI exibe isso de forma proeminente (não em tooltip) antes de
qualquer conclusão jurídica ou de preço, com opção de solicitar reprocessamento (fila de prioridade
para revisão manual/reprocessamento com outra estratégia de extração).

## Chunking estrutural

Chunking por contagem fixa de tokens é rejeitado como estratégia única — quebra cláusulas jurídicas
no meio, separando obrigação de condição. Estratégia adotada:

1. **Passo 1 — segmentação por estrutura conhecida do domínio**: o pipeline tenta identificar as
   seções típicas de um edital brasileiro (preâmbulo, objeto, condições de participação,
   habilitação, qualificação técnica, qualificação econômico-financeira, requisitos fiscais,
   julgamento, proposta, sanções, recursos, prazos, obrigações, execução, pagamento, garantias,
   anexos — seção 10C) via heurística de cabeçalhos + fallback semântico quando a heurística falha
   (edital mal formatado).
2. **Passo 2 — chunking dentro de cada seção**, respeitando um teto de tamanho por chunk (limite de
   contexto do embedding/reranker), mas nunca cruzando fronteira de seção sem necessidade.
3. Todo chunk carrega contexto estrutural como metadado, não só o texto:

```
chunk:
  document_id
  document_version
  section: "qualificacao_tecnica"
  subsection: nullable
  page_start / page_end
  heading_path: ["Edital", "8. Qualificação Técnica", "8.2. Atestados"]
  chunk_type: clause | table | list | preamble
  content: "..."
```

Isso é o que permite que uma `Evidence` (ver [DOMAIN_MODEL.md](DOMAIN_MODEL.md)) aponte não só para
"página 12" mas para "seção 8.2, Qualificação Técnica" — rastreabilidade útil de verdade, não só
tecnicamente correta.

## Global Knowledge Layer vs. Tenant Knowledge Layer

```
                KNOWLEDGE PLATFORM
                       │
             ┌─────────┴─────────┐
             │                   │
        GLOBAL LAYER         TENANT LAYER
   editais públicos,      documentos privados,
   leis, jurisprudência   custos, margens, atestados,
   (sem tenant_id)        preferências, feedback
   Qdrant collection      (tenant_id obrigatório em
   "global_knowledge"     payload E em toda query)
             │                   │
             └─────────┬─────────┘
                       ▼
                CONTEXT BUILDER
             (junta os dois por Opportunity)
                       ▼
                    ANALYSIS
```

### Isolamento no Qdrant (decisão técnica concreta, não deixada em aberto)

Duas opções eram possíveis: (a) uma collection por tenant, (b) uma collection compartilhada com
`tenant_id` como campo de payload indexado e filtro obrigatório em toda query. **Decisão: opção
(b)** para o Tenant Layer, com o filtro de tenant aplicado na camada de repositório (nunca deixado a
critério do código de chamada) — uma collection por tenant não escala operacionalmente para
centenas/milhares de tenants (overhead de gestão de coleção, HNSW index por coleção pequena é
ineficiente). O Global Layer é uma collection própria, sem `tenant_id`, com controle de acesso de
leitura aberto a qualquer tenant autenticado.

Mitigação de risco de "filtro esquecido" (risco #1 da análise crítica): a função de retrieval do
Tenant Layer não aceita uma query sem `tenant_id` explícito — é um argumento obrigatório na
assinatura da função, não um filtro opcional aplicado depois. Teste de isolamento multi-tenant
(ver [SECURITY_MODEL.md](SECURITY_MODEL.md)) inclui caso automatizado que tenta recuperar
conhecimento de tenant A usando contexto de tenant B e espera resultado vazio.

## Global Processing Cache (deduplicação por conteúdo)

```
SOURCE → CONTENT HASH → DOCUMENT VERSION → GLOBAL PROCESSING (uma vez)
```

Se N tenants têm interesse no mesmo `Tender` (o mesmo edital, mesmo `content_hash` dos anexos), o
OCR, parsing, chunking e embedding rodam **uma única vez**, gravados no Global Layer. A `Analysis`
específica de cada tenant reaproveita esse processamento e só adiciona o que é específico do tenant
(cruzamento com `CompanyProfile`, preço interno, jurisprudência aplicável ao caso). Métrica de
acompanhamento: taxa de reaproveitamento do Global Layer (seção 10E) — se estiver baixa,
questionar se a segmentação de conteúdo está fragmentando hashes que deveriam ser iguais (ex.:
metadado de download variável sendo incluído no hash por engano).

## Cache multicamada

| Camada | Tecnologia | Conteúdo | TTL / invalidação |
|---|---|---|---|
| L1 | Cache de aplicação (memória do processo) | Configuração, catálogo de planos, `LegalSource` mais acessadas | TTL curto (minutos); invalidado por evento `ConfigChanged` |
| L2 | Redis | Sessão, rate limiting, resultado de matching determinístico recente | TTL curto; chave sempre prefixada por `tenant_id` quando aplicável |
| L3 | Global processed documents (Postgres + MinIO) | Texto extraído, chunks, resultado de OCR | Sem TTL — invalidado só por nova `DocumentVersion` (versionamento, não expiração) |
| L4 | Qdrant | Embeddings (Global e Tenant) | Sem TTL — invalidado por reprocessamento de versão |
| L5 | Tenant-specific analysis cache (Postgres) | `Analysis`/`PriceAnalysis` já geradas | Invalidado quando `Tender` recebe nova versão (retificação) ou `CompanyProfile` muda materialmente |

Toda entrada de cache abaixo de L1 documenta, no código, chave, TTL, evento de invalidação e escopo
de tenant — cache sem estratégia de invalidação explícita não é aceito em revisão de código (risco
concreto: análise obsoleta servida como atual após retificação de edital).

## Legal Intelligence Layer — versionamento e retrieval

Ver também [ADR-0006](adr/0006-legal-grounding-e-revisao-humana.md).

```
NORMA/ACÓRDÃO NOVO
        │
        ▼
   INGESTÃO (mesmo pipeline de Document Intelligence)
        │
        ▼
   VERSIONAMENTO (LegalSource nunca é sobrescrita)
        │
        ▼
   DIFF contra versão anterior
        │
        ▼
   IMPACT ANALYSIS: quais Requirement/Analysis/regras internas referenciam esta fonte?
        │
        ▼
   Identificar Tenants com Opportunity ativa afetada
        │
        ▼
   Alerta (LegalSourceUpdated / NormativeChanged)
```

Toda regra jurídica aplicada por [`domains/procurement/pricing`] (Legal Exequibility Engine, seção
10M/10N) referencia um `LegalSource` versionado explicitamente — nunca uma constante de código
("75% do valor estimado") sem contexto de `jurisdiction`, `contract_type`, `object_type`,
`procurement_modality`, `effective_date`. Regras têm data de vigência e são consultadas por data de
referência (a data do edital, não a data de hoje), para permitir reprocessar análises antigas com a
regra que valia na época.

## Performance budget (síncrono vs. assíncrono)

| Operação | Classe | Budget alvo |
|---|---|---|
| Abrir dashboard / radar | SYNC | < 500ms (dados pré-computados, nunca aciona LLM em linha) |
| Busca/filtro de oportunidades já processadas | SYNC | < 300ms |
| Pergunta simples ao assistente sobre contexto já carregado | SYNC (com stream) | primeiro token < 1.5s |
| Gerar/atualizar `Analysis` completa de uma oportunidade | ASYNC | notificação ao concluir, sem bloquear UI |
| Ingestão de novo edital (fetch → indexação) | ASYNC (background) | best-effort, monitorado por SLA de frescor (ex.: disponível em até X minutos da publicação) |
| Notificação de evento crítico (certidão vencendo, prazo próximo) | ASYNC, mas com fila de alta prioridade | não pode depender de sucesso de um job de baixa prioridade na mesma fila |
