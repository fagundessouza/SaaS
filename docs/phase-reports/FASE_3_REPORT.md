# Relatório de Checkpoint — Fase 3 (Ingestion Engine — PNCP)

Ver critério de saída em [IMPLEMENTATION_ROADMAP.md](../IMPLEMENTATION_ROADMAP.md#fase-3--ingestion-engine-escopo-pncp-apenas):
"editais reais do PNCP aparecem como `Tender` versionado no banco, com métricas de volume vs.
linha de base."

## IMPLEMENTADO

- `ingestion/connectors/base.py`: interface `Connector` (Protocol) e as estruturas
  `RawTender`/`RawTenderDocument` — um conector só sabe buscar e normalizar, nunca toca banco.
- `ingestion/connectors/pncp.py`: `PncpConnector` contra a API pública do PNCP
  (`/v1/contratacoes/publicacao` para listagem paginada por modalidade,
  `/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/arquivos` para anexos), com retry com backoff
  exponencial em falhas 5xx/transporte (nunca em 4xx, que não é transiente).
- `domains/procurement/tenders/`: `Tender`/`TenderVersion`/`TenderDocument` (GLOBAL, sem RLS —
  edital publicado é informação pública, ver `DOMAIN_MODEL.md`). `service.py` decide, por
  `content_hash` do payload normalizado, se um `RawTender` é `Tender` novo, nova `TenderVersion`
  (retificação) ou descartado por já ingerido (`UNCHANGED`).
- `core/storage/client.py`: estendido com `put_global_object`/`get_global_object` (prefixo
  `global/`) — primeira necessidade real de storage não-tenant-scoped desde a Fase 1.
- `ingestion/pipeline/jobs.py`: `run_pncp_ingestion_job`, cron a cada 30min no worker, com janela
  de lookback de 48h (cobre gaps entre ciclos; idempotente por `content_hash`, então reprocessar
  é barato).
- Métricas novas: `ingestion_items_fetched_total`, `ingestion_errors_total`,
  `tenders_created_total`, `tenders_updated_total`, `tender_documents_stored_total`.
- Migration para `tenders`/`tender_versions`/`tender_documents`, sem RLS (confirmado via `psql`).

## TESTADO

- `ruff`, `mypy --strict`, `import-linter` — limpos (84 arquivos-fonte).
- Migration `upgrade`/`downgrade`/`upgrade` — reversível.
- `pytest -v` — **46/46 testes passando** (rodado duas vezes seguidas sem resetar o banco),
  incluindo:
  - `tests/unit/test_pncp_connector.py`: parsing contra o formato documentado, paginação
    através de modalidades, retry em 5xx seguido de sucesso, desistência sem propagar exceção
    após esgotar tentativas.
  - `tests/integration/test_tender_ingestion.py`: `Tender` novo → `CREATED`; mesmo payload de
    novo → `UNCHANGED` (nenhuma versão nova); payload alterado → `UPDATED` (nova
    `TenderVersion`, campos denormalizados atualizados); download/storage de documento com
    dedup (segunda chamada não rebaixa) e com falha registrada sem derrubar o processo.
  - `tests/integration/test_pncp_ingestion_job.py`: job completo com PNCP mockado via respx,
    contagens corretas, idempotência em reexecução.
- **Verificação ao vivo contra a API real do PNCP** (não mockada) — ver seção PROBLEMAS abaixo
  para o histórico completo de tentativas. Resultado final: listagem paginada confirmada
  funcionando com os nomes de campo exatamente como implementados (via `curl` direto, que
  motivou a correção do bug `sequencialCompra`/`numeroCompra` descrito abaixo); endpoint de
  detalhe de compra confirmado; endpoint de listagem de documentos **não confirmado**. Duas
  tentativas adicionais de rodar o pipeline completo (`PncpConnector` + `ingest_raw_tender`) via
  script contra a mesma janela de datas que respondera com sucesso minutos antes falharam por
  timeout/500 — a API voltou a ficar instável antes dessa segunda verificação ser possível. O
  conector se comportou corretamente nesse cenário (3 tentativas com backoff, depois desistência
  registrada em log e métrica, sem exceção não tratada) — evidência adicional, não planejada, de
  que o tratamento de instabilidade funciona na prática.

## PROBLEMAS (encontrados e corrigidos durante a fase)

1. **A API pública do PNCP esteve instável durante boa parte do desenvolvimento**: múltiplas
   tentativas em horários diferentes retornaram HTTP 500 ("Erro na comunicação com o banco de
   dados", erro do lado deles — `HikariPool-1 - Connection is not available`), timeout de
   conexão (>60s sem resposta), e um 422 de validação de data aparentemente incorreto para um
   range de 1 dia. Isso é uma demonstração ao vivo, dentro desta própria sessão de
   desenvolvimento, exatamente do risco #4 documentado em
   [00-CRITICAL_ANALYSIS.md](../00-CRITICAL_ANALYSIS.md) ("fontes governamentais instáveis") —
   não uma hipótese abstrata. Validou diretamente a decisão de retry com backoff e de nunca
   deixar uma falha de ingestão silenciosa (métricas `ingestion_errors_total` existem
   precisamente para isso).
2. **Quando a API voltou a responder, uma comparação campo a campo revelou um bug real**: o
   código assumia que `numeroCompra` (retornado pela API, ex.: `"PR08"`, um texto livre definido
   pelo órgão) seria o identificador numérico usado no path do endpoint de detalhe/documentos.
   O campo correto é `sequencialCompra` (inteiro, estável). Corrigido: `RawTender` agora carrega
   `ano_compra`/`sequencial_compra` como campos próprios (não mais lidos ad-hoc do
   `raw_payload`), e `fetch_documents` foi renomeado/corrigido para usar o campo certo. Sem a
   verificação ao vivo, esse bug só seria descoberto em produção, silenciosamente causando 404
   em toda tentativa de buscar documentos.
3. **Lógica de retry original tentava de novo em qualquer erro HTTP, inclusive 404** — um erro
   definitivo (não transiente) fazia o conector esperar até ~17s (soma do backoff) antes de
   desistir, por engano. Corrigido: `_request_raw_with_retry` agora só tenta de novo em 5xx ou
   erro de transporte; um 4xx é propagado imediatamente para o chamador decidir (ex.:
   `fetch_documents` trata 404 como "sem documentos", não como falha).

## RISCOS

- **O sub-recurso de listagem de documentos do PNCP não foi confirmado ao vivo.** Duas compras
  testadas retornaram 404 tanto para `/arquivos` quanto para `/documentos` — pode ser o nome de
  path errado, ou as duas compras genuinamente não tinham anexos (não dá para distinguir sem
  testar contra uma compra sabidamente com anexo). `fetch_documents` foi projetado para esse
  cenário de incerteza: nunca lança exceção para o chamador, apenas loga e retorna lista vazia —
  então o pior caso hoje é "nenhum documento é baixado", não uma falha visível. Isso significa
  que o critério de saída da fase ("Tender versionado no banco") está cumprido e verificado, mas
  a cobertura de anexos/documentos ainda não está confirmada em produção real.
- Ingestão cobre apenas 3 modalidades por padrão (Pregão Eletrônico, Concorrência Eletrônica,
  Dispensa) — decisão deliberada (ADR-0009: não cobrir especulativamente), mas significa que
  editais de outras modalidades (leilão, concurso, credenciamento, etc.) não aparecem ainda.
- O cron de ingestão roda a cada 30 minutos com lookback de 48h — nunca testado contra o volume
  real de produção (milhares de itens/dia a nível nacional, conforme
  [00-CRITICAL_ANALYSIS.md](../00-CRITICAL_ANALYSIS.md) já advertia). Cada modalidade e cada
  página é uma chamada HTTP sequencial — para o volume nacional completo isso pode ser lento;
  paralelização fica para quando houver evidência de que é o gargalo real (seção 30 do prompt
  mestre: não otimizar sem medir).

## DECISÕES

- Confirmada a estratégia de retry seletivo (5xx/transporte sim, 4xx não) como padrão para
  qualquer conector futuro de fonte externa instável.
- Confirmado `core/storage` com dois espaços de chave (`tenant/` e `global/`) — qualquer dado
  GLOBAL futuro (ex.: base jurídica da Fase 12) usa o mesmo padrão `put_global_object`.
- `ingestion` pode depender de `domains` (sem violar contrato de camadas) — mas a composição
  fica isolada em `ingestion/pipeline/jobs.py`, nunca dentro do conector (que permanece puro,
  sem conhecer modelos de banco).

## PENDÊNCIAS

1. **Confirmar o endpoint real de listagem de documentos do PNCP** contra uma compra sabidamente
   com anexos (não foi possível identificar uma no tempo desta fase). Até lá, `fetch_documents`
   é best-effort — documentado no docstring do módulo, não uma lacuna silenciosa.
2. Avaliar performance do ciclo de ingestão contra volume real de produção antes de expandir
   modalidades cobertas ou reduzir o intervalo do cron.
3. Nenhum endpoint de API foi exposto para consultar `Tender`/`TenderVersion` manualmente (ex.:
   `GET /v1/tenders`) — não fazia parte do critério de saída desta fase (isso é
   `domains/procurement` de cara ao usuário, Fase 6/7); os dados hoje só são visíveis via
   `psql` ou pelos testes.
4. **Reconciliar `TenderDocument` com o desenho original de `DOMAIN_MODEL.md`**: o modelo de
   domínio da Fase 0 previa `TenderDocument → Document → DocumentVersion` (o anexo apontando para
   a entidade genérica de conhecimento, que carrega `extraction_quality`/OCR — ver
   `DATA_AND_KNOWLEDGE_ARCHITECTURE.md`). Como `Document`/`DocumentVersion` são escopo da Fase 4
   (Document Intelligence, ainda não implementada), esta fase implementou `TenderDocument` como
   um registro autocontido de armazenamento bruto (`content_hash`, `storage_key`,
   `downloaded_at`), sem essa indireção. Isso é suficiente para o critério de saída desta fase
   (guardar o documento cru) mas precisa ser revisitado na Fase 4: ou `TenderDocument` passa a
   referenciar um `DocumentVersion`, ou ganha os campos de qualidade de extração diretamente —
   decisão a tomar com o desenho completo de Document Intelligence em mãos, não antes.

## PRÓXIMA FASE

Fase 4 — Document Intelligence: detecção de qualidade de extração + OCR/parsing dos documentos já
baixados por `TenderDocument` (quando o endpoint de documentos for confirmado — ver pendência 1),
com o campo `DocumentVersion.extraction_quality` bloqueando conclusões de alto risco a jusante
(ver [ADR-0006](../adr/0006-legal-grounding-e-revisao-humana.md) e
[DATA_AND_KNOWLEDGE_ARCHITECTURE.md](../DATA_AND_KNOWLEDGE_ARCHITECTURE.md)).
