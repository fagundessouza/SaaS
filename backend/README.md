# Backend — Fase 1 (Foundation/Core)

Implementa o núcleo transversal descrito em [docs/SYSTEM_ARCHITECTURE.md](../docs/SYSTEM_ARCHITECTURE.md):
tenancy, outbox de eventos, fila de jobs assíncrona, storage, cache e observabilidade básica.
Nenhum domínio de negócio (`domains/procurement`) existe ainda — isso é Fase 6+.

## Subindo o ambiente local

```bash
# 1. Infraestrutura (Postgres, Redis, MinIO)
cd ops/docker
docker compose up -d

# 2. Dependencias Python
cd ../../backend
uv sync
cp .env.example .env   # ajustar se necessario

# 3. Papel de banco sem privilegio de superusuario (OBRIGATORIO — ver ADR-0002).
#    O usuario de bootstrap do Postgres (POSTGRES_USER) e superuser e ignora RLS
#    incondicionalmente; sem este passo, o isolamento multi-tenant nao e de fato aplicado.
docker exec -i licitacoes-dev-postgres-1 psql -U licitacoes -d licitacoes \
  < ../ops/docker/initdb/01-app-role.sql

# 4. Migrations
uv run alembic upgrade head

# 5. API
uv run uvicorn api.main:app --reload

# 6. Worker (em outro terminal)
uv run arq core.jobs.worker.WorkerSettings
```

> Nota: `ops/docker/initdb/` só é executado automaticamente pelo Postgres na primeira
> inicialização de um volume vazio. Se o container já existia antes deste arquivo ser criado,
> rode o passo 3 manualmente (como acima) — é idempotente, pode ser repetido sem risco.

## Verificando que o isolamento de tenant funciona

```bash
# cria dois tenants
curl -s -X POST localhost:8000/v1/tenants -H "Content-Type: application/json" -d '{"name":"A"}'
curl -s -X POST localhost:8000/v1/tenants -H "Content-Type: application/json" -d '{"name":"B"}'

# dispara um job como tenant A, tenta ler como tenant B (espera 404)
curl -s -X POST localhost:8000/v1/jobs/echo -H "X-Tenant-Id: <ID_A>" -d '{"message":"oi"}'
curl -s localhost:8000/v1/jobs/<JOB_ID> -H "X-Tenant-Id: <ID_B>"
```

O mesmo cenário está automatizado em `tests/security/test_tenant_isolation.py`.

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

## O que existe e o que não existe ainda

Existe: `core/tenancy`, `core/events` (outbox), `core/jobs` (fila Arq), `core/storage` (MinIO),
`core/cache` (Redis), `core/observability` (logging + métricas), RLS aplicado e testado, um
endpoint HTTP síncrono (`/v1/tenants`) e um fluxo assíncrono de referência (`/v1/jobs/echo`).

Não existe ainda: autenticação real (a extração de tenant via header `X-Tenant-Id` é um
placeholder documentado em `api/deps.py`, substituído na Fase 2), `ai_platform/`, `ingestion/` e
`domains/` (pacotes vazios, populados a partir da Fase 3), frontend.
