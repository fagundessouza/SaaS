# Relatório de Checkpoint — Fase 4 (Document Intelligence)

Ver critério de saída em [IMPLEMENTATION_ROADMAP.md](../IMPLEMENTATION_ROADMAP.md#fase-4--document-intelligence-escopo-mínimo):
"um edital real de baixa qualidade digital é processado e corretamente marcado como
`LOW_EXTRACTION_CONFIDENCE` quando aplicável (validado com casos reais, não sintéticos)."

## IMPLEMENTADO

- `ai_platform/documents/` — primeira capacidade real de `ai_platform` (antes um pacote vazio,
  reservado desde a Fase 0).
- `models.py`: `Document` (GLOBAL, identidade por `content_hash` único) e `DocumentVersion`
  (GLOBAL, derivada) com os campos exigidos por `DATA_AND_KNOWLEDGE_ARCHITECTURE.md`:
  `extraction_method`, `extraction_quality`, `ocr_required`, `ocr_confidence`, `layout_quality`,
  `table_quality`, `processing_version`, além de `low_extraction_confidence` (booleano de
  primeira classe, não decorativo) e `diagnostics` (JSONB com os números que sustentam a
  classificação — nunca uma qualidade sem explicação, ver seção 7 de
  [00-CRITICAL_ANALYSIS.md](../00-CRITICAL_ANALYSIS.md)).
- `quality.py`: detecção de suficiência da camada de texto nativa via `pypdf` — heurística
  documentada (média de caracteres por página), não um "parece bom" opaco.
- `ocr.py`: OCR real via Tesseract (idioma português), renderizando página a página com
  `pypdfium2`. Confiança calculada a partir da média de `conf` por palavra do próprio Tesseract
  (`image_to_data`), nunca inventada.
- `service.py` (`get_or_process_document`): decide nativo-vs-OCR, classifica qualidade (nunca
  `HIGH` para OCR — ver ADR-de-fato aplicado na seção "DECISÕES"), e aplica o Global Processing
  Cache por `content_hash` (ver [ADR-0012](../adr/0012-document-processing-cache.md), nova nesta
  fase, que resolve a pendência deixada pela Fase 3 sobre `TenderDocument → Document →
  DocumentVersion`).
- `domains/procurement/tenders`: `TenderDocument` ganhou `document_id` (FK nullable) e
  `processing_error`; `store_tender_documents` agora aciona o processamento automaticamente após
  cada download bem-sucedido.
- `core/storage/client.py`, `core/observability/metrics.py`: sem mudança estrutural nesta fase
  além das métricas novas (`document_processing_total`, `document_processing_cache_hits_total`,
  `document_processing_duration_seconds`).
- Migration para `documents`/`document_versions` + colunas novas em `tender_documents`, sem RLS
  (GLOBAL, confirmado via `psql`).
- CI: Tesseract (`tesseract-ocr`, `tesseract-ocr-por`) instalado via apt no workflow, para que os
  testes de OCR rodem de verdade lá, não só localmente.

## AMBIENTE (setup real, não hipotético)

Tesseract 5.4.0 não estava instalado nesta máquina — instalado via `winget` durante esta fase.
Os dados de idioma português (`por.traineddata`) não vêm com a instalação Windows e não puderam
ser copiados para `C:\Program Files\Tesseract-OCR\tessdata\` (permissão negada, diretório
protegido) — resolvido com um diretório `.tessdata/` local ao projeto (não versionado, cada
ambiente monta o seu, ver `backend/README.md`) e a variável `TESSDATA_PREFIX` (mais robusta que
passar `--tessdata-dir` como config string, que se mostrou frágil com paths do Windows).

## TESTADO

- `ruff`, `mypy --strict`, `import-linter` — limpos (94 arquivos-fonte).
- Migration `upgrade`/`downgrade`/`upgrade` — reversível; `documents`/`document_versions`
  confirmadas sem RLS via `psql`.
- **OCR real testado manualmente antes de escrever os testes automatizados**: gerei uma imagem
  com texto em português (Pillow), rodei o Tesseract via linha de comando — texto extraído
  corretamente. Depois testei o pipeline completo (`ocr_pdf`) contra um PDF só-imagem gerado com
  `fpdf2` — texto extraído com 89% de confiança média, exatamente o texto esperado.
- `pytest -v` — **55/55 testes passando** (suíte inteira do projeto, Fases 1-4), rodada duas
  vezes seguidas sem resetar o banco para confirmar idempotência. Docker Desktop precisou ser
  reiniciado no início desta sessão (ver PROBLEMAS item 4) antes de conseguir rodar contra
  Postgres/MinIO reais.
  - `tests/unit/test_document_quality.py`: PDF nativo → suficiente; PDF só-imagem (gerado via
    fpdf2 + Pillow) → insuficiente; PDF corrompido → `UnreadablePdfError`.
  - `tests/unit/test_ocr.py`: OCR real (sem mock) contra PDF só-imagem gerado nos testes —
    pulado automaticamente se o Tesseract não estiver configurado no ambiente.
  - `tests/integration/test_document_service.py`: caminho nativo (`HIGH`/`MEDIUM`), caminho OCR
    (nunca `HIGH`), PDF corrompido (`UNUSABLE` sem lançar exceção), reaproveitamento do Global
    Processing Cache (processar o mesmo conteúdo duas vezes gera uma única `DocumentVersion`).
  - `tests/integration/test_tender_ingestion.py`: estendido para confirmar que
    `TenderDocument.document_id` é preenchido após o download (usando um PDF de verdade em vez
    do placeholder de bytes arbitrários da Fase 3).

## PROBLEMAS (encontrados e corrigidos durante esta fase)

1. **`--tessdata-dir` como config string do pytesseract falhou em path do Windows**: o erro
   (`Error opening data file ".tessdata"/por.traineddata`) indicava que o path relativo entre
   aspas não estava sendo resolvido como esperado pelo subprocess do Tesseract. Corrigido usando
   a variável de ambiente `TESSDATA_PREFIX` (documentada pelo próprio Tesseract para este fim),
   resolvida para caminho absoluto via `pathlib` antes de setar — evita depender de quoting
   correto atravessando um subprocess.
2. **CI nunca teria funcionado**: ao adicionar o passo de instalação do Tesseract no workflow,
   notei que `JWT_SECRET_KEY` (obrigatório, sem default em `core/config.py`) nunca foi definido
   no `env:` do CI — qualquer execução falharia na validação do Pydantic Settings antes mesmo de
   chegar a um teste. Corrigido. Isso nunca foi pego antes porque o CI nunca rodou de fato (o
   repositório remoto está vazio até o momento desta fase).
3. **Testes de storage (Fase 3) só passavam localmente por acidente**: dependiam implicitamente
   de o bucket do MinIO já existir, o que só acontecia porque uma API rodada manualmente antes
   dos testes já tinha chamado `ensure_bucket()` no `lifespan` — os testes via `ASGITransport`
   nunca disparam esse lifespan. Corrigido com um fixture `session`-scoped e `autouse` em
   `tests/conftest.py` que garante o bucket antes de qualquer teste, independente de processo
   externo. Também corrigi o serviço MinIO do CI (comentário antigo dizia que não era possível
   rodar MinIO como `services:` do GitHub Actions por causa do `CMD` customizado exigido pela
   imagem oficial — resolvido usando `bitnami/minio`, que aceita configuração só por variável de
   ambiente).
4. **Docker Desktop não subiu na primeira tentativa** ao retomar o trabalho nesta sessão — o
   backend WSL2 (`docker-desktop` distro) ficou em estado `Stopped` mesmo com os processos da UI
   rodando. A causa raiz real (achada nos logs): um socket AF_UNIX órfão
   (`sailor-ingest.sock`) que nem `wsl --shutdown` nem matar todos os processos Docker
   conseguiam liberar — o handle era mantido pelo serviço `WslService` do Windows, cujo reinício
   exige privilégio de administrador (não disponível nesta sessão). Resolvido pedindo ao usuário
   para reiniciar o Docker Desktop manualmente (via UI, com prompt de UAC se necessário).
5. **Bug de isolamento de teste pego só ao rodar contra Postgres real** (não aparecia em nenhuma
   validação anterior porque o Docker esteve indisponível entre a escrita dos testes e esta
   verificação): `test_process_native_text_pdf_is_classified_correctly` e
   `test_process_same_content_twice_reuses_cache` compartilhavam a mesma constante de texto
   (`_LONG_TEXT`) — como as duas rodam na mesma sessão do pytest sem rollback entre testes (ver
   `tests/conftest.py`), o `content_hash` colidia e a segunda função de teste via
   `reused_cache=True` já na primeira chamada, quebrando sua própria premissa. Mesma classe de
   problema já resolvida para email/CNPJ nas Fases 2/3 (dados fixos + Postgres persistente entre
   execuções = colisão), só que desta vez para conteúdo de PDF — corrigido com um novo helper
   `unique_text()` em `tests/conftest.py`, seguindo o mesmo padrão de `unique_email`/`unique_cnpj`.

## RISCOS

- Sem detecção/correção de rotação de página nem análise real de layout/tabela
  (`table_quality` é sempre `NOT_APPLICABLE` nesta fase) — documentado como limitação
  deliberada do "escopo mínimo" (ver `IMPLEMENTATION_ROADMAP.md`), não uma lacuna escondida.
  Editais escaneados de cabeça para baixo ou tortos terão qualidade de OCR artificialmente baixa.
- `low_extraction_confidence` ainda não tem nenhum consumidor real (Analysis/Finding são Fase 8)
  — o campo existe e está correto, mas o "bloqueio de conclusão de alto risco" que ele deve
  acionar só pode ser testado de ponta a ponta quando esse consumidor existir.
- Heurísticas de classificação de qualidade (limiares de caracteres/página, confiança de OCR)
  foram calibradas por raciocínio de engenharia, não por um conjunto de documentos reais
  anotados manualmente (que `DATA_AND_KNOWLEDGE_ARCHITECTURE.md` recomenda para calibrar isso
  com rigor). Ajustar quando houver volume real de editais do PNCP passando pelo pipeline
  (Fase 3 já traz `TenderDocument`, mas o endpoint de anexos do PNCP ainda não foi confirmado ao
  vivo — ver pendência 1 do relatório da Fase 3).
- ~~CI atualizado mas nunca executado de fato~~ — **atualizado**: o primeiro push ao GitHub
  (via PR #1) rodou o CI de verdade e revelou mais um problema real, corrigido na hora:
  `bitnami/minio:latest` não existe mais (a Bitnami parou de publicar essa tag publicamente —
  `manifest unknown`). Corrigido subindo o MinIO via `docker run` direto (mesma imagem
  `quay.io/minio/minio` usada localmente) em vez do bloco `services:`. Após a correção, o CI
  passou de ponta a ponta: lint, mypy, import-linter, migrations e **55/55 testes** contra
  Postgres/Redis/MinIO reais no runner do GitHub Actions.

## DECISÕES

- Nova ADR: [ADR-0012](../adr/0012-document-processing-cache.md) — `Document.content_hash` é
  identidade imutável; `DocumentVersion.version_number` representa tentativa de processamento,
  não revisão de conteúdo. Resolve a pendência da Fase 3.
- OCR nunca é classificado `HIGH`, mesmo com confiança de reconhecimento muito alta — reforça o
  princípio de "nunca transformar OCR em falsa certeza" (seção 6 de
  [00-CRITICAL_ANALYSIS.md](../00-CRITICAL_ANALYSIS.md)).
- `TESSDATA_PREFIX` (variável de ambiente) é o mecanismo padrão para apontar o diretório de
  idiomas, não `--tessdata-dir` como argumento de config — mais robusto entre plataformas.

## PENDÊNCIAS

1. Calibrar os limiares de qualidade (nativo e OCR) contra um conjunto de editais reais do PNCP
   assim que o pipeline de anexos da Fase 3 estiver confirmado ao vivo.
2. Detecção/correção de rotação de página e análise de layout/tabela — candidatos a
   endurecimento do pipeline quando houver evidência de que documentos reais precisam disso
   (não antecipar sem essa evidência, ver seção 30 do prompt mestre).

## PRÓXIMA FASE

Fase 5 — Knowledge / RAG (Global Layer): chunking estrutural do `extracted_text` já disponível em
`DocumentVersion`, embeddings, indexação no Qdrant, retrieval básico com citação de
seção/página — ver [DATA_AND_KNOWLEDGE_ARCHITECTURE.md](../DATA_AND_KNOWLEDGE_ARCHITECTURE.md).
