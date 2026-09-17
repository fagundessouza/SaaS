# ADR-0010: WhatsApp como Notification Channel via API oficial, sem dependência de grupo/comunidade

## Status
Aceito

## Contexto
A seção 19 do prompt mestre exige que WhatsApp seja tratado como canal de notificação, mas proíbe
dependência estrutural de "grupo WhatsApp" ou "comunidade WhatsApp" — mecanismos informais, não
auditáveis, e fora do controle de entrega/observabilidade do produto.

## Decisão
WhatsApp é implementado como um `NotificationChannel` (ver
[EVENT_AND_NOTIFICATION_ARCHITECTURE.md](../EVENT_AND_NOTIFICATION_ARCHITECTURE.md)) via API oficial
(Meta Cloud API), integrada através de um BSP (Business Solution Provider) homologado — nunca
automação não-oficial de WhatsApp pessoal (que viola termos de uso da plataforma e é tecnicamente
frágil/sujeita a bloqueio). Entra no roadmap (Fase 10, aprofundamento posterior) apenas após
validação de custo por conversa e demanda real de clientes-piloto, dado que o modelo de cobrança por
conversa do WhatsApp Business afeta diretamente a unit economics do produto (ver
[OBSERVABILITY.md](../OBSERVABILITY.md), cost governance).

## Alternativas consideradas
- **Grupo/comunidade WhatsApp como canal**: rejeitado explicitamente pela especificação e por não
  permitir preferência individual de canal por tipo de alerta, nem garantia de entrega/leitura
  rastreável.
- **Automação não-oficial (bibliotecas que simulam um cliente WhatsApp Web)**: rejeitado — risco de
  bloqueio de número, viola termos de serviço, e não é uma base confiável para uma feature paga.

## Consequências
- Exige processo de aprovação/homologação de número comercial junto ao BSP antes de disponibilizar
  o canal — isso é uma dependência externa com lead time que precisa ser considerada com
  antecedência no roadmap, não deixada para a véspera da Fase 10.
- Preferência de canal por tipo de alerta (ver
  [EVENT_AND_NOTIFICATION_ARCHITECTURE.md](../EVENT_AND_NOTIFICATION_ARCHITECTURE.md)) permite ao
  tenant escolher WhatsApp só para alertas de alta prioridade, mitigando custo por conversa.
