# ADR-0012: Document/DocumentVersion — identidade por content_hash, versão como reprocessamento

## Status
Aceito

## Contexto
[DOMAIN_MODEL.md](../DOMAIN_MODEL.md) previa `TenderDocument → Document → DocumentVersion`, mas
a Fase 3 implementou `TenderDocument` como um registro autocontido (sem `Document`/
`DocumentVersion`, que são escopo de Document Intelligence, Fase 4) — pendência registrada em
[FASE_3_REPORT.md](../phase-reports/FASE_3_REPORT.md). Ao implementar a Fase 4, era preciso
decidir precisamente o que uma "versão" de `Document` significa, porque duas leituras razoáveis
competem:

1. Versão = uma revisão de conteúdo (como `TenderVersion`: conteúdo mudou, nova versão).
2. Versão = uma tentativa de processamento (o conteúdo é o mesmo, mas o pipeline que o processou
   mudou ou foi reexecutado).

## Decisão
`Document.content_hash` é a identidade do documento — **imutável por definição**: se os bytes
mudam, é logicamente um `Document` diferente (com seu próprio hash), nunca uma nova versão do
mesmo `Document`. Isso é o que sustenta o Global Processing Cache
([ADR-0005](0005-global-tenant-knowledge-dedup.md)): dois `TenderDocument` de tenants ou tenders
diferentes, mas com bytes idênticos, apontam para o **mesmo** `Document`.

`DocumentVersion.version_number` incrementa quando o **mesmo** `Document` é **reprocessado** —
isto é, quando `processing_version` (a versão do pipeline de extração) muda, ou quando um
reprocessamento manual é disparado (ex.: depois de `LOW_EXTRACTION_CONFIDENCE`, um operador
aciona nova tentativa). O conteúdo de entrada é sempre o mesmo; o que muda é o resultado da
extração.

Consequência prática: `get_or_process_document(content)` primeiro verifica se já existe uma
`DocumentVersion` para o `content_hash` com o `PROCESSING_VERSION` atual — se sim, reaproveita
sem reprocessar (cache hit); se não (documento novo, ou pipeline mudou desde o último
processamento), processa e grava uma nova versão.

## Alternativas consideradas
- **`Document` versionado por conteúdo** (como `Tender`/`TenderVersion`): rejeitada para este
  caso — um documento PDF de edital não sofre "retificação" da mesma forma que os metadados de
  um `Tender`; se o órgão publica um PDF diferente, isso já é capturado como um
  `TenderDocument.content_hash` diferente apontando para um `Document` diferente. Misturar as
  duas semânticas (conteúdo vs. processamento) no mesmo campo `version_number` geraria ambiguidade
  sobre "essa versão 2 tem bytes diferentes ou só foi reprocessada?".
- **Sem versionamento, um único registro de processamento por `Document`**: rejeitado — perderia
  o histórico de reprocessamento (útil para auditoria e para comparar se uma melhoria de pipeline
  realmente melhorou a qualidade de extração de documentos antigos).

## Consequências
- `TenderDocument.document_id` é nulo até o processamento completar, e aponta para o `Document`
  correspondente ao `content_hash` baixado — nunca para uma "versão" específica diretamente;
  quem quer o resultado do processamento consulta a `DocumentVersion` mais recente daquele
  `Document` (ou a mais recente com o `processing_version` desejado).
- Reprocessar documentos antigos após uma melhoria de pipeline é uma operação explícita e barata
  de rastrear: basta subir `PROCESSING_VERSION` e rodar novamente — o cache natural (baseado na
  combinação `content_hash` + `processing_version`) garante que só o que precisa ser
  reprocessado é reprocessado.
