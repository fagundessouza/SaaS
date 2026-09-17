# Backend

Fase 1 (Foundation/Core) implementou o núcleo transversal descrito em
[docs/SYSTEM_ARCHITECTURE.md](../docs/SYSTEM_ARCHITECTURE.md): tenancy, outbox de eventos, fila
de jobs assíncrona, storage, cache e observabilidade básica.

Fase 2 (Auth + Multi-tenancy + Subscription) adicionou autenticação real (JWT + refresh token),
RBAC (owner/admin/member), billing mínimo (Plan/Subscription, sem gateway de pagamento) e o
primeiro pedaço de `domains/procurement`: `CompanyProfile` com enriquecimento automático por CNPJ
(BrasilAPI).

Fase 3 (Ingestion Engine — PNCP) adicionou `ingestion/` (conector do PNCP + pipeline de
fetch/dedup/versionamento) e `domains/procurement/tenders` (`Tender`/`TenderVersion`/
`TenderDocument`, GLOBAL, sem RLS). Um cron no worker busca editais novos a cada 30min.

Fase 4 (Document Intelligence) adicionou `ai_platform/documents` — a primeira capacidade real de
`ai_platform` (antes um pacote vazio): detecção de qualidade de extração nativa (pypdf), OCR real
via Tesseract quando a camada de texto é insuficiente, e o Global Processing Cache
(`Document`/`DocumentVersion` por `content_hash`, ver [ADR-0012](../docs/adr/0012-document-processing-cache.md)).
Todo `TenderDocument` baixado é processado automaticamente.

Fase 5 (Knowledge / RAG — Global Layer) adicionou `ai_platform/chunking`, `ai_platform/embeddings`
e `ai_platform/retrieval`: chunking estrutural do texto já extraído (Fase 4), embeddings locais
(fastembed, sem GPU) e indexação/busca semântica no Qdrant. Todo `DocumentVersion` processado com
sucesso é automaticamente indexado.

## Subindo o ambiente local

```bash
# 1. Infraestrutura (Postgres, Redis, MinIO, Qdrant)
cd ops/docker
docker compose up -d

# 2. Dependencias Python
cd ../../backend
uv sync
cp .env.example .env   # ajustar se necessario (troque JWT_SECRET_KEY em qualquer ambiente real)

# 3. Papel de banco sem privilegio de superusuario (OBRIGATORIO — ver ADR-0002).
#    O usuario de bootstrap do Postgres (POSTGRES_USER) e superuser e ignora RLS
#    incondicionalmente; sem este passo, o isolamento multi-tenant nao e de fato aplicado.
docker exec -i licitacoes-dev-postgres-1 psql -U licitacoes -d licitacoes \
  < ../ops/docker/initdb/01-app-role.sql

# 4. Migrations (inclui seed do plano "trial")
uv run alembic upgrade head

# 5. API
uv run uvicorn api.main:app --reload

# 6. Worker (em outro terminal) — nota: o modulo mudou de core.jobs.worker para worker (raiz),
#    ver "Por que backend/worker.py" abaixo.
uv run arq worker.WorkerSettings
```

### Tesseract (OCR, Fase 4)

Necessário para o caminho de OCR do Document Intelligence — sem ele, documentos sem camada de
texto nativa são marcados `UNUSABLE` em vez de processados (degrada de forma segura, não quebra).

```bash
# Windows (winget) — ajuste TESSERACT_CMD no .env para o caminho instalado
winget install --id UB-Mannheim.TesseractOCR -e

# Linux (Ubuntu/Debian)
sudo apt-get install -y tesseract-ocr tesseract-ocr-por

# macOS
brew install tesseract tesseract-lang
```

Os arquivos de idioma português (`por.traineddata`) geralmente não vêm com a instalação Windows
via winget — baixe manualmente e aponte `TESSDATA_DIR` no `.env` para a pasta:

```bash
mkdir -p .tessdata
curl -sL -o .tessdata/por.traineddata https://github.com/tesseract-ocr/tessdata_fast/raw/main/por.traineddata
# eng.traineddata e osd.traineddata tambem precisam estar em .tessdata/ — copie da instalacao
# do Tesseract (ex.: "C:\Program Files\Tesseract-OCR\tessdata\") se `--tessdata-dir` substituir
# o diretorio padrao inteiro.
```

