# ADR-0005: Separação Global/Tenant Knowledge com deduplicação por content hash

## Status
Aceito

## Contexto
Documentos públicos (editais, leis, jurisprudência) são potencialmente relevantes para múltiplos
tenants simultaneamente. Processar OCR, parsing, chunking e embedding de forma isolada por tenant
multiplicaria custo e tempo sem nenhum ganho — esse processamento não depende de quem está olhando o
documento, só do próprio documento.

## Decisão
Duas camadas de conhecimento explícitas: **Global** (sem `tenant_id`, conteúdo público, processado
uma única vez e reutilizado) e **Tenant** (com `tenant_id` obrigatório, conteúdo privado). O
`content_hash` de um documento determina se o processamento pesado (OCR, parsing, chunking,
embedding) já existe no Global Layer antes de reprocessar. A `Analysis` específica de um tenant
sempre combina os dois (Global + Tenant) no momento da consulta, nunca duplica o processamento
global dentro do espaço do tenant.

## Alternativas consideradas
- **Processar tudo por tenant, sem camada global**: rejeitado — desperdiça custo de OCR/LLM
  proporcionalmente ao número de tenants interessados no mesmo edital, o que é comum (editais de
  grande valor atraem múltiplos concorrentes usando a mesma plataforma).
- **Uma única camada de conhecimento sem distinção Global/Tenant**: rejeitado — misturaria dados
  privados com públicos, tornando o isolamento de tenant mais difícil de garantir estruturalmente
  (ver [ADR-0002](0002-multi-tenancy-isolamento.md)).

## Consequências
- Exige métrica de taxa de reaproveitamento do Global Layer (ver
  [OBSERVABILITY.md](../OBSERVABILITY.md)) para validar que a deduplicação está funcionando como
  esperado.
- Exige disciplina de nunca vazar dado de tenant para o Global Layer por engano (ex.: anotação
  específica de um tenant sobre um edital público deve viver no Tenant Layer, referenciando o
  documento global, nunca sendo escrita de volta nele).
