# Relatório de Checkpoint — Fase 6 (Procurement Domain)

Ver critério de saída em [IMPLEMENTATION_ROADMAP.md](../IMPLEMENTATION_ROADMAP.md#fase-6--procurement-domain):
"um edital real tem seus requisitos de habilitação corretamente listados e auditáveis contra o
texto original."

## IMPLEMENTADO

- `domains/procurement/tenders/models.py`: `TenderItem` (item/lote do edital, GLOBAL) e
  `Requirement` + `RequirementCategory` (requisito de habilitação classificado, GLOBAL).
- `ingestion/connectors/base.py` / `pncp.py`: `RawTenderItem` + `PncpConnector.fetch_items()` —
  o PNCP entrega item já estruturado (`numeroItem`, `descricao`, `materialOuServicoNome`,
  `quantidade`, `unidadeMedida`, `valorUnitarioEstimado`, `valorTotal`), então isto é regra
  determinística pura (ADR-0007), sem IA envolvida.
- `domains/procurement/tenders/items_service.py`: `store_tender_items` — upsert idempotente por
  `(tender_id, item_number)`, mesmo espírito de dedup já usado em outras partes do domínio.
- `domains/procurement/tenders/requirements_service.py`: `extract_requirements_for_document_version`
  — extração de `Requirement` em duas etapas (ADR-0007, "IA assistindo regra"):
  1. **REGRA**: dos chunks já indexados na Fase 5, candidatos são os do tipo `clause` cujo
     cabeçalho de seção bate com um vocabulário conhecido de habilitação (subconjunto do
     vocabulário do chunker — "DA HABILITAÇÃO", "QUALIFICAÇÃO TÉCNICA", "QUALIFICAÇÃO
     ECONÔMICO-FINANCEIRA", "REGULARIDADE FISCAL" — deliberadamente mais estreito que o
     vocabulário completo do chunker, que também cobre seções não relacionadas a requisito).
  2. **IA**: cada candidato é classificado em `RequirementCategory` por similaridade de cosseno
     contra um texto-protótipo por categoria, usando o `EmbeddingProvider` self-hosted já
     existente da Fase 5 (fastembed) — classificação zero-shot por embedding, não um LLM
     generativo novo (ver DECISÕES).
- `ai_platform/retrieval/search.py`: `get_document_chunks` — leitura de chunks já indexados por
  filtro (scroll do Qdrant, sem busca por similaridade), usada pela extração de requisitos para
  varrer todos os chunks de uma `DocumentVersion`.
- `domains/procurement/tenders/service.py`: `store_tender_documents` agora chama
  `extract_requirements_for_document_version` após a indexação (Fase 5) ter sucesso — mesmo
  padrão defensivo já usado para processamento/indexação (falha de extração nunca derruba a
  ingestão).
- `ingestion/pipeline/jobs.py`: `run_pncp_ingestion_job` agora também busca e armazena itens
  (`fetch_items` + `store_tender_items`) para todo Tender `CREATED`/`UPDATED`, mesmo padrão já
  usado para documentos.
- `api/v1/tenders.py`: `GET /v1/tenders/{id}/items` e `GET /v1/tenders/{id}/requirements` —
  qualquer usuário autenticado, sem escopo de tenant (conteúdo GLOBAL, mesmo raciocínio de
  `api/v1/knowledge.py`).
- Métricas novas: `tender_items_stored_total`, `requirements_extracted_total` (por categoria).

## AMBIENTE (setup real)

- Verificação ao vivo do sub-recurso de itens do PNCP (mesma disciplina da Fase 3): descoberto
  que `/itens` **não** vive sob a mesma base (`/api/consulta/v1`) usada pelo resto do conector —
  responde 404 lá. O path confirmado funcionando é
  `https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens` (base
  diferente), testado contra uma compra real (Município de Campo Grande/RN,
  `08084014000142/2024/57`, 5 itens retornados). Ver nota de verificação em
  `ingestion/connectors/pncp.py`.
- `uv` não estava instalado neste ambiente (só o `pyproject.toml`/`uv.lock`) — instalado via
  `pip install uv`, depois `uv sync --group dev` recriou o `.venv` exatamente como o lock
  especifica.
- Docker Desktop não estava rodando; subido manualmente antes de `docker compose up -d`.

## TESTADO

- `ruff`, `mypy --strict`, `import-linter` — limpos (116 arquivos-fonte).
- Migration (`tender_items`, `requirements`) `upgrade`/`downgrade`/`upgrade` — reversível.
- `pytest` — **86/86 testes passando** (70 herdados da Fase 5 + 16 novos), rodado **três vezes
  seguidas** sem resetar Postgres/Qdrant, sem flakiness.
  - `tests/unit/test_pncp_connector.py`: `_parse_item` mapeia campos documentados; oculta
    valores quando `orcamentoSigiloso=True` (sem esconder a quantidade, que não é sigilosa);
    exige `numeroItem`; `fetch_items` contra endpoint mockado no formato real; 404 tratado como
    "sem itens".
  - `tests/integration/test_tender_items.py`: cria itens novos; idempotente quando nada mudou
    (não reconta); atualiza em vez de duplicar quando um campo muda (retificação).
  - `tests/integration/test_requirement_extraction.py`: uma cláusula de habilitação fiscal
    sintética ("certidão negativa de débitos federais/estaduais/municipais, FGTS, CNDT") foi
    classificada corretamente como `FISCAL`, com seção/página corretas; seção "DO OBJETO" não
    vira candidata; idempotente; `force=True` reextrai sem duplicar; edital sem seção de
    habilitação retorna zero requisitos.
  - `tests/integration/test_tenders_api.py`: endpoints exigem autenticação; retornam itens
    armazenados; retornam lista vazia para tender sem itens.
  - `tests/integration/test_pncp_ingestion_job.py`: atualizado para mockar também `/itens` (novo
    sub-recurso chamado pelo job) — os dois testes existentes continuam passando.

## PROBLEMAS (encontrados e corrigidos durante esta fase)

1. **Conflito de porta com túnel SSH de outro projeto**: este computador já tinha um túnel SSH
   ativo (do projeto `triagem_ai`, não relacionado) ocupando as portas padrão do
   `docker-compose` deste projeto (5432, 6379, 6333, 9000/9001). Conexões contra `localhost`
   caíam no túnel em vez do Postgres/Qdrant/MinIO deste projeto, causando
   `InvalidPasswordError` enganoso. Corrigido com `ops/docker/docker-compose.override.yml`
   (não versionado — ver `.gitignore`) remapeando as portas de host só neste computador; o outro
   túnel SSH não foi tocado. `backend/.env` local ajustado para as portas remapeadas.
2. **Base URL inconsistente no PNCP entre sub-recursos da mesma compra**: `/arquivos` (Fase 3) e
   `/itens` (Fase 6) do mesmo `numeroControlePNCP` vivem sob bases diferentes
   (`/api/consulta/v1` vs. `/api/pncp/v1`) — não documentado no Manual de Integração, achado por
   tentativa direta contra a API real (ver AMBIENTE acima).
3. **Violação de FK ao escrever o teste de extração de requisitos**: a primeira versão do teste
   usava um `tender_id` aleatório (`uuid.uuid4()`) sem criar um `Tender` real, o que só falhou
   quando havia pelo menos um candidato a inserir (a constraint `requirements_tender_id_fkey`
   rejeitou o insert) — corrigido criando um `Tender` real em cada teste.

## RISCOS

- Classificação de categoria por similaridade de embedding contra 4 protótipos fixos (escrito à
  mão, não calibrado contra um conjunto real de editais anotados) — mesma ressalva já feita nas
  Fases 4/5 sobre limiares de engenharia vs. avaliação formal. `confidence` é o cosseno bruto da
  categoria vencedora, não uma probabilidade calibrada; não há limiar mínimo de confiança abaixo
  do qual um `Requirement` é descartado ou marcado para revisão humana — candidato a endurecer
  quando houver volume real (ex.: descartar/flagar classificações com cosseno muito baixo,
  indicando que nenhuma categoria realmente bateu).
- Detecção de candidato a requisito depende inteiramente do cabeçalho de seção do chunker da
  Fase 5 (mesmo nível único de seção, sem sub-seções aninhadas) — um edital que liste requisitos
  de habilitação fora de uma seção com um dos cabeçalhos conhecidos (ex.: dentro de um anexo, ou
  com título fora do vocabulário) não gera `Requirement` nenhum. Comportamento silencioso (zero
  requisitos), não um erro — mesmo princípio de "fallback documentado, não escondido" das fases
  anteriores.
- `TenderItem.material_or_service` guarda o nome já traduzido pelo PNCP (`"Material"`/
  `"Serviço"`), não o código bruto (`materialOuServico`) — decisão de simplicidade, revisável se
  outro consumidor precisar do código.
- O sub-recurso `/itens` tem a mesma incerteza documentada para `/arquivos` na Fase 3: um 404 é
  tratado como "sem itens", que é o comportamento seguro tanto se a compra realmente não tiver
  itens (incomum, mas não impossível) quanto se algum caso extremo de path/parâmetro estiver
  errado — não há como distinguir os dois casos sem mais amostras reais.

## DECISÕES

- **Classificação de categoria via embedding zero-shot, não um `LLMProvider` de completion
  novo**: ADR-0003 já previa um segundo provider (API externa) "quando houver necessidade real
  de comparar custo/qualidade" — mas a extração de requisitos desta fase é resolvida
  inteiramente pelo `EmbeddingProvider` self-hosted que já existe (Fase 5), sem exigir API key,
  custo por chamada ou latência de rede novos. Fica registrado aqui como decisão explícita do
  ADR-0007 ("IA assistindo regra"): a "IA" é embedding, não geração de texto. Um `LLMProvider`
  de completion real só entra quando uma feature futura exigir de fato (ex.: geração de
  texto explicativo — ver ADR-0007, linha "Geração de texto explicativo/resumo").
- `TenderItem` não é versionado por retificação como `TenderVersion` — uma retificação de item
  faz upsert por `(tender_id, item_number)` na mesma linha, porque o item em si (não o edital
  inteiro) é a unidade que faz sentido corrigir in-place; o histórico de retificação do edital
  como um todo já vive em `TenderVersion.raw_payload`.
- `Requirement` idempotente por `(document_version_id, chunk_index)`, não por hash de conteúdo —
  chunking é função pura de `page_texts`, então o mesmo chunk sempre cai no mesmo índice para a
  mesma versão, tornando o índice uma chave estável mais simples que hash.
- Override de porta do `docker-compose` local (problema 1 acima) feito via
  `docker-compose.override.yml` não versionado, não editando o `docker-compose.yml` principal —
  o conflito é específico deste computador (túnel SSH de outro projeto), não deve ser imposto ao
  outro ambiente de trabalho do Lucas.

## PENDÊNCIAS

1. Calibrar um limiar mínimo de confiança para `Requirement` (ver RISCOS) contra um conjunto
   real de editais anotados, quando houver volume suficiente — mesmo princípio já aplicado às
   calibrações pendentes das Fases 4/5.
2. Confirmar ao vivo se `/itens` realmente pode retornar 404 para "compra sem itens" vs. algum
   caso de path incorreto ainda não observado (mesma pendência já aberta para `/arquivos` na
   Fase 3).
3. `TenderDocument` do tipo anexo (termo de referência, ETP, matriz de riscos — ver
   `DOMAIN_MODEL.md`) ainda não é distinguido por tipo; a extração de requisitos hoje roda sobre
   qualquer documento indexado do Tender, não especificamente sobre o edital principal.

## PRÓXIMA FASE

Fase 7 — Opportunity Engine: matching por `CompanyProfile` (CNAE, região, palavra-chave)
primeiro (regra determinística), semântico como refinamento — ver ADR-0007 e
[IMPLEMENTATION_ROADMAP.md](../IMPLEMENTATION_ROADMAP.md#fase-7--opportunity-engine-filtro-determinístico--matching-semântico).
Marco de MVP interno: a partir desta próxima fase já é possível demonstrar o produto a um
cliente piloto real.