Em Linux/CI, `tesseract-ocr-por` via apt já inclui o idioma no diretório padrão do sistema —
normalmente não é preciso setar `TESSDATA_DIR` nesse caso (deixe em branco).

> Nota: `ops/docker/initdb/` só é executado automaticamente pelo Postgres na primeira
> inicialização de um volume vazio. Se o container já existia antes deste arquivo ser criado,
> rode o passo 3 manualmente (como acima) — é idempotente, pode ser repetido sem risco.

## Fluxo de autenticação

```bash
# signup: cria Tenant + User (owner) + Subscription (trial) + CompanyProfile
curl -s -X POST localhost:8000/v1/auth/signup -H "Content-Type: application/json" -d '{
  "company_name": "Minha Empresa LTDA",
  "email": "dono@empresa.com",
  "password": "senha-forte-123",
  "cnpj": "19131243000197"
}'
# -> { access_token, refresh_token, tenant_id, user_id, company_profile_id }

# usar o access_token em qualquer rota protegida
curl -s localhost:8000/v1/users/me -H "Authorization: Bearer <ACCESS_TOKEN>"

# renovar (access token expira em 15min por padrao; refresh token roda e e revogado no uso)
curl -s -X POST localhost:8000/v1/auth/refresh -d '{"refresh_token": "<REFRESH_TOKEN>"}'

# logout (revoga o refresh token)
curl -s -X POST localhost:8000/v1/auth/logout -d '{"refresh_token": "<REFRESH_TOKEN>"}'
```

Se um `cnpj` for informado no signup (ou depois via `PUT /v1/company-profile/cnpj`), um job
assíncrono consulta a BrasilAPI e preenche `legal_name`/`trade_name`/`cnaes`/`regions`
automaticamente — acompanhe com `GET /v1/company-profile` (`enrichment_status`:
`pending` → `enriched`/`failed`).

## Verificando que o isolamento de tenant funciona

```bash
# dois tenants diferentes, cada um so enxerga o proprio CompanyProfile/usuarios
curl -s localhost:8000/v1/company-profile -H "Authorization: Bearer <ACCESS_TOKEN_TENANT_A>"
curl -s localhost:8000/v1/company-profile -H "Authorization: Bearer <ACCESS_TOKEN_TENANT_B>"
```

Automatizado em `tests/security/test_tenant_isolation.py` (Fase 1: `job_runs`) e
`tests/security/test_auth_isolation.py` (Fase 2: `users`, `company_profiles`, fim a fim via API).

## Ingestão do PNCP

O worker roda `run_pncp_ingestion_job` a cada 30min (cron), buscando editais das últimas 48h nas
modalidades Pregão Eletrônico, Concorrência Eletrônica e Dispensa. `Tender`/`TenderVersion` são
GLOBAL (sem tenant) — um edital publicado é informação pública. Dedup e versionamento são por
`content_hash` do payload normalizado (mesmo edital reingerido sem mudança = `UNCHANGED`, edital
retificado = nova `TenderVersion`). Ver [docs/phase-reports/FASE_3_REPORT.md](../docs/phase-reports/FASE_3_REPORT.md)
para o histórico de verificação contra a API real (que esteve instável durante o desenvolvimento
— a listagem foi confirmada campo a campo, o endpoint de documentos anexos ainda não).

## Document Intelligence

Todo `TenderDocument` baixado (ver seção acima) é processado automaticamente: se a camada de
texto nativa do PDF é suficiente (`pypdf`), extrai direto; senão, renderiza cada página
(`pypdfium2`) e roda OCR (Tesseract, português). O resultado vira uma `DocumentVersion` com
`extraction_quality` real — nunca hardcoded — e `low_extraction_confidence=true` quando a
qualidade é `LOW`/`UNUSABLE` (nenhum consumidor de análise existe ainda para respeitar essa
flag — isso é Fase 8 — mas o dado já nasce correto). Documentos com o mesmo `content_hash`
(mesmo PDF, tenders diferentes) são processados uma única vez (Global Processing Cache, ver
[ADR-0012](../docs/adr/0012-document-processing-cache.md)).

