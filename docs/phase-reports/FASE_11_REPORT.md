# Relatório de Checkpoint — Fase 11 (Frontend)

Ver nota de processo em [IMPLEMENTATION_ROADMAP.md](../IMPLEMENTATION_ROADMAP.md#fase-11--frontend-paralelo-às-fases-610-não-sequencial-após-elas):
"o frontend não espera o backend estar 100% pronto — cresce em paralelo contra contratos de API
estabilizados desde a Fase 1." Sem critério de saída único e testável como as outras fases (é uma
fase de processo, não de domínio) — o critério adotado aqui foi navegar as 7 telas do MVP
(UX_AND_ASSISTANT_SPEC.md) contra o backend real, ponta a ponta, sem dado fabricado em nenhuma
delas.

## IMPLEMENTADO

- `frontend/` (workspace Next.js 16.3.5/Turbopack + React 19.2.8 + TypeScript strict + Tailwind,
  stack já definida em DEVELOPMENT.md/SYSTEM_ARCHITECTURE.md — **retomada por pedido explícito do
  usuário**, ver DECISÕES).
- **Fronteira de segurança**: o navegador nunca fala com o FastAPI diretamente. Todo dado vem de
  Server Components (`lib/api.ts` → `apiFetch`, roda só no servidor, `import "server-only"`) ou de
  Route Handlers (`app/api/*`) para ações do usuário. O access token (15 min) e o refresh token
  (30 dias, rotacionado a cada uso — nunca reaproveitável, ver `core/auth`) vivem só em cookies
  httpOnly (`lib/session.ts`), nunca expostos ao JS do cliente — elimina roubo de token via XSS e a
  necessidade de CORS no backend (mesma origem sempre).
- `lib/api.ts`: `apiFetch()` injeta o Bearer token, tenta refresh uma vez em 401 e propaga
  `SessionExpiredError` se o refresh também falhar; `pageFetch()` (adicionada durante esta fase,
  ver PROBLEMAS) é a mesma coisa para Server Components de página, mas troca o throw por
  `redirect("/login")` do próprio Next.
- `lib/types.ts`: tipos espelhando 1:1 os modelos de resposta do backend (Opportunity, Tender,
  TenderItem, Requirement, Analysis/Finding/Evidence, CompanyProfile, Certificate, Attestation,
  AssistantAction/Message, Alert etc.) — nenhum tipo inventado além do que a API já devolve.
- 7 telas de navegação (UX_AND_ASSISTANT_SPEC.md): Visão Geral (`/`), Radar (`/radar` + filtro por
  status), detalhe de oportunidade (`/radar/[id]` — edital, itens, dossiê/findings com evidência,
  requisitos por categoria), Análises (`/analises`), Minha Empresa (`/minha-empresa` — CNPJ +
  perfil comercial), Documentos (`/documentos` — certidões/atestados), Inteligência Competitiva e
  Jurídico como **estados "ainda não implementado" honestos** (ver DECISÕES), nunca omitidos do
  menu nem preenchidos com dado fake.
- Botão flutuante do Assistente (`components/AssistantButton.tsx`) — não é item de menu (conforme
  spec), extrai `opportunity_id` da URL atual via regex e oferece só as ações que fazem sentido
  para a tela (`missing_requirements`/`understand_tender` em `/radar/[id]`, nada fora dali).
- `api/v1/tenders.py` (`GET /{tender_id}`) e `domains/procurement/opportunities/service.py` +
  `api/v1/opportunities.py` (`get_opportunity()` / `GET /{opportunity_id}`) — **dois endpoints
  novos no backend**, adicionados durante esta fase porque o frontend não tinha como renderizar
  edital/oportunidade real sem eles (só existiam list/sub-resource antes). Ver DECISÕES sobre por
  que isso é tratado como parte da Fase 11 e não uma fase própria.

## AMBIENTE (setup real)

- Node.js/npm instalados via `winget install --id OpenJS.NodeJS.LTS` (v24.19.0/11.17.0) nesta
  máquina — não estava disponível antes desta fase.
- `preview_start` (spawner de processo do ambiente de dev) não enxerga o PATH atualizado pelo
  winget mesmo após `SetEnvironmentVariable(..., "User")` explícito — contornado com
  `frontend/run-dev.cmd`, que prefixa o PATH com o diretório do Node.js antes de chamar
  `npm run dev`, referenciado em `.claude/launch.json`.
