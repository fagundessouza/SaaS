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

Fase 6 (Procurement Domain) adicionou `TenderItem` (itens/lotes do edital — o PNCP já entrega
estruturado, regra pura) e `Requirement` (requisito de habilitação extraído do texto já indexado
— regra sobre vocabulário de seção + classificação por embedding, sem LLM). Todo `TenderDocument`
processado gera automaticamente seus `Requirement`.

Fase 7 (Opportunity Engine) adicionou `domains/procurement/opportunities`: funil em duas etapas
(região + palavra-chave por regra determinística, similaridade semântica só quando a regra não
bate) que decide se um `Tender` vira uma `Opportunity` para um tenant, e por quê — `compatibility`
e `confidence` sempre decompostos, nunca um score único. Limiar semântico calibrado contra 100
editais reais do PNCP (ver [FASE_7_REPORT](../docs/phase-reports/FASE_7_REPORT.md)).

Fase 8 (Analysis Engine) adicionou `domains/procurement/companies` (`Certificate`/`Attestation`,
o que o tenant declara ter) e `domains/procurement/analysis` (`Analysis`/`Finding`/`Evidence`):
cruza cada `Requirement` do edital contra `Certificate` (regra — categoria + validade) ou
`Attestation` (embedding, só para categoria técnica) e gera um dossiê auditável, nunca automático
— só quando o usuário pede via `POST /v1/opportunities/{id}/analysis`.

Fase 10 (Event + Notification Engine) adicionou `core/notifications` (canais de e-mail/Web Push,
Alert/Notification/preferências) e `domains/notifications` (roteia evento → quem notificar,
consumindo o Redis Stream do outbox já existente desde a Fase 1). Canais "console" (sem
SMTP/VAPID configurados) são implementações reais, não stubs — mesmo raciocínio de
`core/billing` desde a Fase 2.

Fase 9 (Assistente), retomada depois de adiada: `ai_platform/llm` — provider de LLM **plugável**
(`LLMProvider` Protocol, ADR-0003), self-hosted (Ollama/vLLM/LM Studio, qualquer tamanho de
modelo) ou nuvem (Anthropic/OpenAI), trocável só por configuração. `domains/assistant` executa 3
ações determinísticas ("o que está faltando?", "entender edital", "explicar requisito") citando
evidência real do dossiê (Fase 8) — o LLM só sintetiza linguagem natural sobre fatos já corretos.

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

## Notification Engine

```bash
curl -s localhost:8000/v1/notifications -H "Authorization: Bearer <ACCESS_TOKEN>"
curl -s -X PUT localhost:8000/v1/notifications/preferences \
  -H "Authorization: Bearer <ACCESS_TOKEN>" -H "Content-Type: application/json" \
  -d '{"topic": "TenderUpdated", "channel": "email", "enabled": false}'
```

Uma retificação de edital (`TenderUpdated`) ou um novo match (`OpportunityMatched`, `Analysis`
completa) vira um evento no outbox (`core/events`, Fase 1) → despachado para um Redis Stream →
consumido pelo Notification Engine (`domains/notifications/consumer.py`, cron a cada 10s no
worker) → vira `Alert` + uma `Notification` por canal habilitado (e-mail, Web Push). Sem
`SMTP_HOST`/`VAPID_PRIVATE_KEY` configurados (padrão local), os canais "console" logam a
notificação em vez de enviar de verdade — implementação real, não um stub (mesmo raciocínio de
`core/billing` desde a Fase 2).

## Assistente

```bash
curl -s -X POST localhost:8000/v1/assistant/actions \
  -H "Authorization: Bearer <ACCESS_TOKEN>" -H "Content-Type: application/json" \
  -d '{"opportunity_id": "<OPPORTUNITY_ID>", "action": "missing_requirements"}'
```

