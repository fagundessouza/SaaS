# Relatório de Checkpoint — Fase 5 (Knowledge / RAG — Global Layer)

Ver critério de saída em [IMPLEMENTATION_ROADMAP.md](../IMPLEMENTATION_ROADMAP.md#fase-5--knowledge--rag-global-layer):
"busca semântica funcional sobre editais já ingeridos, com citação de seção/página."

## IMPLEMENTADO

- `ai_platform/chunking/chunker.py`: chunking estrutural em duas etapas (segmentação por
  cabeçalho de seção conhecida de edital brasileiro + sub-chunking por parágrafo até um teto de
  caracteres, nunca cruzando fronteira de seção). Fallback documentado (não escondido): se
  nenhum cabeçalho é detectado, o documento inteiro vira uma única seção "preâmbulo" — a
  especificação original previa fallback semântico sofisticado, fora do "escopo mínimo" desta
  fase (ver seção `PROBLEMAS`/`DECISÕES`).
- `ai_platform/embeddings/`: `EmbeddingProvider` (Protocol, ADR-0003) + `FastEmbedProvider`
  (concreto, único por enquanto — self-hosted via `fastembed`/ONNX Runtime, sem PyTorch/GPU).
  Modelo default `paraphrase-multilingual-MiniLM-L12-v2` (384 dim, ~220MB) — escolha
  deliberada de leveza sobre qualidade máxima (ver DECISÕES).
- `ai_platform/retrieval/`: `client.py` (Qdrant singleton), `indexer.py`
  (`index_document_version` — chunking + embedding + upsert, idempotente por
  `document_version_id`, mesmo padrão de dedup do Global Processing Cache da Fase 4),
  `search.py` (`search_global_knowledge` — sem reranking, decisão já registrada na Fase 0).
- `domains/procurement/tenders/service.py`: `store_tender_documents` agora indexa
  automaticamente após o Document Intelligence processar com sucesso — mesmo padrão defensivo
  já usado para o processamento em si (falha de indexação nunca derruba a ingestão).
- `api/v1/knowledge.py`: `GET /v1/knowledge/search` — qualquer usuário autenticado (conteúdo
  GLOBAL, sem escopo de tenant).
- Qdrant adicionado a `ops/docker/docker-compose.yml` e ao CI (via `services:`, ao contrário do
  MinIO — a imagem oficial do Qdrant não exige `CMD` customizado).
- Métricas novas: `knowledge_chunks_indexed_total`, `knowledge_indexing_cache_hits_total`,
  `knowledge_indexing_duration_seconds`, `knowledge_search_duration_seconds`.
- **Correção retroativa na Fase 4**: `DocumentVersion` ganhou `page_texts` (JSONB, lista por
  página) via migration aditiva — a Fase 4 só guardava `extracted_text` já concatenado entre
  páginas, o que tornaria impossível citar `page_start`/`page_end` por chunk. Ver PROBLEMAS.

## AMBIENTE (setup real)

`fastembed` + `qdrant-client` instalados sem PyTorch (ONNX Runtime apenas) — download do modelo
de embeddings (~220MB, primeira execução) testado manualmente antes de escrever qualquer teste,
incluindo verificação de que a similaridade semântica realmente captura relações em português
(“material de escritório” mais próximo de “canetas e papel” do que de “limpeza predial” —
0.58 vs. 0.33 de similaridade de cosseno). Qdrant local via `docker compose` — sem problema de
inicialização desta vez (diferente da saga do Docker Desktop na Fase 4).

## TESTADO

- `ruff`, `mypy --strict`, `import-linter` — limpos (109 arquivos-fonte).
- Migration (`page_texts`) `upgrade`/`downgrade`/`upgrade` — reversível, com `server_default`
  para as linhas já existentes (Fase 4 já tinha `DocumentVersion` em uso).
- **Smoke test manual de ponta a ponta antes de escrever testes formais** (mesma disciplina das
  Fases 3/4): indexei um `DocumentVersion` sintético com seções "DO OBJETO" e "DAS SANÇÕES",
  busquei por "multa por descumprimento do contrato" — resultado correto (seção "DAS SANÇÕES",
  score 0.668) muito acima do irrelevante ("DO OBJETO", score 0.072), com página citada
  corretamente.
- `pytest -v` — **70/70 testes passando**, rodados **três vezes seguidas** sem resetar
  Postgres/Qdrant (disciplina reforçada depois de já ter sido pega de surpresa duas vezes nesta
  mesma sessão — ver PROBLEMAS).
  - `tests/unit/test_chunking.py`: segmentação correta com página certa; regressão específica
    para o bug de heurística descrito abaixo; fallback sem cabeçalhos; documento vazio;
    corte bruto de parágrafo gigante; índice sequencial de chunk.
  - `tests/unit/test_embeddings.py`: dimensão do vetor bate com a configurada; similaridade
    semântica real (texto relacionado pontua mais alto que não relacionado).
  - `tests/integration/test_retrieval.py`: indexação + busca com citação correta; idempotência
    (reindexar não duplica); `force=True` reindexã; `DocumentVersion` inexistente levanta erro
    claro; resultados sempre ordenados por relevância.
  - `tests/integration/test_knowledge_search_api.py`: endpoint exige autenticação; busca real
    via API retorna o chunk indexado com a citação certa.

## PROBLEMAS (encontrados e corrigidos durante esta fase)

1. **Bug real na heurística de detecção de cabeçalho, achado ao testar manualmente antes de
   escrever os testes formais**: a primeira versão tratava qualquer linha numerada (`1.2. Os
   itens deverão...`) ou qualquer linha contendo uma palavra do vocabulário de seções em
   qualquer lugar da frase (`a) prova de regularidade fiscal;`) como um cabeçalho novo — o que
   fragmentaria todo o documento em uma seção por frase, destruindo o propósito do chunking
   estrutural. Corrigido exigindo que a linha, além de bater com o vocabulário conhecido,
   *pareça um título* (maioria de caracteres maiúsculos após remover um eventual prefixo
   numerado) — "1. DO OBJETO" passa, "a) prova de regularidade fiscal;" não. Um teste de
   regressão específico (`test_chunk_document_does_not_treat_clause_text_as_a_new_heading`)
   cobre exatamente este caso.
2. **`DocumentVersion.extracted_text` (Fase 4) perdia a fronteira de página** — era só
   `"\n\n".join(text_by_page)`, sem preservar a lista original. Sem isso, chunking não teria
   como saber em que página um chunk cai, quebrando o critério de saída desta fase ("citação de
   seção/página"). Corrigido com `page_texts` (nova coluna, migration aditiva) e refatoração de
   `_extract()`/`get_or_process_document` para um dataclass `_ExtractionResult` em vez de uma
   tupla de 7 posições (que já estava no limite da legibilidade antes mesmo desta mudança).
3. **Poluição de teste entre execuções, desta vez no Qdrant** (terceira vez nesta sessão que
   esse padrão aparece — depois de e-mail/CNPJ na Fase 2/3 e texto de documento na Fase 4):
   `test_index_then_search_returns_relevant_chunk_with_citation` assumia que o resultado recém
   indexado seria o topo do ranking, mas o Qdrant de desenvolvimento acumula, entre execuções
   sucessivas do mesmo teste, vários chunks quase idênticos (mesmo texto base, só um marcador
   aleatório muda — irrelevante para a similaridade semântica) — o "primeiro" resultado nem
   sempre era o desta execução especificamente. Corrigido buscando o `document_version_id`
   esperado entre os resultados (com `limit` maior), não assumindo posição de ranking; o
   ranking em si é testado separadamente com uma asserção que não depende de identidade
   ("scores sempre em ordem decrescente"). Confirmado rodando a suíte três vezes seguidas.

## RISCOS

- Chunking so tem um nível de seção (sem sub-seções aninhadas, ex.: "8.2" dentro de "8" não vira
  um `heading_path` de dois níveis) e não distingue tabela/lista de texto corrido
  (`chunk_type` só tem `preamble`/`clause`) — limitação deliberada do "escopo mínimo", igual à
  Fase 4 não fazer detecção de rotação de página. Documentado, não escondido.
- Limiares de chunking (1200 caracteres por chunk) e o modelo de embedding (multilíngue leve,
  não o BGE-M3 mencionado no prompt mestre original — fastembed não o disponibiliza; ver
  DECISÕES) foram escolhidos por raciocínio de engenharia, não por avaliação formal de
  qualidade de retrieval contra um conjunto de editais reais anotados. Mesma ressalva já feita
  na Fase 4 para os limiares de qualidade de extração — calibrar quando houver volume real.
- A indexação roda inline dentro de `store_tender_documents` (mesmo processo/transação lógica do
  download+processamento) — para o volume de um piloto isso é aceitável, mas se o tempo de
  embedding começar a dominar a duração do ciclo de ingestão, vale considerar desacoplar em um
  job próprio (não antecipado agora, sem evidência de que é necessário).
- Apenas um provider de embedding implementado (self-hosted) — o segundo (API externa, previsto
  por ADR-0003) fica para quando houver necessidade real de comparar custo/qualidade.

## DECISÕES

- Modelo de embedding: `paraphrase-multilingual-MiniLM-L12-v2` em vez de BGE-M3 (mencionado no
  prompt mestre original) — BGE-M3 não está disponível no `fastembed` (que foi escolhido
  especificamente por evitar a dependência pesada do PyTorch); os multilingues disponíveis no
  fastembed são este (384 dim, leve) ou `multilingual-e5-large` (1024 dim, 2.24GB, mais lento
  sem GPU). Optado pelo mais leve para manter o ciclo de desenvolvimento/teste rápido — trocável
  via `EMBEDDING_MODEL_NAME` sem mudar código (ver `EmbeddingProvider`), decisão revisável
  quando houver avaliação real de qualidade de retrieval.
- Chunks vivem **só no Qdrant** (como payload dos pontos), não duplicados em nenhuma tabela
  Postgres — evita uma segunda fonte da verdade para o mesmo dado; toda consulta de chunk passa
  pelo Qdrant de qualquer forma (é onde a busca acontece).
- Sem reranking no retrieval básico (Radar) — decisão já tomada na Fase 0, apenas confirmada
  aqui na implementação real.
- Heurística de detecção de cabeçalho: vocabulário conhecido de seções de edital brasileiro E
  formato de título (maioria maiúscula) — nunca um dos dois sozinho (ver PROBLEMAS item 1).

## PENDÊNCIAS

1. Avaliar `multilingual-e5-large` (ou outro modelo) contra um conjunto de editais reais quando
   houver volume suficiente para medir qualidade de retrieval de verdade, não só plausibilidade
   por inspeção manual.
2. Sub-seções aninhadas e detecção de tabela/lista no chunking — candidatos a endurecimento
   quando houver evidência de que documentos reais precisam (mesmo princípio já aplicado à Fase 4).
3. Segundo provider de embedding (API externa) — só quando houver necessidade real de comparar
   custo/qualidade contra o self-hosted atual.

## PRÓXIMA FASE

Fase 6 — Procurement Domain: `TenderItem`/`Requirement` extraídos estruturalmente do texto já
processado e indexado (Fases 4/5), usando regra determinística onde o dado é verificável e IA
(retrieval + classificação) onde exige interpretação semântica — ver ADR-0007 e
[DOMAIN_MODEL.md](../DOMAIN_MODEL.md).
