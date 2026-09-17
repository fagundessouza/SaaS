# ADR-0001: Monorepo com monólito modular no backend, não microsserviços

## Status
Aceito

## Contexto
A especificação original propõe uma arquitetura sofisticada (ingestão, RAG, agentes, motor
jurídico, motor de preço, notificações multicanal) e ao mesmo tempo chama o produto de "MicroSaaS".
É preciso decidir a granularidade de deploy/runtime sem comprometer a separação de domínio exigida
pela especificação.

## Decisão
Backend como um único pacote Python versionado (monólito modular), com fronteiras de bounded
context aplicadas por convenção de import e verificadas por import linter em CI. Múltiplos
*processos* de runtime a partir do mesmo código (API, workers de ingestão, workers de análise,
workers de notificação), não múltiplos *serviços* com contratos de rede próprios. Frontend Next.js
como workspace separado no mesmo monorepo.

## Alternativas consideradas
- **Microsserviços por bounded context**: rejeitado por adicionar custo operacional (deploy,
  observabilidade distribuída, versionamento de contrato entre serviços) desproporcional ao estágio
  do produto (sem evidência de necessidade de escala ou de times múltiplos independentes).
- **Monólito não-modular** (tudo em um pacote sem fronteiras internas): rejeitado porque a
  especificação exige isolamento de domínio verificável (ex.: `platform/` não pode depender de
  `domains/procurement`) para permitir evolução e eventual extração futura sem reescrita.

## Consequências
- Deploy simples no início; extração de um módulo para serviço próprio é um refactor localizado, não
  uma reescrita, se e quando houver evidência real de necessidade (candidatos naturais:
  `ingestion`, `platform/knowledge` — ver [SYSTEM_ARCHITECTURE.md](../SYSTEM_ARCHITECTURE.md)).
- Exige disciplina de import linter desde a Fase 1 — sem isso, o monólito modular degrada em
  "big ball of mud" rapidamente.
