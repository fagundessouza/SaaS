# Relatório de Checkpoint — Fase 7 (Opportunity Engine)

Ver critério de saída em [IMPLEMENTATION_ROADMAP.md](../IMPLEMENTATION_ROADMAP.md#fase-7--opportunity-engine-filtro-determinístico--matching-semântico):
"taxa de falso positivo/negativo validada manualmente contra um conjunto de editais conhecidos de
um cliente piloto real."

**Status honesto do critério de saída: parcialmente atendido.** A taxa de falso positivo/negativo
foi medida manualmente contra 100 editais reais do PNCP e três perfis de empresa plausíveis (ver
AMBIENTE) — mas **não contra o conjunto de um cliente piloto real**, que não existe ainda. Os
números abaixo são reais e reprodutíveis; a validação com cliente piloto fica como pendência
bloqueante para declarar o "Marco de MVP interno" do roadmap como comercialmente validado.

## IMPLEMENTADO

- `domains/procurement/opportunities/models.py`: `Opportunity` (TENANT, RLS) com o ciclo de vida
  do DOMAIN_MODEL (`DISCOVERED → UNDER_REVIEW → QUALIFIED → PURSUING → SUBMITTED → WON | LOST |
  WITHDRAWN`), `assigned_to_user_id`, e `OpportunityMatch` (TENANT, RLS) com `compatibility` e
  `confidence` decompostos por critério.
- `domains/procurement/opportunities/matching.py`: o funil, na ordem exigida pela mitigação do
  risco 5 da análise crítica (filtro determinístico antes de qualquer IA):
  1. **Região** (regra): UF do edital contra as UFs declaradas. Descarta aqui, sem embedding.
     Lista vazia = sem restrição (nunca "não aceita nenhuma" — um perfil novo não pode ter o
     radar zerado).
  2. **Palavra-chave** (regra): termo declarado dentro do objeto, normalizado (minúsculas, sem
     acento). Se bate, é match com confiança 1.0 e o embedding **não roda**.
  3. **Semântico** (IA/embeddings), só quando 1 passou e 2 não bateu: similaridade de cosseno
     entre o objeto e cada produto/serviço declarado, contra um limiar calibrado.
- `domains/procurement/opportunities/service.py`: criação idempotente de Opportunity +
  OpportunityMatch + evento `OpportunityMatched` na mesma transação (outbox, ADR-0004), e as
  transições de ciclo de vida validadas no domínio (`_ALLOWED_TRANSITIONS`), não só na API.
- `domains/procurement/opportunities/jobs.py`: `run_opportunity_matching_job` — varre tenants
  matcháveis (TRIAL e ACTIVE) contra os editais da janela de lookback, alternando
  `system_session` (Tender é GLOBAL) e `tenant_session` (Opportunity é TENANT).
  Registrado no worker em `minute={15,45}`, defasado 15min da ingestão.
- `api/v1/opportunities.py`: `GET /v1/opportunities` (com filtro `status`/`only_active`),
  `PATCH /{id}/status` (409 em transição inválida), `PATCH /{id}/assignee`.
- `api/v1/companies.py`: `PUT /v1/company-profile/commercial` — a porta de entrada de
  regiões/produtos/serviços, sem a qual o radar fica vazio por construção.
- Métricas novas: `opportunities_created_total`, `opportunity_match_evaluations_total`
  (por desfecho — a razão rejected/matched é o sinal de que o funil está barrando volume antes
  do custo de IA).
- **Correções retroativas** (ver PROBLEMAS 1 e 2): `Tender.uf`/`Tender.municipio` (com backfill
  do `raw_payload` já ingerido) e `CompanyProfile.products`/`services`.

## AMBIENTE (calibração real, não escolha no abstrato)

O limiar semântico foi calibrado contra **100 objetos de edital reais** coletados ao vivo da API
do PNCP (modalidades Pregão Eletrônico e Dispensa, janela de 10 dias), com três perfis de empresa
plausíveis, julgando manualmente cada resultado.

**Medição do limiar** (precisão dos aprovados, por perfil):

| Limiar | Perfil TI | Perfil hospitalar |
|---|---|---|
| 0.50 | 54% (aprova "engenharia ambiental", "instrumentais odontológicos") | 88% |
| **0.55** | **71%** | **86%** |
| 0.65 | 100%, mas recall cai a ~29% | — |

**Descoberta adicional — preâmbulo formulaico dilui o embedding.** Editais brasileiros quase nunca
começam pelo objeto real: começam por "Registro de preços para eventual e futura aquisição de…",
"Contratação de empresa especializada para prestação de serviços de…". Esse texto é praticamente
constante entre editais e domina o vetor da frase. Medido:

| Par | Score bruto | Sem preâmbulo |
|---|---|---|
| "Registro de preços para eventual aquisição de material de expediente" × "material de escritório" | 0.434 | **0.679** |
| "Contratação de empresa especializada para prestação de serviços de TI" × "serviço de tecnologia da informação" | 0.741 | **0.972** |
| "Aquisição de gêneros alimentícios" × "material de escritório" (negativo) | 0.132 | 0.178 |

A limpeza do preâmbulo entrou na implementação (`_strip_object_preamble`), aplicada **apenas** ao
caminho semântico — o filtro literal usa o texto completo, onde o preâmbulo não atrapalha.

**Medição final do funil completo** (300 avaliações = 100 editais × 3 perfis, limiar 0.55 +
limpeza de preâmbulo, julgamento manual de cada aprovado):

| Perfil | Aprovados | Verdadeiros positivos | Falsos positivos / duvidosos | Precisão |
|---|---|---|---|---|
| Hospitalar | 8 | 7 | 1 | ~87% |
| TI | 8 | 5 | 3 (engenharia ambiental, segurança eletrônica, telefonia) | ~63% |
| Papelaria | 2 | 0 | 2 | 0% |

Falsos negativos identificados no perfil hospitalar (relevantes que ficaram abaixo do limiar):
"TUBOS E FRASCOS PARA AMOSTRA BIOLÓGICA" (0.430), "Saco para transporte de órgãos e equipo de
perfusão" (0.417), "abaixador de língua" (0.370), "instrumentais odontológicos" (0.356) — recall
estimado ~64%.

O perfil "papelaria" merece destaque honesto: **a amostra não continha nenhum edital de material
de escritório** (o maior score do ramo foi 0.551), então não havia verdadeiro positivo possível —
e o funil ainda assim aprovou 2 itens (ruído puro). É o pior caso medido e está registrado como
tal, não omitido.

Ambiente: Docker Desktop precisou ser iniciado manualmente; `uv sync` já estava resolvido da
Fase 6. O override local de portas criado na Fase 6 (conflito com túnel SSH de outro projeto)
continua necessário neste computador.

## TESTADO

- `ruff`, `mypy --strict`, `import-linter` — limpos (127 arquivos-fonte).
- Migration (`opportunities`, `opportunity_matches`, colunas novas, RLS, backfill)
  `upgrade`/`downgrade`/`upgrade` — reversível. O `DROP TYPE opportunity_status` no downgrade
  não é decorativo: sem ele, o segundo `upgrade` falha com "type already exists" (o
  `drop_table` não remove o enum criado implicitamente).
- **Backfill validado com payload real**, não só sintético: inseri um Tender com
  `raw_payload` real do PNCP (`unidadeOrgao.ufSigla`), rodei `downgrade` + `upgrade` e confirmei
  `uf='RN'`, `municipio='Campo Grande'` preenchidos a partir do JSONB.
- `pytest` — **116/116 testes passando** (86 herdados + 30 novos), rodados **três vezes
  seguidas** sem resetar Postgres/Qdrant.
  - `tests/unit/test_opportunity_matching.py` (11): ordem do funil provada por construção — um
    provider de embedding que **explode se chamado** garante que região/palavra-chave decidem
    antes de qualquer IA; normalização de acento/caixa; região vazia não filtra; UF desconhecida
    com região declarada rejeita; perfil sem produtos nunca casa; termo curto não conta como
    palavra-chave; sinônimo real capturado pelo semântico; objeto não relacionado rejeitado;
    limpeza de preâmbulo registrada na evidência; e um teste de invariante de produto: a
    avaliação **nunca** expõe score único agregado.
  - `tests/integration/test_opportunity_matching_job.py` (7): cria Opportunity + Match
    decomposto + evento; idempotente entre rodadas; pula edital de outra região, tenant sem
    perfil, tenant suspenso, perfil sem produtos; perfil sem região casa qualquer UF.
  - `tests/integration/test_opportunities_api.py` (9): auth; listagem com match decomposto e sem
    score agregado; transição válida; transição inválida → 409; status terminal não reabre;
    filtro `only_active`; atribuição/desatribuição; 404 em id desconhecido; endpoint de perfil
    comercial normalizando UF e descartando termo vazio.
  - `tests/security/test_opportunity_isolation.py` (3): Opportunity e OpportunityMatch de um
    tenant invisíveis a outro (com query que **não** filtra `tenant_id`, provando o RLS); o mesmo
    Tender gerando uma Opportunity independente por tenant; token de outro tenant recebendo 404
    ao tentar mudar status.

## PROBLEMAS (encontrados e corrigidos durante esta fase)

1. **`Tender` não tinha UF — o filtro de região era impossível.** O dado existia desde a Fase 3,
   mas apenas dentro de `TenderVersion.raw_payload` (JSONB), inutilizável para filtro indexado.
   Corrigido com `Tender.uf`/`municipio` (migration aditiva) **e backfill do acervo já ingerido**
   — sem o backfill, o Opportunity Engine nasceria cego para todos os editais anteriores à
   migration, porque UF nula com perfil que declara região é tratada como não compatível.
   Mesmo tipo de correção retroativa que a Fase 5 fez com `page_texts`.
2. **`CompanyProfile` não tinha produtos/serviços.** Previstos no DOMAIN_MODEL desde a Fase 0,
   mas nunca materializados — a Fase 7 é o primeiro consumidor real. Viraram coluna + endpoint;
   sem eles não há o que casar com o objeto do edital.
3. **CNAE não é utilizável para matching contra edital do PNCP.** O roadmap previa "CNAE, região,
   palavra-chave", mas **o edital do PNCP não traz CNAE** — o `CompanyProfile` tem CNAE (do
   enriquecimento por CNPJ da Fase 2), o edital não tem contra o que comparar. Verificado no
   payload real da API. O filtro determinístico ficou sendo região + palavra-chave; CNAE segue
   útil para outras finalidades (habilitação, relatórios), não para este matching. Registrado
   aqui porque é uma divergência real entre o roadmap e o que a fonte de dados permite, não uma
   simplificação de conveniência.
