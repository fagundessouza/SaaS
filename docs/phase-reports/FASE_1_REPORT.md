# Relatório de Checkpoint — Fase 1 (Foundation/Core)

Ver critério de saída em [IMPLEMENTATION_ROADMAP.md](../IMPLEMENTATION_ROADMAP.md#fase-1--foundation--core)
e checklist de verificação em [DEVELOPMENT.md](../DEVELOPMENT.md).

## IMPLEMENTADO

- Monorepo com git inicializado, estrutura de pastas conforme
  [SYSTEM_ARCHITECTURE.md](../SYSTEM_ARCHITECTURE.md) (`backend/{core,ai_platform,ingestion,domains,api}`).
- `core/tenancy`: contexto de tenant via `contextvars` (`tenant_scope`, `get_current_tenant_id`),
  modelo `Tenant`.
- `core/db`: base declarativa SQLAlchemy, mixins (`IdMixin`, `TimestampMixin`,
  `TenantScopedMixin`), sessão com `tenant_session()` (aplica `SET LOCAL app.tenant_id`) e
  `system_session()` (dado GLOBAL), registro central de modelos (`core/db/registry.py`).
- `core/events`: outbox transacional (`DomainEvent`), `publish_event()`, dispatcher
  (outbox → Redis Stream) rodando como cron job.
- `core/jobs`: modelo `JobRun` (tenant-scoped, RLS), worker Arq com job de referência
  (`process_echo_job`) cobrindo o ciclo `PENDING → RUNNING → COMPLETED/FAILED`, enfileiramento a
  partir da API.
- `core/storage`: cliente MinIO/S3 com prefixo obrigatório por tenant e signed URLs.
- `core/cache`: cliente Redis com chave obrigatoriamente prefixada por tenant.
- `core/observability`: logging estruturado (structlog, JSON, `request_id` correlacionado) e
  métricas Prometheus (`http_requests_total`, `job_duration_seconds`, `outbox_events_dispatched_total`,
  etc.), endpoint `/metrics`.
- API HTTP mínima: `/healthz` (SYNC), `/v1/tenants` (bootstrap + `me`), `/v1/jobs/echo` (ASYNC,
  202 + consulta de status) — demonstrando a separação SYNC/ASYNC do ADR-0008.
- Migration inicial (Alembic) com **Row-Level Security habilitado e forçado** em `job_runs`,
  testada em ambas as direções (upgrade/downgrade/upgrade).
- Infraestrutura local via `docker-compose` (Postgres, Redis, MinIO).
- Import-linter configurado e validando as fronteiras `api → domains → ai_platform → core`.
- CI (GitHub Actions) com lint, type check, fronteiras de módulo, migrations e testes.

## TESTADO

Executado de fato neste ambiente (não apenas escrito):

- `ruff check .` — limpo.
- `mypy .` (modo strict) — limpo, 47 arquivos.
- `lint-imports` — 2/2 contratos de camada respeitados.
- `alembic upgrade head` / `downgrade base` / `upgrade head` — migration reversível confirmada.
- `pytest -v` — **13/13 testes passando**, incluindo:
  - `tests/security/test_tenant_isolation.py`: tenant B não lê job de tenant A (nem em leitura
    individual, nem em listagem), e uma tentativa de **escrever** um `JobRun` com `tenant_id` de
    outro tenant é **rejeitada pelo Postgres** (política `WITH CHECK`), não apenas pela aplicação.
  - `tests/integration/test_api_tenants.py`: fluxo HTTP completo via ASGI in-process.
  - `tests/unit/test_tenancy_context.py`: comportamento do `contextvar` de tenant.
- Fluxo ponta a ponta manual com API e worker reais rodando: criação de 2 tenants → job
  assíncrono disparado por um tenant → processado pelo worker → evento despachado do outbox para
  o Redis Stream → tenant correto vê o resultado completo → tenant B recebe 404 ao tentar acessar
  o job de A.
- Verificação direta no Postgres de que `job_runs` tem `relrowsecurity=t` e
  `relforcerowsecurity=t`, com a política `tenant_isolation_job_runs` ativa.

## PROBLEMAS (encontrados e corrigidos durante a fase, não escondidos)

1. **RLS não era de fato aplicado no primeiro teste manual.** O usuário de bootstrap do Postgres
   (`POSTGRES_USER` da imagem oficial) é criado como **superusuário**, e superusuário ignora RLS
   incondicionalmente — `FORCE ROW LEVEL SECURITY` não tem efeito sobre superusuário (só sobre o
   dono não-superusuário da tabela). O primeiro teste de isolamento passou "por engano" (tenant B
   conseguiu ler o job de tenant A). Corrigido criando um papel `app_runtime`, sem privilégio de
   superusuário (`ops/docker/initdb/01-app-role.sql`), usado pela API/worker em runtime;
   migrations continuam rodando com o usuário de bootstrap (que precisa de privilégio de DDL).
   Isso está documentado no [SECURITY_MODEL.md](../SECURITY_MODEL.md) e reforçado com um teste
   automatizado que só é significativo justamente porque roda sob o papel restrito.
2. **`SET LOCAL` não aceita bind parameter** (`$1`) no protocolo do Postgres/asyncpg — precisou
   virar literal interpolado com segurança (o valor já é um `uuid.UUID` validado antes de chegar
   ali, não uma string crua de entrada, então não há superfície de injeção).
3. **Pacote `platform/` sombrearia o módulo padrão do Python** — renomeado para `ai_platform`
   antes de qualquer código depender do nome errado. Documentado em ambos os lugares
   (`SYSTEM_ARCHITECTURE.md` e `backend/README.md`).
4. **Worker Arq falhava com `NoReferencedTableError`** porque o processo do worker só importava
   `core.jobs.models`, nunca `core.tenancy.models` — SQLAlchemy não resolve uma ForeignKey para
   uma tabela cujo modelo nunca foi importado naquele processo. Corrigido com
   `core/db/registry.py`, importado por worker, Alembic e API.
5. **`op.drop_table` não remove o tipo `ENUM` associado** no Postgres — o primeiro teste de
   downgrade/upgrade falhou com "type already exists". Corrigido adicionando `DROP TYPE`
   explícito no `downgrade()` da migration.
6. **Imagem `minio/minio` no Docker Hub retornou "pull access denied"** neste ambiente —
   resolvido usando `quay.io/minio/minio`, que é uma fonte de distribuição oficial alternativa do
   projeto MinIO. Ajustado no `docker-compose.yml`.
7. **Métricas Prometheus são por processo** — a métrica `outbox_events_dispatched_total`
   incrementada no worker não aparece no `/metrics` da API (são processos separados, cada um com
   seu próprio registro em memória do `prometheus_client`). Não é um bug, é uma limitação
   conhecida que precisa de solução explícita (scrape por processo, ou modo multiprocess do
   `prometheus_client`) antes da Fase 15 — registrado como pendência abaixo, não escondido.

## RISCOS

- O placeholder de autenticação (`X-Tenant-Id` sem verificação de identidade real) é
  **deliberadamente inseguro** e não pode, em hipótese alguma, ser exposto fora de ambiente local
  — é substituído por completo na Fase 2. Risco mitigado por estar isolado em `api/deps.py` com
  aviso explícito no docstring, e por nenhum ambiente além do local existir ainda.
- A migration de RLS depende de todo desenvolvedor lembrar de rodar
  `ops/docker/initdb/01-app-role.sql` em qualquer Postgres novo (o script só roda automaticamente
  em volume vazio). Mitigado documentando o passo no `backend/README.md`, mas vale considerar
  automatizar isso dentro do próprio `docker-compose` (ex.: healthcheck/entrypoint) numa fase
  posterior se continuar sendo fonte de erro manual.
- CI ainda não valida MinIO (nenhum teste depende disso hoje) — ver pendências.

## DECISÕES

- Confirmada a estratégia de RLS + papel não-superusuário do [ADR-0002](../adr/0002-multi-tenancy-isolamento.md),
  agora com evidência empírica de que a alternativa ingênua (RLS sem cuidado com o papel de
  conexão) falha silenciosamente.
- Pacote Python `platform` renomeado para `ai_platform` (deviation registrada, não é uma mudança
  de arquitetura, só de nome de diretório — não precisa de ADR novo, já anotado inline nos docs).
- Migrations rodam com um `DATABASE_URL` diferente do runtime (`MIGRATIONS_DATABASE_URL`) —
  padrão que deve se manter para toda migration futura.

## PENDÊNCIAS

1. Métricas multiprocess (worker vs. API) — resolver antes da Fase 15 (Observability hardening),
   ou mais cedo se isso já atrapalhar o debugging em Fase 3/4.
2. Automatizar a criação do papel `app_runtime` no bootstrap do `docker-compose` (hoje é um passo
   manual documentado, funciona mas depende de disciplina).
3. CI não cobre MinIO — adicionar quando o primeiro teste automatizado depender de storage real
   (Fase 4, Document Intelligence, provavelmente).
4. Tracing distribuído completo (OpenTelemetry) explicitamente fora do escopo desta fase (ver
   nota em `core/observability/logging.py`) — hoje a correlação é só por `request_id` em log.
   Suficiente para um monólito, mas listar como candidato quando `ingestion`/workers crescerem em
   número de saltos.

## PRÓXIMA FASE

Fase 2 — Auth + Multi-tenancy + Subscription: substituir o placeholder de `X-Tenant-Id` por
autenticação real (sessão/JWT com usuário), implementar `User`/`Role` sobre a base de `Tenant` já
existente, `Plan`/`Subscription`/`Entitlement` no schema, e o onboarding com enriquecimento
automático de `CompanyProfile` por CNPJ (promovido para esta fase na análise crítica). A base de
tenancy/RLS desta fase não muda — Fase 2 constrói em cima dela, não a substitui.
