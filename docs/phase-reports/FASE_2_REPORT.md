# Relatório de Checkpoint — Fase 2 (Auth + Multi-tenancy + Subscription)

Ver critério de saída em [IMPLEMENTATION_ROADMAP.md](../IMPLEMENTATION_ROADMAP.md#fase-2--auth--multi-tenancy--subscription):
"uma empresa consegue criar conta e ter `CompanyProfile` parcialmente preenchido
automaticamente."

## IMPLEMENTADO

- `core/auth`: `User` (TENANT, RLS), `Role` (owner/admin/member), `EmailIndex` e `RefreshToken`
  (GLOBAL, ver [ADR-0011](../adr/0011-auth-bootstrap-global-lookup.md)). Hash de senha com
  bcrypt, access token JWT (HS256, 15min) e refresh token opaco de 256 bits com rotação (uso
  revoga o token antigo, nunca reutilizável).
- `core/permissions`: checagem de RBAC pura (`ensure_role`), consumida por `api/deps.py`
  (`require_role`).
- `core/billing`: `Plan` (GLOBAL, catálogo) e `Subscription` (TENANT, RLS). Toda conta nova nasce
  com uma `Subscription` em `trialing` no plano `trial` (seed via migration, `max_users: 3`).
  Sem `Entitlement`/`Usage` como tabelas — decisão YAGNI documentada em `core/billing/models.py`
  (sem consumidor real além de `max_users`, calculado sob demanda).
- `domains/procurement/companies`: primeiro pedaço de domínio de negócio. `CompanyProfile`
  (TENANT, RLS) com `EnrichmentStatus`; adapter de consulta de CNPJ via BrasilAPI
  (`cnpj_lookup.py`); serviço de enriquecimento assíncrono (`service.py` + `jobs.py`).
- `api/onboarding.py`: orquestração do signup completo (Tenant + User owner + Subscription trial
  + CompanyProfile + job de enriquecimento se houver CNPJ) — o único módulo autorizado a compor
  os três bounded contexts, por ser da camada `api` (topo da cadeia de dependência).
- Endpoints novos: `POST /v1/auth/{signup,login,refresh,logout}`, `GET/POST /v1/users`,
  `GET /v1/company-profile`, `PUT /v1/company-profile/cnpj`. `GET /v1/tenants/me` e
  `GET /v1/jobs/{id}` migrados do placeholder `X-Tenant-Id` (Fase 1) para JWT real.
- Removido: `POST /v1/tenants` (bootstrap aberto da Fase 1) e `POST /v1/jobs/echo` +
  `process_echo_job` (demo da Fase 1, substituída pelo job real de enriquecimento).
- Migration com RLS habilitado e forçado em `users`, `subscriptions`, `company_profiles`;
  `email_index`, `refresh_tokens` e `plans` deliberadamente sem RLS (GLOBAL); seed do plano
  `trial`. Testada em ambas as direções.
- `backend/worker.py` e `backend/model_registry.py`: novos *composition roots* no nível raiz do
  backend (ver "PROBLEMAS" abaixo) — mesmo papel de `api/main.py`, mas para o processo worker e
  para o registro de modelos do Alembic.

## TESTADO

- `ruff check .`, `mypy .` (strict), `lint-imports` — todos limpos (72 arquivos-fonte).
- `alembic upgrade head` / `downgrade -1` / `upgrade head` — migration da Fase 2 reversível,
  confirmada com verificação direta de RLS (`relrowsecurity`/`relforcerowsecurity`) e do seed do
  plano trial via `psql`.
- `pytest -v` — **32/32 testes passando**, incluindo:
  - `tests/unit/test_auth_security.py`: roundtrip de hash de senha e de JWT, rejeição de token
    adulterado/assinado com chave errada/expirado.
  - `tests/security/test_auth_isolation.py`: `CompanyProfile` de um tenant é invisível a outro
    (nível de serviço) e, fim a fim via API, o token de um tenant nunca traz dado de outro.
  - `tests/integration/test_auth_flow.py`: signup → login → endpoint protegido → refresh (com
    rotação e rejeição de reuso) → logout (com rejeição de refresh após logout).
  - `tests/integration/test_users_entitlement.py`: RBAC (member não pode convidar) e enforcement
    real do limite de usuários do plano trial (4º convite rejeitado com 403).
  - `tests/integration/test_company_enrichment.py`: enriquecimento com sucesso e com CNPJ não
    encontrado (respx mockando a BrasilAPI), mais o endpoint que dispara o job.
  - Suíte reexecutada duas vezes seguidas sem resetar o banco, para confirmar idempotência (ver
    "PROBLEMAS" — isso não era verdade na primeira tentativa).
- **Smoke test manual fim a fim com API e worker reais**: signup com CNPJ real (Open Knowledge
  Brasil, `19131243000197`) contra a BrasilAPI real (não mockada) — `enrichment_status` passou de
  `pending` para `enriched` com razão social, nome fantasia, CNAEs e UF corretos, verificados
  tanto via API quanto diretamente no Postgres (a acentuação exibida errada no terminal era
  artefato de codepage do console, não corrupção de dado — conferido via `psql`).

## PROBLEMAS (encontrados e corrigidos durante a fase)

1. **Violação do contrato de camadas (`core` importando `domains`)**: a primeira versão de
   `core/auth/service.py` criava o `CompanyProfile` diretamente dentro da função de signup,
   importando `domains.procurement.companies.models` — o import-linter (configurado desde a Fase
   1) pegou isso antes de qualquer teste rodar. Corrigido extraindo a orquestração cross-domain
   para `api/onboarding.py` (única camada autorizada a depender de tudo), deixando
   `core/auth/service.py` responsável só por Tenant+User+tokens.
2. **Mesmo problema, no registro de modelos**: `core/db/registry.py` precisaria importar
   `domains.procurement.companies.models` para o Alembic enxergar `CompanyProfile`, o que também
   violaria a camada. Corrigido promovendo o registro para `backend/model_registry.py`, um
   *composition root* fora de qualquer pacote em camadas — mesma solução aplicada ao worker (ver
   item 3).
3. **Mesmo problema, no worker Arq**: `core/jobs/worker.py` não pode importar
   `domains/procurement/companies/jobs.py` (job de enriquecimento). Corrigido: o conteúdo
   genérico virou `core/jobs/generic_jobs.py`, e `backend/worker.py` (novo, no nível raiz) é quem
   combina jobs genéricos e jobs de domínio no `WorkerSettings` — documentado em
   [ADR-0011](../adr/0011-auth-bootstrap-global-lookup.md) (nota final) e no
   `backend/README.md`.
4. **Testes não eram idempotentes entre execuções**: a primeira rodada da suíte passou, mas
   rodar `pytest` de novo sem resetar o Postgres falhou — os testes usavam emails e CNPJs fixos
   (`"dono@exemplo.com"`, `"11222333000181"`), e agora `EmailIndex.email` e
   `CompanyProfile.cnpj` têm unicidade **global** (não só por tenant). Corrigido com helpers
   `unique_email()`/`unique_cnpj()` em `tests/conftest.py`, usados por todos os testes de
   integração/segurança da Fase 2. Confirmado rodando a suíte duas vezes seguidas sem limpeza de
   banco.
5. **`types-pyjwt` conflitava com os tipos inline do PyJWT**: causava um falso positivo de mypy
   (`jwt.encode` "retornando bytes" quando na verdade retorna `str` no PyJWT 2.x). Removido —
   PyJWT já é `py.typed` desde a v2, o stub separado era para versões antigas.
6. **`HTTPBearer` sem credenciais retorna 401, não 403**: um teste assumiu 403 por engano (não é
   um bug de produção, era a expectativa errada no teste) — corrigido para refletir o
   comportamento real, que aliás é semanticamente mais correto (401 = sem credenciais válidas).

## RISCOS

- `email` e `cnpj` são únicos **globalmente** na plataforma (não por tenant) — decisão deliberada
  (ver [ADR-0011](../adr/0011-auth-bootstrap-global-lookup.md) e `DOMAIN_MODEL.md`), mas significa
  que uma pessoa com papel em duas empresas cadastradas aqui precisa de dois emails diferentes.
  Aceitável para o perfil de cliente-alvo desta fase; revisar se isso virar uma reclamação real de
  usuário.
- Convite de usuário (`POST /v1/users`) cria a conta com senha já definida pelo owner/admin, sem
  fluxo de confirmação por email — aceitável como simplificação documentada (Notification Engine
  é Fase 10), mas é uma lacuna de segurança/UX real se o produto for exposto além de uso interno
  antes da Fase 10 (quem convida sabe a senha do convidado até que ele troque).
- Access token de 15 minutos sem verificação de que o usuário/tenant ainda está ativo entre
  emissão e expiração (é o trade-off padrão de JWT stateless) — se um usuário for desativado, o
  token dele continua válido até expirar. Aceitável dado o TTL curto; revisar se algum caso de uso
  de desativação imediata (ex.: usuário comprometido) precisar de revogação síncrona antes disso
  virar um problema real.

## DECISÕES

- Confirmado o padrão de índice GLOBAL para bootstrap de autenticação em vez de bypass de RLS —
  ver [ADR-0011](../adr/0011-auth-bootstrap-global-lookup.md) (nova).
- Confirmado o padrão de *composition root* fora de `core/` para qualquer processo/registro que
  precise atravessar bounded contexts (`api/main.py`, `backend/worker.py`,
  `backend/model_registry.py`, `api/onboarding.py`) — generalizado para futuras fases: nenhuma
  orquestração cross-domain deve viver dentro de `core/`.
- `Entitlement`/`Usage` permanecem fora do schema (YAGNI) até haver um segundo consumidor de
  limite além de `max_users` — revisar quando `Analysis`/`Opportunity` (Fase 7/8) precisarem de
  limites próprios.

## PENDÊNCIAS

1. Fluxo de convite de usuário com confirmação por email (depende do Notification Engine, Fase
   10) — hoje é uma simplificação documentada, não um esquecimento.
2. Revisão de revogação síncrona de acesso (deactivate now vs. esperar expiração do access token)
   se/quando houver caso de uso real que exija isso.
3. `docs/UX_AND_ASSISTANT_SPEC.md` já previa onboarding com enriquecimento automático — nenhuma
   revisão de documento pendente, mas vale conferir se o formato de resposta de
   `GET /v1/company-profile` (campos `cnaes`/`regions`) é o suficiente para a tela de "Minha
   Empresa" quando o frontend (Fase 11) for construído.

## PRÓXIMA FASE

Fase 3 — Ingestion Engine (PNCP): implementar o `Connector` para a API do PNCP (fonte canônica,
ver [ADR-0009](../adr/0009-pncp-fonte-canonica.md)) e o pipeline fetch → validação → dedup → hash
→ versionamento → raw storage. Não depende de nenhuma decisão em aberto desta fase.