4. **O caso canônico de sinônimo ficava abaixo do limiar.** "Material de expediente" (termo
   oficial) × "material de escritório" dava 0.512 com limiar 0.55 — ou seja, o caso que mais
   justifica a existência da etapa de IA falhava. A investigação levou à descoberta do preâmbulo
   formulaico (ver AMBIENTE) e à sua remoção, que levou o mesmo par a 0.679. A alternativa fácil
   (baixar o limiar para 0.50) foi rejeitada porque derrubava a precisão do perfil TI para 54%.
5. **Poluição de teste entre execuções — 4ª ocorrência deste padrão no projeto** (depois de
   e-mail/CNPJ nas Fases 2/3, texto de documento na Fase 4 e Qdrant na Fase 5). Aqui a causa é
   estrutural e nova: este job varre **todo** tenant ativo contra **todo** Tender recente, e o
   Postgres de teste não é limpo entre rodadas — então o tenant de um teste inevitavelmente casa
   também com tenders deixados por outros testes (vários usam "material de escritório"). As
   asserções que contavam linhas do tenant (`len(opportunities) == 1`) passavam isoladas e
   falhavam na suíte completa. Corrigido fazendo **toda** asserção sobre o tender específico
   criado pelo próprio teste, com a razão documentada no topo do módulo de teste.

