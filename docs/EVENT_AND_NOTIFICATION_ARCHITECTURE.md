# Arquitetura de Eventos e Notificações

## Event Engine

Implementado como **outbox pattern** sobre Postgres, não como dependência de um message broker
externo desde o dia 1 (YAGNI no estágio atual — Redis já está no stack para filas de job e pode
mediar consumo, mas a fonte da verdade do evento é uma tabela transacional, para garantir que
gravar o estado de domínio e publicar o evento sejam atômicos).

```
Mudança de estado de domínio (mesma transação)
        │
        ▼
   grava em `domain_events` (outbox)
        │
        ▼
   worker de despacho lê outbox → publica em fila Redis por tópico
        │
        ▼
   consumidores (workers, n8n via webhook, etc.)
```

### Catálogo de eventos de domínio (base da seção 10)

| Evento | Produtor | Consumidores esperados |
|---|---|---|
| `TenderCreated` | ingestion/pipeline | opportunities (matching) |
| `TenderUpdated` (retificação) | ingestion/pipeline | opportunities, analysis (invalida cache L5), notification |
| `TenderDeadlineChanged` | ingestion/pipeline | notification |
| `DocumentCreated` / `DocumentUpdated` | platform/documents | knowledge indexing |
| `LegalSourceUpdated` / `NormativeChanged` | platform/knowledge (legal) | legal impact analysis, notification |
| `CertificateExpiring` | jobs agendado (varredura diária) | notification |
| `OpportunityMatched` | domains/procurement/opportunities | notification, analysis (gatilho opcional de auto-análise para match forte) |
| `AnalysisCompleted` | domains/procurement/analysis | notification, assistant (contexto atualizado) |
| `UserFeedbackCreated` | domains/procurement (feedback) | learning/retrieval tuning |

### Idempotência (mitigação do risco #6 da análise crítica)

Todo evento tem `event_id` (UUID) único, gerado no momento da gravação no outbox — não no momento
do despacho. Todo consumidor mantém registro de `event_id` processados (tabela ou chave Redis com
TTL longo) e descarta reentregas. Nenhum consumidor pode assumir entrega exatamente-uma-vez da
fila; a idempotência é responsabilidade do consumidor, não da fila.

### Fluxos compostos (exemplos da seção 10)

```
NOVA LICITAÇÃO
   → TenderCreated
   → matching determinístico por tenant ativo
   → (se compatível) OpportunityMatched
   → Notification Engine → canal preferido do usuário
```

```
ALTERAÇÃO LEGAL
   → LegalSourceUpdated
   → diff contra versão anterior
   → impact analysis (quais Requirement/Analysis referenciam esta fonte)
   → identificar tenants com Opportunity ativa afetada
   → Notification Engine (alerta específico, não genérico)
```

## Notification Engine

```
Alert
  │
  ├── Web Push
  ├── Email
  ├── WhatsApp (via BSP oficial — ver ADR-0010)
  ├── Telegram
  └── outros (plugável via NotificationChannel interface)
```

`NotificationChannel` é uma interface com um único contrato (`send(notification) -> DeliveryResult`)
— o core do domínio nunca importa um SDK de canal específico diretamente; cada canal é um adapter
isolado, com suas próprias credenciais, rate limits e formato de mensagem.

Preferências de canal são configuráveis por usuário e por tipo de `Alert` (ex.: "prazo próximo" via
WhatsApp, "nova oportunidade" só por email) — não uma preferência global única.

### Estados de entrega

```
PENDING → SENT → DELIVERED | FAILED | BOUNCED
```

Falha de entrega em um canal não deve bloquear tentativa em outro canal configurado como fallback —
a política de fallback é configuração do `Alert`, não lógica hardcoded no worker de notificação.

## Segurança de webhooks (entrada e saída)

- **Webhooks recebidos** (ex.: confirmação de entrega de provedor de WhatsApp/email): validação de
  assinatura HMAC do provedor, verificação de timestamp para evitar replay, endpoint idempotente
  por `event_id` do provedor.
- **Webhooks emitidos** (se a plataforma expuser webhooks a integrações do próprio tenant no
  futuro): assinatura HMAC própria, retries com backoff exponencial, e o tenant nunca recebe dados
  de outro tenant no payload (isolamento aplicado também na camada de saída, não só na de leitura).