## Knowledge / RAG (busca semântica)

```bash
curl -s "localhost:8000/v1/knowledge/search?q=multa+por+descumprimento+do+contrato" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

Cada `DocumentVersion` processada com sucesso (Fase 4) é automaticamente segmentada em chunks
estruturais (uma seção de edital = um chunk, respeitando o vocabulário típico: objeto, condições
de participação, habilitação, sanções etc. — ver `ai_platform/chunking/chunker.py`), embutida
(modelo multilíngue local via `fastembed`, sem GPU) e indexada no Qdrant
(`global_knowledge`, GLOBAL — sem tenant, edital publicado é informação pública). A busca nunca
faz reranking (isso é Analysis, Fase 8 — ver ADR-0007) e sempre devolve a citação (seção,
página) junto com o trecho, nunca só o texto solto.

## Comandos de verificação (checkpoint de fase, ver docs/DEVELOPMENT.md)

```bash
uv run ruff check .        # lint
uv run mypy .               # type check
uv run lint-imports         # fronteiras de camada (api -> domains -> ai_platform -> core)
uv run pytest -v             # testes (precisa da infra do passo 1 no ar)
uv run alembic upgrade head  # migrations
```

## Por que `ai_platform` e não `platform`

`platform` é módulo da biblioteca padrão do Python — um pacote local com esse nome pode
sombrear o stdlib para qualquer dependência que faça `import platform` internamente. Ver nota em
[docs/SYSTEM_ARCHITECTURE.md](../docs/SYSTEM_ARCHITECTURE.md).

## Por que `backend/worker.py` e `backend/model_registry.py` ficam fora de `core/`

`core` não pode depender de `domains` (contrato de camadas em `pyproject.toml`,
`api -> domains -> ai_platform -> core`). O processo worker precisa combinar jobs genéricos
(`core/jobs`) com jobs de domínio (`domains/procurement/companies/jobs.py`), e o registro de
modelos para o Alembic precisa conhecer os modelos de todo bounded context — nenhuma das duas
coisas pode viver dentro de `core` sem violar o contrato. Por isso ambos são *composition roots*
no nível raiz do backend, no mesmo papel que `api/main.py` cumpre para o processo HTTP. Ver
[ADR-0001](../docs/adr/0001-monorepo-modular-monolith.md).

## O que existe e o que não existe ainda

Existe: `core/tenancy`, `core/events` (outbox), `core/jobs` (fila Arq), `core/storage` (MinIO),
`core/cache` (Redis), `core/observability` (logging + métricas), `core/auth` (JWT + refresh token
+ EmailIndex — ver [ADR-0011](../docs/adr/0011-auth-bootstrap-global-lookup.md)),
`core/permissions` (RBAC), `core/billing` (Plan/Subscription, sem gateway de pagamento),
`domains/procurement/companies` (CompanyProfile + enriquecimento por CNPJ),
`domains/procurement/tenders` (Tender/TenderVersion/TenderDocument), `ingestion/` (conector PNCP
+ pipeline), `ai_platform/documents` (Document/DocumentVersion, extração nativa + OCR) e
`ai_platform/chunking`/`embeddings`/`retrieval` (chunking estrutural, embeddings locais, busca
semântica no Qdrant). RLS aplicado e testado em toda tabela `TENANT` (`job_runs`, `users`,
`subscriptions`, `company_profiles`) — `tenders`/`tender_versions`/`tender_documents`/`documents`/
`document_versions` são GLOBAL, sem RLS; chunks vivem só no Qdrant (não duplicados em Postgres).

Não existe ainda: `Requirement`/`TenderItem` extraídos estruturalmente do texto processado,
`opportunities`/`analysis` (Fase 6/7/8 — nada ainda consome `low_extraction_confidence` para
bloquear conclusão de alto risco, porque não há conclusão nenhuma sendo gerada ainda), reranking
(deliberadamente fora do escopo do retrieval básico, ver ADR-0007 — só entra em Analysis, Fase 8),
`ai_platform/llm`/`agents` (Fase 9, Assistente), frontend, envio de e-mail de convite/verificação
(fica para o Notification Engine, Fase 10 — hoje o owner/admin já cria o usuário com senha
definida, sem fluxo de confirmação por e-mail).
