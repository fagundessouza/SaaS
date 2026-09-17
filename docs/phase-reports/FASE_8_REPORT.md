# Relatório de Checkpoint — Fase 8 (Analysis Engine)

Ver critério de saída em [IMPLEMENTATION_ROADMAP.md](../IMPLEMENTATION_ROADMAP.md#fase-8--analysis-engine-escopo-mínimo-findings--evidence-sem-legalpricing-ainda):
"dossiê de uma oportunidade real mostra pendências corretas e rastreáveis."

## IMPLEMENTADO

- `domains/procurement/companies/models.py`: `Certificate` (certidão fiscal/jurídica/
  econômico-financeira que o tenant declara ter) e `Attestation` (atestado de capacidade
  técnica) — ambos TENANT, filhos de `CompanyProfile` (ver DOMAIN_MODEL.md). `Certificate.category`
  reaproveita `RequirementCategory` da Fase 6 de propósito: é a mesma taxonomia usada por
  `Requirement.category`, o que permite cruzar um requisito com a certidão que o atende sem uma
  segunda tabela de mapeamento.
- `domains/procurement/companies/certificates_service.py` /
  `domains/procurement/companies/attestations_service.py`: CRUD simples (create/list/delete).
- `domains/procurement/analysis/models.py`: `Analysis` (uma por `Opportunity`, sem histórico de
  versões — regenerar substitui), `Finding` (`status`: met/missing/expired/needs_review,
  `severity`: blocking/warning/info) e `Evidence` (`kind`: requirement_text/certificate_data/
  attestation_data — nunca existe `Finding` sem pelo menos uma `Evidence`, conforme DOMAIN_MODEL).
- `domains/procurement/analysis/service.py`: `generate_analysis(opportunity_id)` — cruza cada
  `Requirement` do edital (Fase 6, GLOBAL) contra o que o tenant tem:
  - Categorias `FISCAL`/`JURIDICA`/`ECONOMICO_FINANCEIRA` → **regra determinística** contra
    `Certificate`: existe uma certidão da mesma categoria? Está dentro da validade (comparação
    de data)? Nenhuma chamada de IA (ADR-0007: "prazos, comparação de datas" → regra).
  - Categoria `TECNICA` → **IA (embedding)** contra `Attestation`: não há campo estruturado
    equivalente a "vencimento" para experiência técnica, a pergunta é semântica ("este atestado
    cobre o que este requisito pede?") — mesmo `EmbeddingProvider` self-hosted da Fase 5, dois
    limiares configuráveis (`analysis_attestation_met_threshold`/`_review_threshold`) decidindo
    entre `MET`, `NEEDS_REVIEW` (revisão humana recomendada) e `MISSING`.
  - Nunca gerada automaticamente para toda `Opportunity` descoberta (ver
    docs/00-CRITICAL_ANALYSIS.md item 5 da seção 6) — só quando o usuário aprofunda, via
    `POST /v1/opportunities/{id}/analysis`.
- `api/v1/companies.py`: `GET/POST/DELETE /v1/company-profile/certificates` e
  `/attestations` (mutação exige OWNER/ADMIN, leitura qualquer usuário autenticado).
- `api/v1/opportunities.py`: `GET/POST /v1/opportunities/{id}/analysis` — `GET` retorna 404 se
  nenhuma análise foi gerada ainda (nunca gera implicitamente); `POST` gera ou regenera.
- Métricas novas: `analyses_generated_total`, `findings_by_status_total` (por status).

## TESTADO

- `ruff`, `mypy --strict`, `import-linter` — limpos (137 arquivos-fonte).
- Migration (`certificates`, `attestations`, `analyses`, `findings`, `evidences`, RLS nas 5
  tabelas TENANT) `upgrade`/`downgrade`/`upgrade` — reversível, com `DROP TYPE IF EXISTS` para
  os três ENUMs novos (`finding_status`, `finding_severity`, `evidence_kind`).
- **Smoke test manual de ponta a ponta antes de escrever os testes formais** (mesma disciplina
  das fases anteriores): gerei uma Analysis sintética com 3 Requirement (jurídica sem certidão,
  fiscal com certidão válida, técnica com atestado relacionado) — encontrou dois bugs reais
  antes de qualquer teste formal existir (ver PROBLEMAS).
- `pytest -v` — **140 testes passando**, rodados três vezes seguidas (48s/42s/85s — ver PROBLEMAS
  item 3 sobre por que essas execuções antes levavam 6-7 minutos e ficavam flaky).
  - `tests/unit/test_analysis_service.py` (8 testes): regra de certidão pura — sem candidato,
    categoria errada, sem vencimento, vencendo no futuro, vencida, vencendo exatamente hoje
    (`>=`, não `>`), prioriza válida sobre vencida da mesma categoria, `_category_label` cobre
    tanto enum quanto string crua.
  - `tests/integration/test_analysis_service.py` (7 testes, Postgres + fastembed real): dossiê
    cobre missing/met/expired de certidão; atestado casado por similaridade semântica real;
    regeneração substitui sem duplicar; erro claro para Opportunity/CompanyProfile inexistente;
    erro claro ao ler Analysis antes de gerar.
  - `tests/integration/test_analysis_api.py` (5 testes): CRUD de certidão/atestado via API;
    análise retorna 404 antes de gerar; gerar e reler via API.
  - `tests/security/test_analysis_isolation.py` (3 testes): certidões/atestados de um tenant
    invisíveis a outro; análises/findings/evidências de um tenant invisíveis a outro; token de
    outro tenant não alcança a análise via API (404, não 403 — mesmo padrão já provado para
    Opportunity na Fase 7).

## PROBLEMAS (encontrados e corrigidos durante esta fase)

1. **`.value` quebrando em `category` lido do banco**, achado no smoke test manual:
   `Requirement.category`/`Certificate.category` são colunas `String` puras (não `Enum`,
   decisão já tomada na Fase 6) — um valor lido de volta do banco chega como `str` puro, não uma
   instância de `RequirementCategory`, então `requirement.category.value` levantava
   `AttributeError: 'str' object has no attribute 'value'`. Corrigido com um helper
   `_category_label()` que usa `str(x)` (funciona igual para os dois casos, porque
   `StrEnum.__str__` retorna o próprio valor) em vez de `.value`. Teste de regressão:
   `test_category_label_handles_raw_string_from_db_round_trip`.
2. **`tenant_id` ausente ao criar Certificate/Attestation pela API**, achado pelo próprio RLS ao
   rodar os testes de API pela primeira vez (`InsufficientPrivilegeError: new row violates
   row-level security policy`): `certificates_service.create_certificate`/
   `attestations_service.create_attestation` construíam o modelo sem passar `tenant_id`
   explicitamente — `TenantScopedMixin.tenant_id` não tem default, então ficava `None`, e o
   `WITH CHECK` da política RLS rejeitou o insert antes de qualquer dado vazar. Corrigido
   adicionando `tenant_id` como parâmetro explícito nos dois serviços (mesmo padrão já usado por
   `create_opportunity_from_match`), com o `api/v1/companies.py` passando
   `current_user.tenant_id`. Prova concreta de que a defesa em profundidade do ADR-0002
   funciona: um bug real de aplicação foi barrado no banco, não silenciosamente ignorado.
3. **`run_opportunity_matching_job` (Fase 7) ficando lento e flaky por acúmulo do Postgres de
   dev**, achado rodando a suíte completa repetidas vezes durante esta fase: o job é
   O(tenants × tenders) por design (documentado como limitação conhecida desde a Fase 7), e
   depois de um dia inteiro de testes (Fases 5 a 8, várias rodadas completas cada) o Postgres de
   desenvolvimento acumulou milhares de tenants/tenders de sessões anteriores — o job passou a
   levar 6-7 minutos por execução, e `tests/integration/test_opportunity_matching_job.py` (que
   já rodava o job de verdade) começou a falhar de forma inconsistente (um teste diferente a
   cada rodada — assinatura clássica de lentidão por volume, não de bug lógico). Mesma causa raiz
   já resolvida uma vez nesta sessão para o Qdrant (Fase 6, `_reset_knowledge_collection`), agora
   resolvida de forma equivalente para o Postgres: nova fixture `_reset_accumulating_tables`
   (`tests/conftest.py`, `session`-scoped) roda `TRUNCATE TABLE tenants, tenders CASCADE` uma vez
   por sessão de pytest, via a engine de migrations (usuário `licitacoes`, superusuário — o
   `app_runtime` usado em runtime não tem privilégio de `TRUNCATE`, só
   SELECT/INSERT/UPDATE/DELETE). Resultado mensurável: suíte completa caiu de 390-420s (com
   falhas intermitentes) para 42-85s (140/140 passando em três rodadas consecutivas).
   Achado colateral: a fixture inicialmente falhava com `permission denied for table tenants`
   porque `os.environ.get("MIGRATIONS_DATABASE_URL")` só funciona se algo já carregou o `.env`
   no ambiente do processo — `Settings` (pydantic-settings) lê o `.env` por conta própria sem
   popular `os.environ`. Corrigido chamando `load_dotenv()` explicitamente, mesmo padrão já
   usado por `alembic/env.py` (o único outro lugar que precisa do papel superusuário).

## RISCOS

- Limiares de similaridade de atestado (`analysis_attestation_met_threshold=0.55`,
  `_review_threshold=0.40`) são valores de engenharia, não calibrados contra dado real — ao
  contrário de `opportunity_semantic_match_threshold` (Fase 7), que foi calibrado contra 100
  editais reais do PNCP. Mesma ressalva já feita repetidamente desde a Fase 5/6: calibrar quando
  houver volume de cliente piloto real.
- `Certificate` não tem verificação automática contra fonte externa (Receita Federal, TST etc.)
  — `status` é inteiramente uma regra determinística sobre `expires_at` declarado pelo próprio
  tenant. A seção 10K do prompt mestre original previa um `CertificateValidationLog` com
  verificação de fonte externa; deliberadamente fora do escopo mínimo desta fase (ver DECISÕES).
- Categorias `JURIDICA`/`ECONOMICO_FINANCEIRA` e `FISCAL` compartilham o mesmo mecanismo
  (`Certificate` por categoria) mas são conceitualmente diferentes (contrato social não "vence"
  como uma certidão fiscal) — o modelo já suporta isso (`expires_at=None` = nunca vence), mas
  não há uma UI/validação ainda que oriente o usuário sobre qual tipo de documento cadastrar em
  qual categoria (fica para a Fase 11, Frontend).
- `Analysis` não gera nenhum `Finding` para requisitos que a Fase 6 não conseguiu extrair (edital
  sem seção de habilitação reconhecida, ver RISCOS da Fase 6) — o dossiê fica silenciosamente
  incompleto nesse caso, não incorreto. Mesmo princípio de "fallback documentado" das fases
  anteriores, mas vale registrar como um limite real do que "dossiê correto" significa hoje.

## DECISÕES

- **Sem `CertificateValidationLog`/verificação automática externa nesta fase**: a seção 10K do
  prompt mestre prevê um histórico de verificações contra fonte externa (Receita Federal, TST) —
  isso exigiria integração com fontes que não foram verificadas ao vivo ainda (diferente do PNCP,
  BrasilAPI já usados). `status` calculado sob demanda a partir de `expires_at` declarado é
  suficiente para o critério de saída desta fase ("pendências corretas e rastreáveis" — o
  usuário sabe que uma certidão está vencida porque ELE declarou a data, não porque o sistema
  afirma algo que não verificou). Entra quando houver uma fonte real para integrar.
- **`Certificate.category` reaproveita `RequirementCategory`** em vez de uma taxonomia própria —
  mesmo raciocínio de reduzir vocabulários paralelos já aplicado a outras decisões do projeto:
  um `Requirement` e o `Certificate` que o atende precisam falar a mesma linguagem de categoria
  para o cruzamento em `generate_analysis` funcionar sem uma tabela de mapeamento adicional.
- **`Evidence` sempre carrega pelo menos a evidência do próprio requisito** (`REQUIREMENT_TEXT`),
  mesmo quando o resultado é `MISSING` (nada do lado do tenant para citar) — o "o que foi pedido"
  é sempre uma evidência válida por si só, consistente com o DOMAIN_MODEL ("nunca existe Finding
  sem pelo menos uma Evidence").
- **Sem endpoint de exclusão/edição de Analysis** — só `POST` (gera/regenera) e `GET` (lê a mais
  recente). Não há necessidade de um histórico de análises nesta fase (mesma decisão já tomada
  para `TenderItem` na Fase 6): o usuário sempre quer o dossiê mais atual.

## PENDÊNCIAS

1. Calibrar `analysis_attestation_met_threshold`/`_review_threshold` contra atestados reais de
   cliente piloto, mesmo padrão de pendência já registrado nas Fases 5/6/7.
2. `CertificateValidationLog` + verificação automática contra fonte externa (seção 10K) — quando
   houver uma fonte real identificada para integrar.
3. Distinguir melhor, na camada de apresentação (Fase 11), qual tipo de documento cadastrar em
   cada categoria de `Certificate` (contrato social vs. certidão fiscal vs. balanço patrimonial).

## PRÓXIMA FASE

Fase 9 — Assistente (escopo mínimo: contexto de tela + ações da Fase 7/8): botão flutuante,
contexto automático, 3–4 ações da lista da seção 16. Critério de saída: assistente responde "o
que está faltando?" citando evidência real do dossiê desta fase.