## RISCOS

- **Nenhum limiar único separa bem todos os ramos, e isso foi medido, não suposto.** No conjunto
  de pares de controle, a margem entre o pior verdadeiro positivo e o melhor falso positivo é
  **negativa** (-0.015 no texto bruto, -0.053 após a limpeza de preâmbulo): existe sobreposição
  real. A limpeza melhora muito os casos dominados por preâmbulo, mas também eleva alguns
  negativos adjacentes. A consequência prática é a diferença de precisão entre perfis (87%
  hospitalar vs. 63% TI): vocabulário de ramo amplo tem mais vizinhos semânticos. Limiar por
  ramo/perfil é o endurecimento natural, e está em PENDÊNCIAS — não é um detalhe de ajuste fino.
- **A escolha foi precisão sobre recall, e é uma decisão de produto, não técnica.** Com 0.55,
  ~36% dos editais relevantes do perfil hospitalar não entram no radar. O raciocínio: no Radar
  (alto volume, triagem), falso positivo corrói a confiança no produto inteiro, enquanto falso
  negativo é parcialmente recuperável (a busca semântica da Fase 5 continua disponível, e o
  edital permanece no sistema). Se a validação com cliente piloto mostrar que perder oportunidade
  dói mais que ver ruído, o limiar desce — é um setting, não constante.