Ações disponíveis: `missing_requirements` ("o que está faltando?"), `understand_tender`
("entender edital"), `explain_requirement` (exige `requirement_id` também). Cada uma monta o
contexto por query determinística (nunca aceita do cliente) e usa `ai_platform/llm` só para
sintetizar a resposta em linguagem natural — a citação (`evidence_refs`) vem sempre do banco, não
do texto do modelo. Sem `LLM_MODEL_NAME` configurado (padrão local), o endpoint responde `503`
de forma explícita, nunca finge uma resposta. Provider trocável por configuração
(`LLM_PROVIDER=anthropic` ou `openai_compatible` — este último cobre tanto a nuvem da OpenAI
quanto qualquer servidor self-hosted, ver `.env.example`).

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
`core/notifications` (Alert/Notification/preferências, canais e-mail + Web Push),
`domains/procurement/companies` (CompanyProfile + enriquecimento por CNPJ + Certificate/
Attestation), `domains/procurement/tenders` (Tender/TenderVersion/TenderDocument/TenderItem/
Requirement), `domains/procurement/opportunities` (Opportunity/OpportunityMatch, funil
determinístico + semântico), `domains/procurement/analysis` (Analysis/Finding/Evidence, dossiê
sob demanda), `domains/notifications` (roteia evento de domínio → quem notificar), `ingestion/`
(conector PNCP + pipeline), `ai_platform/documents` (Document/DocumentVersion, extração nativa +
OCR) e `ai_platform/chunking`/`embeddings`/`retrieval` (chunking estrutural, embeddings locais,
busca semântica no Qdrant). RLS aplicado e testado em toda tabela `TENANT` (`job_runs`, `users`,
`subscriptions`, `company_profiles`, `certificates`, `attestations`, `opportunities`,
`opportunity_matches`, `analyses`, `findings`, `evidences`, `alerts`, `notifications`,
`notification_preferences`, `push_subscriptions`, `assistant_sessions`, `assistant_messages`) —
`tenders`/`tender_versions`/`tender_documents`/`tender_items`/`requirements`/`documents`/
`document_versions` são GLOBAL, sem RLS; chunks vivem só no Qdrant (não duplicados em Postgres);
`domain_events` (outbox) também não tem RLS — é infraestrutura interna despachada por um worker
de confiança, não dado de tenant. `ai_platform/llm` (Fase 9) existe — provider plugável
(self-hosted ou nuvem, ver ADR-0003) — mas sem credencial real configurada em nenhum ambiente
ainda (ver PENDÊNCIAS da Fase 9).

Frontend (Fase 11) existe em `frontend/` — Next.js/React/TypeScript/Tailwind, JWT nunca trafega
para o navegador (Server Components + Route Handlers, cookie httpOnly), ver
[FASE_11_REPORT.md](../docs/phase-reports/FASE_11_REPORT.md).

Não existe ainda: `ai_platform/agents` (memória de longo prazo do assistente entre sessões —
depende de `TenantKnowledge`/`Feedback`/
`Decision`, Fase 14), análise jurídica avançada e Deterministic Pricing Engine (Fase 12 —
bloqueada por exigir base jurídica curada real e um caso de cliente piloto real, nenhum dos dois
disponível; `low_extraction_confidence` já é propagado até `Finding` desde a Fase 8, mas ainda
nenhum consumidor bloqueia uma conclusão de alto risco por causa dela, porque não há conclusão
jurídica/de preço sendo gerada ainda), Competitive Intelligence (Fase 13 — mesmo bloqueio de
dado real de cliente piloto), `CertificateValidationLog`/verificação automática de certidão
contra fonte externa (ver PENDÊNCIAS da Fase 8), reranking (deliberadamente fora do escopo do
retrieval básico, ver ADR-0007 — só entra em Analysis avançada, Fase 12), envio de e-mail de
convite/verificação de usuário (o Notification Engine da Fase 10 existe, mas ninguém ainda
dispara esse fluxo especificamente), `CertificateExpiring` sem produtor real (falta o job
agendado diário, ver PENDÊNCIAS da Fase 10), canais SMTP/Web Push/LLM reais sem credencial
configurada em nenhum ambiente ainda (só as implementações "console"/mockadas foram exercitadas).
