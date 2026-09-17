# Análise Crítica da Especificação — Fase 0

> Este documento é o entregável central da Fase 0. Ele não reescreve o prompt mestre — ele o
> questiona. Onde a especificação original é aceita, é porque resistiu à crítica abaixo. Onde não
> resistiu, isso está marcado explicitamente como **decisão em aberto** ou **ADR necessário**, e os
> demais documentos desta pasta já refletem a versão revisada, não a original.

## 1. Contradição estrutural: "MicroSaaS" vs. o que está especificado

**Problema.** O prompt chama o produto de "MicroSaaS" mas especifica, em detalhe, uma plataforma de
dados de nível enterprise: motor de ingestão multi-fonte com OCR/vision, RAG com camada global e
por tenant, motor jurídico com versionamento normativo, motor de precificação determinístico,
motor de risco, engine de eventos com múltiplos webhooks, notificações multicanal, agentes com MCP,
observabilidade com p50/p90/p95/p99 e cost governance por feature, e 16 fases de roadmap.

**Impacto.** Se tratado como um único backlog sequencial, isso é um projeto de 18–30 meses antes do
primeiro cliente pagante ver valor. Isso mata o produto antes de existir: não há como validar
product-market fit sem receita ou uso real por tanto tempo, e é o oposto do espírito "micro" do
SaaS.

**Risco.** Construir a "máquina perfeita" e nunca chegar ao mercado. Este é o risco #1 do projeto,
mais alto que qualquer risco técnico.

**Opções.**
1. Reduzir o escopo do produto (abandonar partes da visão). Rejeitado — o usuário foi explícito:
   "não reduza a visão simplesmente para facilitar a implementação".
2. Manter a visão completa como **arquitetura-alvo (North Star)**, mas fatiar o roadmap em um
   **MVP vertical fino** que atravessa todas as camadas com escopo mínimo em cada uma, e ir
   engordando cada camada em paralelo com uso real e feedback de clientes-piloto.
3. Construir tudo "certo" desde a Fase 1, sem clientes piloto até a Fase 10+.

**Recomendação.** Opção 2. Isto **não** é reduzir a visão — é sequenciar. A arquitetura (contratos,
domínios, isolamento multi-tenant, separação global/tenant knowledge, motor de regras vs. IA) é
definida por completo agora, na Fase 0. A **implementação** de cada camada começa rasa (ex.: só
fonte PNCP, só um provider LLM, sem OCR de visão computacional no dia 1, sem WhatsApp no dia 1) e
aprofunda por fases subsequentes, sem jamais violar os contratos definidos aqui. Isso é o
princípio de "Não-Reset" (seção 36 do prompt) aplicado ao roadmap. Ver
[IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md) para o corte de MVP proposto e
[ADR-0001](adr/0001-monorepo-modular-monolith.md).

## 2. PNCP muda o problema de ingestão

**Problema.** A especificação trata "ingestão multi-portal" (PNCP, Compras.gov.br, SISLOG, portais
estaduais e municipais) como um conjunto simétrico de fontes igualmente prioritárias.

**Realidade de domínio.** Desde a Lei 14.133/2021 e a obrigatoriedade de publicação no PNCP (Portal
Nacional de Contratações Públicas), o PNCP é o agregador nacional oficial e possui API pública
(dados abertos) para praticamente toda contratação pública sujeita à lei — federal, estadual e
municipal. Compras.gov.br é, para a maior parte dos casos, uma interface sobre dados que também
fluem para o PNCP. Portais estaduais/municipais residuais (contratações fora do PNCP, sistemas
legados, pregões antigos ainda sob a Lei 8.666/93 em contratos de transição) existem, mas são cauda
longa, não o corpo principal.

**Impacto se ignorado.** Construir N conectores/scrapers frágeis para portais estaduais/municipais
antes de esgotar o valor do PNCP é desperdício de esforço de engenharia e superfície de manutenção
desnecessária (scrapers de HTML quebram constantemente — ver seção 10J do prompt, que já reconhece
isso para *validação de certidões* mas não foi aplicado ao raciocínio de ingestão de editais).

**Decisão.** PNCP é a fonte canônica e prioritária (ver [ADR-0009](adr/0009-pncp-fonte-canonica.md)).
Outras fontes entram via o mesmo `Connector` interface, mas como conectores de prioridade 2,
adicionados sob demanda de clientes-piloto que efetivamente contratam com órgãos fora do PNCP — não
especulativamente.

## 3. n8n como espinha dorsal do pipeline crítico é uma escolha arriscada