- Backend (`uv run uvicorn ...`) e frontend (`run-dev.cmd`) rodando simultaneamente via
  `preview_start` durante toda a verificação.

## TESTADO

**Backend** (endpoints novos + regressão):
- `ruff check`, `mypy .` (171 arquivos), `lint-imports` — limpos.
- `pytest -q` — **184 testes passando, três rodadas consecutivas** (58s/58s/97s) — 5 testes novos
  (`test_get_tender_requires_authentication`, `test_get_tender_returns_404_for_unknown_tender`,
  `test_get_tender_returns_stored_fields`, `test_get_single_opportunity_returns_decomposed_match`,
  `test_get_single_opportunity_returns_404_for_unknown_id`), zero regressão nos 179 existentes.

**Frontend**:
- `npx next build` — TypeScript strict limpo, 16 rotas geradas corretamente (nenhum erro de tipo,
  nenhuma rota conflitante).
- `npx eslint .` — limpo.
- **Verificação ao vivo no navegador** (servidor real, backend real, nenhum mock): cadastro de
  conta real (`Empresa Teste LTDA`) → login → as 7 telas de navegação + detalhe de oportunidade +
  botão do Assistente, todas renderizando contra o backend real com estados vazios honestos (sem
  oportunidade/edital ainda neste ambiente — ver PENDÊNCIAS); logout funcional; acesso não
  autenticado a rota protegida (`/radar`) redireciona corretamente (307) para `/login`; nenhum
  erro de console nem de servidor na versão final.

## PROBLEMAS (encontrados e corrigidos durante esta fase)

1. **Fundo escuro no `/signup`**: `globals.css` gerado pelo scaffold trazia
   `@media (prefers-color-scheme: dark) { :root { --background: #0a0a0a } } body { background:
   var(--background) }`, que sobrepunha a classe Tailwind `bg-slate-50` do `<body>` porque o
   esquema de cor do navegador de teste é escuro. Corrigido removendo essas regras de
   `globals.css` (deixando só o import do Tailwind + variáveis de fonte) e movendo `font-sans`
   para a `className` do `<body>` em `layout.tsx`.
