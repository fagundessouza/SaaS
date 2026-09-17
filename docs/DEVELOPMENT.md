# Estrutura de Repositório, Convenções e Estratégia de Ambiente/Testes

## Estrutura do repositório (monorepo)

```
/
├── backend/                # Python (FastAPI) — ver SYSTEM_ARCHITECTURE.md para estrutura interna
│   ├── core/
│   ├── platform/
│   ├── ingestion/
│   ├── domains/
│   ├── api/
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   ├── security/        # isolamento de tenant, RBAC — categoria própria, não misturada em integration/
│   │   └── fixtures/         # dados sintéticos versionados (nunca dado real sensível)
│   └── alembic/               # migrations
│
├── frontend/                # Next.js + React + TypeScript + Tailwind
│
├── ops/
│   ├── docker/                # docker-compose para desenvolvimento local
│   ├── podman/                # manifestos equivalentes para produção
│   └── n8n/                    # flows de automação auxiliar (não-crítica) versionados como JSON
│
└── docs/                     # esta pasta
    └── adr/
```

## Convenções

- **Python**: type hints obrigatórios em código novo, formatação automática (ruff/black),
  `mypy`/`pyright` em CI. Nenhum PR quebra o type check.
- **Fronteiras de módulo**: import linter (ex.: `import-linter` ou equivalente) garantindo que
  `domains/procurement` não importe de `api/`, que `core/` não importe de `domains/` nem de
  `platform/`, e que `platform/` não importe de `domains/` — a dependência é sempre de fora para
  dentro (`api → domains → platform → core`), nunca o contrário. Isso é o que torna a separação de
  camadas do [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) verificável em CI, não só uma
  convenção de boa vontade.
- **Migrations**: toda mudança de schema via Alembic, revisável em PR, com checagem automatizada de
  que a migration é reversível (`downgrade` testado) e de que não há migration destrutiva sem
  aprovação explícita.
- **Commits/PRs**: um PR por unidade de trabalho coerente; nenhuma mudança de arquitetura sem ADR
  correspondente (seção 32/36 do prompt mestre).
- **TypeScript/Frontend**: strict mode, componentes tipados, sem `any` não justificado.

## Estratégia de ambiente

| Ambiente | Propósito | Dados |
|---|---|---|
| Local (docker-compose) | Desenvolvimento | Sintéticos (fixtures versionadas) |
| CI | Testes automatizados a cada PR | Sintéticos, efêmeros |
| Staging | Validação pré-produção, inclui clientes piloto de confiança quando aplicável | Anonimizados ou reais de piloto com consentimento explícito |
| Produção | — | Reais, com toda a política de retenção/LGPD de [SECURITY_MODEL.md](SECURITY_MODEL.md) |

Produção usa Podman (conforme especificado); desenvolvimento usa Docker por conveniência de
ferramentas — os manifestos são mantidos equivalentes (mesma composição de serviços), não
divergentes.

## Estratégia de testes (seção 26 do prompt mestre, categorizada)

| Categoria | O que cobre | Observação |
|---|---|---|
| Unitário | Regras determinísticas (matching, pricing engine, extração de metadado) | Rápido, roda em todo PR |
| Integração | Fluxos entre módulos (ingestão → indexação → matching) contra banco/Qdrant reais em container | Roda em CI, não em cada save local |
| API | Contratos de endpoint, incluindo casos de erro e paginação | Contra API real, banco de teste |
| Segurança/isolamento | Tenant A nunca acessa dado de tenant B, em toda camada de dados listada em SECURITY_MODEL.md | **Obrigatório em todo PR que toca `core/tenancy`, `platform/retrieval`, `core/storage`, `core/cache`** — bloqueia merge se ausente |
| RAG/matching | Conjunto de casos reais anotados (edital conhecido → resultado esperado) | Base também usada para observabilidade de regressão em produção (ver OBSERVABILITY.md) |
| Eventos/webhooks | Idempotência, reentrega, ordem | Simula reentrega de evento duplicado |
| Assistente | Contexto correto injetado, ferramentas não vazam tenant | Ver casos de SECURITY_MODEL.md |
| Regressão | Conjunto crescente de bugs corrigidos, nunca reintroduzidos | Adicionado a cada bug real corrigido |

Dados sintéticos de teste são gerados a partir de templates de edital reais **anonimizados/
sintetizados na estrutura**, nunca commitando um edital real com dados sensíveis de terceiros sem
verificar que é conteúdo público apropriado para repositório.

## Definição de pronto (Definition of Done) por unidade de trabalho

1. Código implementado dentro das fronteiras de módulo (verificado por import linter).
2. Testes das categorias aplicáveis passando.
3. Lint e type check limpos.
4. Migration (se houver) revisável e reversível.
5. Se a mudança tocar isolamento de tenant, teste de segurança específico adicionado.
6. Se a mudança alterar decisão arquitetural registrada em ADR, o ADR é atualizado (nunca
   silenciosamente contradito).