- **Custo do job é O(tenants × editais) e já é observável.** A suíte de testes passou de ~27s
  para ~105-153s, crescendo a cada rodada conforme o banco de teste acumula tenants e tenders —
  o job reavalia tudo dentro da janela de lookback. Em volume de produção (milhares de editais/dia
  × N tenants) isso exige particionamento/paginação e provavelmente disparo por evento
  (`TenderCreated`) em vez de varredura periódica. Não antecipado agora, mas o sinal de que
  vai doer já existe e está medido.
- **Falso positivo em perfil sem oportunidade real no período**: no perfil "papelaria", sem
  nenhum edital do ramo na amostra, o funil ainda aprovou 2 itens. Um tenant de nicho estreito
  pode receber um radar composto só de ruído numa semana fraca — o que é pior que radar vazio,
  porque parece resultado.
- `Requirement`/`TenderItem` (Fase 6) **não** participam do matching: só o `objeto` do edital é
  comparado. Casar contra a descrição dos itens provavelmente melhoraria muito a precisão
  (item é específico, objeto é genérico), mas multiplicaria o custo de embedding por edital.
  Candidato claro a próxima iteração, com medição.
- O evento `OpportunityStatusChanged` é publicado mas **não tem consumidor** — não está no
  catálogo de `EVENT_AND_NOTIFICATION_ARCHITECTURE.md`. Foi adicionado por consistência de
  auditoria (toda transição de status relevante gera evento, conforme DOMAIN_MODEL), mas é
  dívida se nunca for consumido.
- `test_retrieval.py` (Fase 5) falhou **uma vez** durante esta fase, no cenário de Qdrant muito
  acumulado (o teste busca o chunk recém-indexado dentro do top-20 de relevância). Não é
  regressão desta fase — é o risco de poluição já documentado na Fase 5, agravado pelo volume
  que as rodadas repetidas acumulam. Passou nas três rodadas finais, mas o teste segue frágil.

## DECISÕES