**Problema.** A seção 5 lista n8n em "Automação/integrações" e a seção 9/10 desenham pipelines de
ingestão e eventos que soam como fluxos de n8n. Se o pipeline de ingestão → normalização →
matching → análise → notificação (o núcleo do valor do produto) for implementado como workflows
visuais no n8n, isso tem consequências sérias:

- Testabilidade: workflows visuais são difíceis de cobrir com testes automatizados de regressão
  (seção 26 exige testes de ingestion, matching, RAG, eventos — praticamente impossível de fazer
  bem com qualidade de engenharia dentro do n8n).
- Versionamento e review: diffs de workflow JSON não são revisáveis como código em PR.
- Isolamento multi-tenant dentro de um workflow n8n compartilhado é uma fonte provável de bugs de
  vazamento entre tenants (risco #1 de todo o produto, ver seção 5).
- Observabilidade fina (p95, custo por chamada, tokens) é mais difícil de instrumentar dentro de
  nós de n8n do que em código instrumentado nativamente.

**Impacto.** Um bug de isolamento de tenant dentro de um workflow de automação de terceiros é um
incidente de confiança fatal para um SaaS B2B que lida com dados comerciais sensíveis
(preços, margens, estratégia).

**Decisão.** n8n é mantido no stack, mas com escopo restrito: automações auxiliares e não-críticas
(ex.: notificação interna para o time de suporte, sincronizações administrativas, glue de
marketing/onboarding). O pipeline de domínio (ingestão → matching → análise → dossiê →
notificação ao tenant) é implementado como código versionado no backend, orquestrado por fila de
jobs assíncrona (ver [ADR-0004](adr/0004-orquestracao-core-em-codigo.md)). Isso não contradiz a
seção 10 do prompt (o diagrama de pipeline nela é uma sequência lógica, não uma exigência de
ferramenta específica).

## 4. Inteligência jurídica é a maior superfície de risco de responsabilidade do produto

**Problema.** As seções 14 e 10G–10N já demonstram consciência do risco (linguagem cautelosa,
"possível restrição" em vez de "isso é ilegal"), o que é correto. Mas a arquitetura, se
mal-implementada, ainda pode:

- Fazer o modelo "lembrar" de jurisprudência a partir de conhecimento paramétrico (treino do LLM)
  em vez de recuperação de uma base curada e versionada — isto é uma fonte clássica de alucinação
  de citações jurídicas (número de processo, ementa, tribunal inventados) e é o tipo de erro que
  gera dano concreto (empresa deixa de recorrer, ou recorre com fundamento inexistente).
- Confundir "sugestão de impugnação/recurso" gerada por IA com aconselhamento jurídico — isso é
  reservado a advogado inscrito na OAB (Lei 8.906/94, art. 1º). O produto não pode se posicionar
  como substituto de assessoria jurídica.

**Decisão.** Toda saída do Legal Intelligence Layer é obrigatoriamente ancorada em evidência
recuperada (RAG sobre base jurídica curada e versionada — nunca resposta livre do LLM sobre
jurisprudência). Nenhuma citação de norma/acórdão/súmula é aceita sem `source_url` e
`document_version` rastreáveis. O produto se posiciona explicitamente como **ferramenta de apoio à
decisão**, não como assessoria jurídica — isso deve aparecer em termos de uso, disclaimers de UI, e
ser reforçado por um "human review gate" para qualquer saída classificada como
`requires_human_review` (ver [ADR-0006](adr/0006-legal-grounding-e-revisao-humana.md) e
[SECURITY_MODEL.md](SECURITY_MODEL.md), seção de responsabilidade de conteúdo).

## 5. Ambiguidades e contradições pontuais na especificação original

| # | Item | Ambiguidade/contradição | Resolução adotada |
|---|------|--------------------------|--------------------|
| 1 | Estrutura de pastas (seção 6) | Mistura `core/platform/domains/api` no mesmo `app/`, mas o frontend é Next.js separado — não fica claro se é monorepo ou polyrepo | Monorepo com backend (Python) e frontend (Next.js) como workspaces distintos. Ver [ADR-0001](adr/0001-monorepo-modular-monolith.md) |
| 2 | "Fase 0" deliverables (seção 31) | Lista 9 documentos + ADRs, mas seção 31 também pede "repository structure, development conventions, environment strategy, testing strategy" como itens "além disso", sem arquivo nomeado | Consolidados em [DEVELOPMENT.md](DEVELOPMENT.md) |
| 3 | Assinatura (seção 22) | Diz para não implementar gateway de pagamento antes da arquitetura estar definida, mas não define se `Plan`/`Entitlement` já nascem no schema desde a Fase 2 | `Plan`, `Subscription`, `Entitlement` entram no schema já na Fase 2 (multi-tenancy), mas sem integração de gateway real — enforcement de limites é feito no app, cobrança fica manual/planilha até haver validação comercial |
| 4 | WhatsApp (seção 19) | Proíbe depender de "grupo/comunidade" mas não escolhe entre API oficial (Meta Cloud API via BSP) e outras rotas | API oficial via BSP (Business Solution Provider) homologado, nunca automação não-oficial de WhatsApp pessoal — ver [ADR-0010](adr/0010-canal-whatsapp-oficial.md) |
| 5 | Score de compatibilidade/risco (seções 11, 10O) | Pede "nunca falsa precisão" mas não define o que torna um score legítimo | Um score numérico só é exibido se (a) resultar de uma fórmula documentada e determinística sobre features observáveis, ou (b) vier acompanhado, sempre, dos fatores que o compõem. Nunca um score é a única saída de um LLM sem decomposição visível |
| 6 | Reranking (seção 12/seção 27) | Pede componente "independente e substituível" mas também "usar reranking somente quando necessário" | Reranking é aplicado apenas no estágio de *Analysis* (quando o usuário abre uma oportunidade), nunca no *Radar* (listagem/triagem), que usa recuperação + regras determinísticas por ser um caminho de alto volume e baixa tolerância a latência/custo |
| 7 | Embeddings (seção 5) | "Preferencialmente compatível com BGE-M3", mas seção 24 diz "provider-agnostic" | Interface `EmbeddingProvider` abstrata desde o dia 1; implementação default self-hosted (família BGE-M3 ou equivalente multilíngue/PT-BR) mais um adapter de API externa como fallback/comparação, nunca acoplamento direto no domínio |

## 6. O que pode quebrar este sistema

Ordenado por severidade × probabilidade combinadas.

1. **Vazamento de dados entre tenants.** É o risco mais severo possível para este produto: os
   dados privados de uma empresa (custos, margens, atestados, estratégia) vazarem para outra via
   um filtro de tenant esquecido em uma query Qdrant, um cache Redis sem prefixo de tenant, ou um
   job assíncrono que carrega o contexto errado. Mitigação: isolamento de tenant é uma dimensão
   obrigatória e testada em toda camada de dados (ver [SECURITY_MODEL.md](SECURITY_MODEL.md)) e não
   uma responsabilidade de cada desenvolvedor lembrar caso a caso — deve ser aplicado
   estruturalmente (RLS no Postgres como *defesa em profundidade*, filtro de tenant obrigatório e
   não-opcional na camada de repositório para Qdrant/Redis/MinIO).
2. **Qualidade de OCR ruim virando "certeza" na saída da IA.** Um edital mal escaneado, extraído com
   baixa confiança, ainda assim gera uma resposta fluente e convincente do LLM. O usuário confia e
   toma uma decisão de negócio errada. Mitigação: `extraction_quality`/`LOW_EXTRACTION_CONFIDENCE`
   deve **bloquear** a geração de conclusões de alto risco (jurídico, preço, elegibilidade) até
   reprocessamento ou revisão humana — não é só um campo de metadado decorativo.
3. **Alucinação jurídica.** Já tratado no item 4 acima. Mitigação estrutural, não só de prompt.
4. **Fontes governamentais instáveis.** APIs do PNCP/Compras.gov.br podem ter indisponibilidade,
   mudança de schema sem aviso, ou paginação/rate limit inesperados. Se a ingestão falhar
   silenciosamente, tenants deixam de ver oportunidades reais sem qualquer sinal de erro — pior que
   uma falha visível. Mitigação: todo conector de ingestão emite métricas de saúde (linha de base
   esperada de volume por período) e alerta quando o volume de itens ingeridos cai abaixo de um
   limiar, não apenas quando o HTTP falha explicitamente.
5. **Explosão de custo de LLM em escala.** Volume nacional de novas contratações é da ordem de
   milhares/dia. Rodar análise LLM completa (compatibilidade + jurídico + preço + risco) em toda
   oportunidade nova, para todo tenant, sem gating, quebra a unit economics do produto rapidamente.
   Mitigação: pipeline em funil — filtro determinístico (CNAE/região/palavra-chave/valor) antes de
   qualquer chamada a LLM; Global Knowledge Layer deduplicando processamento pesado (OCR, parsing,
   chunking, embedding) entre tenants; reranking e geração completa só no momento em que o usuário
   (ou uma regra de "match forte") efetivamente pede a análise.
6. **Falta de idempotência em webhooks/eventos.** Reentrega de evento (comum em filas e webhooks)
   causando notificação duplicada, ou pior, uma ação de negócio disparada duas vezes. Mitigação:
   todo consumidor de evento é idempotente por `event_id`, com deduplicação registrada (ver
   [EVENT_AND_NOTIFICATION_ARCHITECTURE.md](EVENT_AND_NOTIFICATION_ARCHITECTURE.md)).
7. **Estagnação de conhecimento jurídico.** Se a base de normas/jurisprudência não for
   ativamente monitorada e versionada, o sistema começa a operar sobre lei revogada sem perceber —
   silenciosamente incorreto, o pior tipo de erro porque não se manifesta como falha visível.
   Mitigação: fontes jurídicas têm job de verificação periódica com alerta de staleness (ver
   `LegalSource.last_verified_at` em [DOMAIN_MODEL.md](DOMAIN_MODEL.md)).
8. **Dependência de scraping de páginas HTML instáveis para validação de certidões** (seção 10J já
   reconhece isso). Mitigação: adapter por fonte, com estado explícito `SOURCE_UNAVAILABLE`
   diferenciado de `NOT_FOUND`/`INVALID`, para não confundir "não consegui verificar" com
   "certidão inválida".
9. **Single point of failure em fluxos síncronos.** Se abrir o dashboard depender de uma chamada
   LLM síncrona, uma lentidão de provider de IA se torna uma indisponibilidade percebida da
   plataforma inteira. Mitigação: separação explícita SYNC/ASYNC desde o design de API (seção 10S),
   nunca um endpoint de leitura de UI aguardando geração de LLM em linha.

## 7. O que parece impressionante mas não gera valor real ("Fake AI")

Aplicando o teste da seção 29 ("o que a IA permite fazer aqui que uma busca tradicional não
faria?") a cada capacidade prevista:

| Capacidade | Veredito | Justificativa |
|---|---|---|
| Chat genérico "pergunte qualquer coisa sobre o edital" sem ações estruturadas | **Risco de Fake AI** | Um chat aberto sem contexto de tela nem ações sugeridas vira uma "busca ruim com passo extra". A seção 16 já corrige isso ao amarrar o assistente ao contexto da tela e a ações (`[Entender edital]`, `[O que está faltando?]`) — manter essa disciplina é o que separa valor real de vitrine |
| Score único de "compatibilidade" sem decomposição | **Risco de Fake AI** | Um número sem explicação é pior que nenhum número — cria falsa confiança. Só se justifica com breakdown visível (ver item 5 da tabela de ambiguidades) |
| Geração de texto jurídico "solto" (ex.: minuta de recurso completa sem citar as evidências linha a linha) | **Risco de Fake AI / risco legal** | Documento bonito e fluente, mas se não é rastreável a evidência real, é pior que não ter a feature — ver item 4 |
| Sumarização de edital em "resumo executivo" | **Valor real** | Uma busca tradicional não sintetiza objeto + prazo + valor + principais exigências em uma leitura; isso é economia de tempo genuína, mensurável e de baixo risco (é descritivo, não conclusivo) |
| Matching semântico de objeto do edital com produtos/serviços do tenant | **Valor real** | Busca por palavra-chave falha com sinônimos e reformulações comuns em editais (nomenclaturas diferentes para o mesmo item); embeddings capturam isso. É o núcleo de valor do Opportunity Engine |
| RAG para "por que essa oportunidade apareceu / não apareceu" (seção 25) | **Valor real** | Explicabilidade é um requisito de confiança do produto, não estética — sem isso o usuário não confia no radar e volta a fazer busca manual |
| Recuperação de jurisprudência relacionada a um requisito específico | **Valor real, condicionado** | Só é valor real se a base é curada/verificada (item 4); se depender de memória do LLM, é Fake AI com risco jurídico agravado |
| Análise de preço com "diagnóstico" (piso econômico vs. mercado vs. regra legal) separados | **Valor real** | O erro comum do mercado é uma "IA" dar um preço sugerido único e opaco; separar as três dimensões é diferenciação real e defensável |
| Agentes autônomos genéricos via MCP com acesso amplo | **Risco de Fake AI + risco de segurança** | "Ter agentes" não é feature — cada ferramenta exposta a um agente precisa justificar por que uma chamada de função determinística não resolveria com menos risco (seção 24 já exige permissões explícitas; reforçar aqui que "agente" não é sinônimo de "mais inteligente") |

## 8. O que falta para ser um produto comercialmente competitivo

A especificação é forte em inteligência analítica, mas fraca ou omissa em capacidades que
determinam se uma equipe de licitação realmente troca sua ferramenta atual pela nova:

1. **Geração de trabalho, não só análise.** Equipes de licitação passam a maior parte do tempo
   *preenchendo* — declarações padronizadas, planilhas de proposta, formulários de habilitação. Um
   produto que só diagnostica e não produz nenhum artefato de saída (rascunho de proposta,
   checklist preenchível, declaração pré-formatada com dados da empresa) resolve metade do
   problema. Recomenda-se adicionar, no roadmap pós-MVP, um **Document Generation Engine**
   alimentado pelo `CompanyProfile` e pelo `Dossiê da Oportunidade`.
2. **Colaboração em equipe.** O domínio modelado é single-user-per-decision (`Feedback`, `Decision`
   por usuário). Empresas reais decidem em equipe: alguém identifica, outro analisa preço, um
   terceiro aprova. Faltam: atribuição de oportunidade a um responsável, comentários internos,
   estado de workflow (`novo → em análise → aprovado para participar → participando → resultado`),
   e permissões por papel dentro do tenant (a seção 8 já prevê `Role`, mas o fluxo de trabalho em
   si não está modelado). Isso deveria entrar em `DOMAIN_MODEL.md` como parte do agregado
   `Opportunity`.
3. **Inteligência competitiva histórica.** `Competitor`/`CompetitorDocument` estão no modelo de
   domínio mas ausentes dos fluxos principais (seção 37). Histórico de quem venceu, com que preço,
   e taxa de vitória por órgão/modalidade é frequentemente o diferencial mais vendável de um
   produto de licitações — deveria ganhar um fluxo próprio, não ficar como entidade órfã.
4. **Enriquecimento automático de perfil no onboarding.** Cadastro manual de CNPJ/CNAEs/certidões é
   fricção que mata ativação. Preencher automaticamente a partir de CNPJ (Receita Federal e demais
   fontes públicas) no onboarding é tanto uma vantagem competitiva quanto uma redução real de
   fricção — deveria ser um requisito de UX explícito, não implícito em "cadastra empresa".
5. **Modelo de precificação do próprio SaaS.** A seção 22 modela a arquitetura de assinatura mas não
   define a métrica de cobrança (por usuário? por oportunidade monitorada? por análise gerada?).
   Dado que o custo variável dominante é IA/LLM por análise (seção 10T já pede isso), a métrica de
   cobrança deveria estar alinhada ao custo variável real (ex.: número de oportunidades
   ativas/monitoradas, não assentos), para não gerar tenants estruturalmente deficitários.
6. **Residência de dados e conformidade LGPD explícita como diferencial comercial**, não só como
   item de segurança interna — compradores B2B deste setor (frequentemente lidando com dados
   sensíveis de contratos públicos) perguntam isso na venda. Hospedagem em território nacional e
   política de retenção devem estar documentadas e citáveis comercialmente.
7. **Integração de saída** (não só de entrada): exportar dossiês/documentos para os sistemas que a
   empresa já usa (ERP, planilhas, ou sistemas de gestão de contratos) — sem isso, o produto vira
   mais um silo de informação em vez de se integrar ao fluxo real de trabalho do cliente.

## 9. Decisões em aberto que exigem validação com o usuário/product owner antes da Fase 1

1. Confirmar corte de MVP proposto em [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md)
   (o que fica de fora da primeira versão vendável).
2. Confirmar se o produto assumirá risco de conteúdo jurídico com revisão humana obrigatória (gate
   bloqueante) ou apenas com disclaimer (gate não-bloqueante) — decisão de apetite a risco do
   negócio, não puramente técnica.
3. Confirmar modelo de cobrança (ligado à métrica de custo variável, ver item 5 da seção 8) antes de
   modelar `Plan`/`Entitlement` em detalhe.
4. Confirmar hospedagem alvo (nuvem pública com região no Brasil vs. infraestrutura própria) — afeta
   diretamente `SECURITY_MODEL.md` e custo de storage/observabilidade.
5. Confirmar se há, desde já, um cliente-piloto identificado — isso deveria dirigir qual conector de
   ingestão além do PNCP entra primeiro (ver item 2).
