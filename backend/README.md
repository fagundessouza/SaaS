# Backend

Fase 1 (Foundation/Core) implementou o núcleo transversal descrito em
[docs/SYSTEM_ARCHITECTURE.md](../docs/SYSTEM_ARCHITECTURE.md): tenancy, outbox de eventos, fila
de jobs assíncrona, storage, cache e observabilidade básica.

Fase 2 (Auth + Multi-tenancy + Subscription) adicionou autenticação real (JWT + refresh token),
RBAC (owner/admin/member), billing mínimo (Plan/Subscription, sem gateway de pagamento) e o
primeiro pedaço de `domains/procurement`: `CompanyProfile` com enriquecimento automático por CNPJ
(BrasilAPI).

## Subindo o ambiente local

```bash
# 1. Infraestrutura (Postgres, Redis, MinIO)
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
`domains/procurement/companies` (CompanyProfile + enriquecimento por CNPJ). RLS aplicado e
testado em toda tabela `TENANT` (`job_runs`, `users`, `subscriptions`, `company_profiles`).

Não existe ainda: qualquer outro domínio de `domains/procurement` (tenders, opportunities,
analysis — Fase 6+), `ingestion/` (Fase 3), frontend, `ai_platform/` (Fase 5+), envio de e-mail de
convite/verificação (fica para o Notification Engine, Fase 10 — hoje o owner/admin já cria o
usuário com senha definida, sem fluxo de confirmação por e-mail).
