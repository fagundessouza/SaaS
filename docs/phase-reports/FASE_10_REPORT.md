# Relatório de Checkpoint — Fase 10 (Event + Notification Engine)

Ver critério de saída em [IMPLEMENTATION_ROADMAP.md](../IMPLEMENTATION_ROADMAP.md#fase-10--event--notification-engine-escopo-mínimo-email--web-push):
"uma retificação de edital real dispara notificação correta ao tenant afetado."

## IMPLEMENTADO

- `core/notifications/models.py`: `Alert` (decisão de que um evento importa para um usuário
  específico, idempotente por `(source_event_id, user_id)`), `Notification` (uma tentativa de
  entrega por canal, `PENDING → SENT | FAILED`), `NotificationPreference` (por usuário + tópico +
  canal, nunca uma preferência global) e `PushSubscription` (assinatura de Web Push do
  navegador). Todas TENANT, com RLS.
- `core/notifications/channels/`: `NotificationChannel` (Protocol de um único método). Dois
  canais, cada um com duas implementações — `ConsoleEmailChannel`/`SmtpEmailChannel` e
  `ConsolePushChannel`/`WebPushChannel` — escolhidas por configuração
  (`get_email_channel()`/`get_web_push_channel()`). A implementação "console" **não é um
  stub**: é a implementação real usada em qualquer ambiente sem SMTP/VAPID configurado (mesmo
  raciocínio de `core/billing` — "sem gateway de pagamento" — já aplicado desde a Fase 2), loga
  a mensagem que teria sido enviada e retorna `SENT`, nunca `FAILED`.
- `core/notifications/formatting.py`: `format_message(topic, payload) -> (assunto, corpo)` —
  determinístico por tópico, nunca gerado por LLM (`ai_platform/llm` não existe ainda, Fase 9,
  adiada nesta sessão por decisão explícita do usuário — ver DECISÕES).
- `core/notifications/service.py`: `create_alert_and_dispatch()` — cria o `Alert` (idempotente),
  consulta `NotificationPreference` (padrão: habilitado, modelo opt-out) e
  `PushSubscription`, dispara em todo canal habilitado.
- `domains/notifications/handlers.py`: roteamento tópico → quem notificar. `TenderUpdated`
  (sem `tenant_id` — `Tender` é GLOBAL) varre todo tenant e verifica quem tem `Opportunity` para
  aquele `Tender` (mesmo padrão de iteração já usado por `run_opportunity_matching_job`, pela
  mesma razão: `Opportunity` tem `FORCE ROW LEVEL SECURITY`, sem bypass introduzido sem
  deliberação própria). `OpportunityMatched`/`AnalysisCompleted` já carregam `tenant_id`, sem
  necessidade de varredura.
- `domains/notifications/consumer.py`: consome o Redis Stream do outbox (`core/events/dispatcher.py`,
  já existente desde a Fase 1) via Consumer Group (`XREADGROUP`/`XACK`) — mensagem só é
  confirmada depois do handler rodar com sucesso; falha não trava o stream, a mensagem não
  confirmada é reentregue no próximo ciclo. A idempotência real mora no `Alert` (constraint
  única), não na garantia do Redis.
- `AnalysisCompleted` (Fase 8) agora é publicado de fato — `generate_analysis` não disparava
  nenhum evento antes desta fase.
- `api/v1/notifications.py`: inbox (`GET /v1/notifications`), preferências
  (`GET`/`PUT /v1/notifications/preferences`) e assinaturas de Web Push
  (`POST`/`DELETE /v1/notifications/push-subscriptions`).
- `worker.py`: novo cron `consume_notification_events_job` (a cada 10s, defasado 5s do despacho
  do outbox — mesmo padrão de defasagem já usado entre ingestão e matching na Fase 7).
- Dependência nova: `pywebpush` (+ `py-vapid`, `cryptography`) — só para assinar/enviar Web
  Push; VAPID não depende de nenhuma conta de terceiro, só de um par de chaves gerado localmente.

## AMBIENTE (setup real)

Testado ao vivo o pipeline completo antes de escrever qualquer teste formal (ver PROBLEMAS):
publiquei um `TenderUpdated` real, rodei `dispatch_pending_events()` e
`consume_notification_events_job` manualmente, e confirmei `Alert`+`Notification` corretos com
os dois canais "console" logando a mensagem certa — inclusive rodando o consumidor uma segunda
vez para confirmar que nada é reprocessado (`XACK` funcionando).

## TESTADO

- `ruff`, `mypy --strict`, `import-linter` — limpos (158 arquivos-fonte).
- Migration (`alerts`, `notifications`, `notification_preferences`, `push_subscriptions`, RLS
  nas 4, 2 ENUMs novos) `upgrade`/`downgrade`/`upgrade` — reversível.
- `pytest -v` — **163 testes passando**, três rodadas consecutivas (50s/48s/85s).
  - `tests/unit/test_notification_formatting.py` (6 testes): mensagem correta por tópico
    conhecido; tópico desconhecido cai no genérico sem lançar exceção.
  - `tests/unit/test_notification_channels.py` (5 testes): canais "console" sempre retornam
    `SENT`; `WebPushChannel` sem assinatura cadastrada também retorna `SENT` (não é falha);
    fábrica escolhe console quando SMTP/VAPID não configurados (ambiente atual).
  - `tests/integration/test_notification_service.py` (3 testes, Postgres real): `Alert` +
    `Notification` por canal habilitado; idempotência por `(source_event_id, user_id)`;
    preferência desabilitada realmente pula o canal.
  - `tests/integration/test_notification_consumer.py` (3 testes, Postgres + Redis reais):
    `TenderUpdated` notifica só quem tem `Opportunity` para aquele Tender, não todo tenant;
    consumidor idempotente entre rodadas consecutivas; `OpportunityMatched` notifica o tenant já
    conhecido diretamente, sem varredura.
  - `tests/integration/test_notification_api.py` (4 testes): preferências (set + upsert),
    assinatura de push (criar + apagar, 404 ao apagar de novo), inbox com status de entrega.
  - `tests/security/test_notification_isolation.py` (2 testes): as 4 tabelas novas isoladas por
    tenant via RLS; token de outro tenant não alcança a inbox pela API.

## PROBLEMAS (encontrados e corrigidos durante esta fase)

1. **`domain_events` acumulando sem limite, sem ser pego pelo fix de acúmulo da Fase 8**:
   testando o pipeline manualmente antes de escrever os testes formais, o primeiro Alert
   esperado simplesmente não apareceu — investigando, `domain_events` tinha **3801 linhas não
   despachadas** acumuladas ao longo do dia (todo evento publicado por qualquer teste desde a
   Fase 1 que nunca chamou `dispatch_pending_events`). O fix de acúmulo da Fase 8
   (`_reset_accumulating_tables`, `TRUNCATE tenants, tenders CASCADE`) não alcança esta tabela
   porque `DomainEvent.tenant_id` **não tem FK** (é infraestrutura interna despachada por um
   worker de confiança, nunca RLS-scoped, ver `core/events/models.py`) — nada cascateia até ela.
   Corrigido estendendo a mesma fixture para também `TRUNCATE domain_events` e `DELETE` a chave
   do Redis Stream (que já tinha recebido o backlog inteiro via `XADD`) — um consumer group novo
   lê do início do stream (`id="0"`), então sem isso o primeiro teste do Notification Engine
   teria que processar o mesmo backlog gigante antes de alcançar o evento que o próprio teste
   criou. Achado colateral do fix: o cliente Redis criado dentro do `asyncio.run()` isolado da
   fixture precisa ser resetado para `None` depois (mesmo motivo já documentado para o cliente
   Qdrant na Fase 6) — sem isso o primeiro teste real herdaria um client preso a um event loop já
   fechado.

## RISCOS

- `handle_tender_updated` é O(tenants) por evento de retificação (varre todo tenant para achar
  quem tem `Opportunity` para aquele Tender) — mesma limitação já documentada para
  `run_opportunity_matching_job` na Fase 7/8, e pela mesma razão: `Opportunity` tem `FORCE ROW
  LEVEL SECURITY`, então não há como fazer uma única query cross-tenant sem introduzir um bypass
  de RLS deliberado, o que este projeto não faz sem avaliação própria. Aceitável no volume atual
  (mitigado pela fixture de reset da Fase 8); reavaliar se o número de tenants ativos crescer a
  ponto de tornar isto lento em produção.
- Canais "console" (padrão atual, sem SMTP/VAPID configurados em nenhum ambiente deste projeto
  ainda) não enviam nada de verdade — o `NotificationChannel` real (`SmtpEmailChannel`,
  `WebPushChannel`) existe e está testado nas partes que não dependem de credencial externa
  (formatação, decisão de canal habilitado), mas o caminho de entrega SMTP/Web Push real em si
  não foi exercitado contra um provedor de verdade (não há credencial disponível nesta sessão —
  decisão explícita do usuário de adiar isso, ver DECISÕES).
- `CertificateExpiring` (catálogo já documentado em
  `docs/EVENT_AND_NOTIFICATION_ARCHITECTURE.md` e em `core/notifications/formatting.py`) não tem
  produtor ainda — precisaria de um job agendado diário varrendo `Certificate.expires_at`, fora
  do escopo mínimo desta fase (o critério de saída é sobre retificação de edital, não sobre
  certidão).
- `DocumentCreated`/`LegalSourceUpdated`/`UserFeedbackCreated` (catálogo da arquitetura) não têm
  produtor: os dois primeiros porque o consumidor que a arquitetura previa (indexação de
  conhecimento) já é chamado diretamente por código, não por evento; o terceiro porque
  `Feedback`/`LegalSource` como entidades de domínio ainda não existem no projeto.

## DECISÕES

- **Fase 9 (Assistente) adiada, não implementada nesta sessão**: exige um provedor de LLM real
  (`ai_platform/llm`, credenciais externas) e um frontend (botão flutuante) — nenhum dos dois
  existe ainda no projeto, e ambas são decisões que o usuário explicitamente pediu para adiar
  (perguntado diretamente: "pular a Fase 9 por agora" e "só backend por enquanto" para o
  frontend). Fase 10 seguiu em frente porque é backend puro, sem essas duas dependências.
- **Canais "console" são implementações de primeira classe, não stubs**: mesmo raciocínio já
  usado para `core/billing` desde a Fase 2 ("sem gateway de pagamento"). O código de entrega real
  (`SmtpEmailChannel` via `smtplib`, `WebPushChannel` via `pywebpush`/VAPID) já existe e está
  pronto para quando houver credenciais reais a configurar — não é um TODO deixado para depois,
  é uma implementação alternativa completa e testável isoladamente.
- **Web Push escolhido junto com e-mail** (não WhatsApp/Telegram, conforme o roadmap já
  determinava) especificamente porque não depende de nenhuma conta de terceiro — só de um par de
  chaves VAPID gerado localmente. Isso evitou a mesma pausa para decisão de credencial que a
  Fase 9 exigiu para o LLM.
- **Idempotência em duas camadas**: o Redis Stream garante "pelo menos uma vez" via Consumer
  Group (mensagem só confirmada após sucesso do handler), mas a garantia real contra duplicação
  de notificação é a constraint única `(source_event_id, user_id)` em `Alert` — mesmo padrão já
  estabelecido pela arquitetura de eventos desde a Fase 0 ("nenhum consumidor pode assumir
  entrega exatamente-uma-vez da fila").

## PENDÊNCIAS

1. Configurar SMTP/VAPID reais em um ambiente com credenciais disponíveis e validar o caminho de
   entrega de verdade (`SmtpEmailChannel`/`WebPushChannel`) contra um provedor real — hoje só
   testado o caminho "console".
2. `CertificateExpiring`: job agendado diário varrendo `Certificate.expires_at` — natural
   próximo passo, mesma disciplina de "regra determinística" já usada em toda comparação de data
   deste projeto (ADR-0007).
3. Revisitar a Fase 9 (Assistente) quando houver decisão de provedor de LLM e direção de
   frontend — ambas explicitamente adiadas pelo usuário nesta sessão.
4. `handle_tender_updated` O(tenants) — recalibrar se o volume de tenants ativos crescer.

## PRÓXIMA FASE

Fase 11 — Frontend (paralelo às Fases 6-10, não sequencial após elas): cresce contra os
contratos de API já estabilizados desde a Fase 1. Adiada nesta sessão junto com a Fase 9 por
decisão explícita do usuário — retomar quando houver direção de stack definida.