2. **Corrida de renderização entre `layout.tsx` e cada `page.tsx`** (achado real, não cosmético):
   Next.js renderiza layout e página filha como Server Components concorrentes — mesmo quando o
   layout dá `redirect("/login")` por falta de sessão (e o usuário recebe o 307 correto), a página
   filha já havia começado sua própria chamada `apiFetch`, que lança `SessionExpiredError` sem
   captura e aparece como erro de servidor não tratado no log, apesar do comportamento correto
   para quem usa o produto. A primeira tentativa de correção (checar o cookie antes de chamar
   `apiFetch` no layout) só resolveu o erro *do próprio layout* — as 6 páginas que chamam
   `apiFetch` diretamente (`/`, `/radar`, `/radar/[id]`, `/analises`, `/minha-empresa`,
   `/documentos`) continuavam gerando a mesma corrida, confirmado navegando para `/radar`
   deslogado e inspecionando `preview_logs` antes de declarar a fase pronta. Correção definitiva:
   `pageFetch()` (ver IMPLEMENTADO) captura `SessionExpiredError` e chama `redirect()` do próprio
   Next em vez de deixar o erro propagar sem captura — `redirect()` é o mecanismo abençoado pelo
   framework para abortar uma renderização e navegar, e não aparece como erro no log, diferente do
   throw genérico. Aplicado a todas as 6 páginas + layout. **Cuidado que ficou registrado no
   código**: os sub-fetches N+1 (edital por oportunidade) que já tinham `.catch(() => null)`
   continuam usando `apiFetch` puro, não `pageFetch` — se usassem `pageFetch`, o `redirect()`
   lançado dentro do `.catch(() => null)` seria engolido silenciosamente (viraria "edital
   indisponível" em vez de navegar para `/login`), trocando uma falha de sessão por dado
   silenciosamente incompleto.

## RISCOS

- **Nenhum dado populado neste ambiente ainda** — toda a verificação ao vivo rodou contra estados
  vazios (nenhuma oportunidade, nenhum edital, nenhuma certidão). As telas com dado populado
  (tabela de oportunidades no Radar, itens/requisitos/findings no detalhe, `StatusSelector`,
  `GenerateAnalysisButton`) não foram visualmente confirmadas ainda — só o caminho de
  renderização vazio. Precisa de um ciclo de ingestão real (Fase 3) rodando para gerar dado de
  verdade e then re-verificar essas telas.
- **Sem suite de teste automatizado no frontend** (nenhum Playwright/Vitest/Testing Library) —
  toda a verificação desta fase foi manual, ao vivo, no navegador. Diferente do backend (que tem
  184 testes automatizados rodando 3x), uma regressão futura no frontend só seria pega em
  verificação manual repetida.
- **Fluxo do Assistente não exercitado ao vivo pela UI com um provider de LLM real configurado**
  (nenhuma credencial configurada em nenhum ambiente ainda, ver PENDÊNCIAS da Fase 9) — o botão
  abre e mostra o contexto certo, mas uma ação de verdade (`missing_requirements` etc.) contra
  `LLM_PROVIDER` configurado não foi testada pela UI, só no backend isoladamente (Fase 9).
- **CNPJ enrichment (`CnpjForm`) não exercitado ao vivo** — precisa de um CNPJ real e da API
  externa de enriquecimento respondendo; não testado nesta fase.
- Layout mobile/responsivo não testado (só viewport desktop 1280×720 usado na verificação).

## DECISÕES

- **Retomar a Fase 11 agora, por pedido explícito do usuário**: "a stack pro front já foi definida
  na documentação, pode implementar também não precisa ficar se segurando não" — revertendo o
  adiamento registrado na Fase 9/10 ("frontend continua fora do escopo").
  [[FASE_9_REPORT.md]]
- **Regra de dado real reforçada em código, não só verbalmente**: pedido explícito do usuário —
  "dado mockado depois de testado quando for pra manter em produção não pode aparecer tem que
  estar em dados reais" — operacionalizado como: (1) N+1 fetch de edital por oportunidade em vez
  de fabricar um agregado (comentado no código como decisão deliberada); (2) telas de
  Inteligência Competitiva e Jurídico como "ainda não implementado" explícito, citando a fase que
  bloqueia cada uma, em vez de dado fake ou tela omitida do menu; (3) se um sub-fetch falha, o
  item some da lista em vez de mostrar um valor inventado.
- **Dois endpoints de backend tratados como parte desta fase, não uma fase própria**: `GET
  /v1/tenders/{id}` e `GET /v1/opportunities/{id}` só existem porque o frontend não tinha como
  buscar o registro individual (só list/sub-resource antes) — mesmo padrão de fases anteriores que
  documentam correção cross-fase quando um retrofit pequeno e bem contido é necessário para a fase
  atual funcionar de verdade.
- **`pageFetch()` como wrapper dedicado a Server Component de página, não uma mudança de
  comportamento em `apiFetch()`**: `apiFetch()` é usado também pelos Route Handlers
  (`app/api/proxy`, `app/api/assistant/actions`), que precisam do throw (`SessionExpiredError`)
  para devolver 401 em JSON — não fazem sentido com `redirect()` do Next, que só funciona dentro
  do pipeline de renderização de página.

## PENDÊNCIAS

1. Popular dado real (rodar ingestão da Fase 3 contra o tenant de teste) e re-verificar Radar,
   detalhe de oportunidade, Análises e Documentos com listas não vazias.
2. Testar o fluxo do Assistente pela UI com um provider de LLM real configurado (mesma pendência
   já registrada na Fase 9, agora também do lado do frontend).
3. Testar `CnpjForm` com um CNPJ real.
4. Escrever teste automatizado de frontend (mínimo: smoke test e2e das 7 telas + fluxo de
   auth) — hoje a única cobertura é a verificação manual desta fase.
5. Testar layout em viewport mobile/tablet.
6. Validar o ciclo completo de refresh de token em tempo real (access token expira em 15 min,
   comportamento de refresh automático só foi validado por leitura de código, não observado ao
   vivo esperando a expiração).

## PRÓXIMA FASE

Fases 12/13 continuam bloqueadas pelo mesmo motivo já registrado (base jurídica curada real e
cliente piloto real, nenhum dos dois disponível). O frontend pode seguir evoluindo em paralelo
(conforme a própria nota da Fase 11 no roadmap) assim que houver dado real populado — ou os
próximos passos backend-only seguem viáveis: Fase 14 (Feedback + Learning) ou Fase 15
(Observability + Security hardening).
