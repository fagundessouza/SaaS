# ADR-0009: PNCP como fonte canônica e prioritária de ingestão

## Status
Aceito

## Contexto
A especificação original trata PNCP, Compras.gov.br, SISLOG e portais estaduais/municipais como
fontes simetricamente prioritárias. Desde a Lei 14.133/2021, o PNCP é o agregador nacional
obrigatório de publicação de contratações públicas, com API de dados abertos, cobrindo a grande
maioria dos casos federais, estaduais e municipais sujeitos à lei. Construir conectores para
múltiplos portais estaduais/municipais residuais antes de esgotar o valor do PNCP é esforço de
engenharia de manutenção alta (scrapers de HTML são frágeis) para um ganho de cobertura
proporcionalmente pequeno no início.

## Decisão
PNCP é a fonte canônica e o único conector implementado no MVP (Fase 3 do roadmap). A interface
`Connector` é definida de forma genérica desde o início para permitir adicionar outras fontes sem
refactor, mas novos conectores só são construídos sob demanda real de cliente-piloto que efetivamente
contrata com órgãos publicando fora do PNCP (contratos de transição sob lei anterior, ou fontes
complementares específicas), não especulativamente.

## Alternativas consideradas
- **Construir N conectores simetricamente desde o início**: rejeitado — desperdiça esforço de
  engenharia em manutenção de scrapers frágeis antes de validar se há demanda real para além do
  PNCP.

## Consequências
- Cobertura de ingestão no MVP é limitada a contratações publicadas no PNCP — isso deve ser
  comunicado com transparência a clientes piloto, não apresentado como cobertura universal.
- Métrica de observabilidade (ver [OBSERVABILITY.md](../OBSERVABILITY.md)) monitora volume de
  ingestão do PNCP contra linha de base esperada, para detectar instabilidade da própria API do
  governo cedo.
