# ADR-0011: Bootstrap de autenticação via índices GLOBAL (EmailIndex, RefreshToken), não bypass de RLS

## Status
Aceito

## Contexto
Login por email+senha e renovação por refresh token não sabem o `tenant_id` de antemão — é
exatamente isso que a consulta precisa descobrir. Mas `users` é uma tabela `TENANT` com RLS
forçado (ver [ADR-0002](0002-multi-tenancy-isolamento.md)): sem `SET LOCAL app.tenant_id`
definido, `current_setting(...)` retorna `NULL` e a política de RLS não libera nenhuma linha —
correto para todo o resto do sistema, mas um impasse de "ovo e galinha" para o primeiro passo do
login.

## Decisão
Duas estruturas **GLOBAL** (sem `tenant_id` como filtro de RLS, sem RLS habilitado) resolvem o
bootstrap sem abrir uma exceção na política de RLS de `users`:

- `EmailIndex` (email → user_id, tenant_id): populada na mesma transação que cria o `User`.
  Login consulta este índice primeiro (via `system_session()`), descobre o tenant, e só então
  abre `tenant_session()` para validar a senha contra o `User` real.
- `RefreshToken` (GLOBAL): sua segurança vem de ser um segredo de 256 bits improvável de
  adivinhar e comparado por hash — não de um filtro de linha por tenant. Refresh/logout também
  consultam via `system_session()`, descobrem o `tenant_id` a partir do token, e só then agem
  sobre dado tenant-scoped quando necessário (ex.: verificar se o `User` ainda está ativo).

## Alternativas consideradas
- **Política de RLS com bypass condicional** (ex.: `USING (tenant_id = current_setting(...) OR
  current_setting('app.auth_bypass', true) = 'on')`): rejeitada. Introduz um mecanismo de exceção
  na política de segurança mais importante do sistema — mesmo bem contido (só relaxando SELECT,
  nunca WITH CHECK), é uma superfície de risco e de complexidade de manutenção desnecessária
  quando uma tabela auxiliar sem RLS resolve o mesmo problema de forma mais simples e mais fácil
  de auditar (grep por `EmailIndex`/`RefreshToken` mostra exatamente onde e por que).
- **Exigir um identificador de tenant (ex.: slug) no login**: rejeitada — pior UX (usuário
  precisaria saber/digitar o "workspace" antes do email), sem benefício de segurança
  correspondente.

## Consequências
- `email` é único **globalmente** na plataforma, não por tenant — uma pessoa com acesso a duas
  empresas cadastradas nesta plataforma precisa de dois emails diferentes (ver
  [DOMAIN_MODEL.md](../DOMAIN_MODEL.md), já assumia usuários não multi-tenant nesta v1).
- `EmailIndex` e `RefreshToken` são escritos a partir de código que roda dentro de uma transação
  `tenant_session()` (ex.: criar um novo usuário) — isso é seguro porque RLS é por tabela; uma
  tabela sem política de RLS não é afetada pelo `SET LOCAL app.tenant_id` da sessão.
- Qualquer nova necessidade de "descobrir o tenant a partir de um segredo/identificador
  pré-autenticação" deve seguir o mesmo padrão (tabela GLOBAL auxiliar), não abrir uma nova
  exceção de RLS.

## Nota relacionada: composition roots fora de `core/`
O mesmo tipo de restrição (uma camada não pode depender de outra "de dentro para fora") apareceu
ao implementar o worker Arq e o registro de modelos do Alembic: `core/jobs` não pode importar
`domains/procurement/companies/jobs.py` (job de enriquecimento de CNPJ), e um registro central de
modelos não pode importar modelos de `domains` se vivesse dentro de `core/db`. Resolvido da mesma
forma que `api/main.py` já resolvia isso para o processo HTTP: `backend/worker.py` e
`backend/model_registry.py` são *composition roots* no nível raiz do backend, fora de qualquer
pacote em camadas, autorizados a importar de todo bounded context porque sua única responsabilidade
é montar o processo, não conter lógica de domínio. Ver `backend/README.md`.