- **`OpportunityMatch` tem `tenant_id` próprio e RLS própria**, apesar de o DOMAIN_MODEL a
  classificar como DERIVADA (que "herda o isolamento do agregado pai"). Defesa em profundidade,
  conforme SECURITY_MODEL ("`tenant_id` obrigatório em toda tabela TENANT" + RLS como segunda
  barreira): um bug de join não vaza match entre tenants. O custo é uma coluna redundante; o
  benefício é que o banco recusa a linha mesmo com query errada.
- **Nenhum score agregado, em nenhuma camada** — nem coluna, nem campo de API, nem payload de
  evento. `compatibility` e `confidence` são JSONB decompostos por critério, com `confidence`
  significando confiança **da técnica** (determinística = 1.0, semântica = cosseno), nunca
  probabilidade de ganhar a licitação. Há um teste dedicado a esse invariante, porque ele é de
  produto (item 5 da tabela de ambiguidades e a linha "Score único de compatibilidade sem
  decomposição = risco de Fake AI" da análise crítica), não de implementação.
- **Região vazia = sem restrição** (vê tudo), e **perfil sem produtos/serviços = nenhum match**.
  Assimetria deliberada: no primeiro caso o silêncio do usuário não deve zerar o radar; no
  segundo, sem saber o que a empresa vende, "todo edital do estado" seria ruído apresentado como
  resultado.
- **TRIAL conta como tenant matchável.** Quem está avaliando o produto é justamente quem mais
  precisa ver o radar funcionando. Tenant suspenso/cancelado não gera Opportunity nova, mas as
  existentes não são apagadas.
- **Limiar como setting, não constante** — porque a medição mostrou que o valor ideal varia por
  ramo, então codificá-lo fixo seria fingir uma precisão que os dados não sustentam.
- **Job periódico, não disparado por evento `TenderCreated`.** Mais simples e resiliente para o
  volume de um piloto (um ciclo que falha é recuperado no seguinte, sem fila de eventos
  pendentes). Revisável quando o custo O(tenants × editais) apertar — ver RISCOS.
- **Limpeza de preâmbulo só no caminho semântico**, nunca no filtro literal: busca de substring
  não é diluída por contexto, então remover texto ali só criaria risco de perder um termo que
  aparece dentro do preâmbulo.

## PENDÊNCIAS

1. **Validação com cliente piloto real** — o critério de saída literal desta fase. Os números
   medidos aqui usam perfis plausíveis inventados por mim; um cliente real tem vocabulário
   próprio, e a taxa de falso positivo/negativo que importa é a dele. Bloqueia declarar o "Marco
   de MVP interno" como comercialmente validado.
2. **Limiar por ramo/perfil** (ou por termo), em vez de global — a margem negativa medida mostra
   que um número único é estruturalmente insuficiente.
3. **Casar contra `TenderItem`/`Requirement`**, não só o objeto do edital, medindo o ganho de
   precisão contra o custo adicional de embedding.
4. **Faixa de valor no perfil** (`min`/`max`): o filtro determinístico previsto na análise crítica
   incluía valor, mas o `CompanyProfile` não tem essa dimensão declarada e `Tender.valor_estimado`
   é frequentemente sigiloso ou nulo — precisa desenho próprio, não foi improvisado aqui.
5. **UX de onboarding cobrando produtos/serviços**: hoje um tenant que não preenche o perfil
   comercial tem radar vazio e nenhuma explicação na interface.
6. **Disparo por evento + particionamento do job** quando o volume exigir (ver RISCOS).

## PRÓXIMA FASE

Fase 8 — Analysis Engine (escopo mínimo: `Finding` + `Evidence`, sem Legal/Pricing): dossiê de
uma oportunidade cruzando os `Requirement` extraídos na Fase 6 com os `Certificate`/`Attestation`
do tenant, apontando pendências documentais rastreáveis ao texto original. Ver
[IMPLEMENTATION_ROADMAP.md](../IMPLEMENTATION_ROADMAP.md#fase-8--analysis-engine-escopo-mínimo-findings--evidence-sem-legalpricing-ainda)
e ADR-0006 (nenhuma conclusão sem evidência rastreável).
