# ADR-0003: Abstração de provider de LLM e embedding — fina, não especulativa

## Status
Aceito

## Contexto
A especificação exige arquitetura "provider-agnostic" para LLM e embeddings, citando Ollama, Qwen,
DeepSeek, APIs externas e "outros modelos futuros". Há risco de over-engineering: construir uma
abstração genérica para N providers hipotéticos antes de haver necessidade real de trocar entre
eles.

## Decisão
Definir as interfaces `LLMProvider` e `EmbeddingProvider` no domínio (`platform/llm`,
`platform/embeddings`) desde a Fase 0, com contrato mínimo (`complete`, `stream`, `embed`) — mas
**implementar concretamente apenas dois providers no início**: um self-hosted (compatível com
Ollama para modelos como Qwen/DeepSeek) e um de API externa, como fallback e comparação de
qualidade/custo. Nenhum domínio de negócio (`domains/procurement`) importa um SDK de provider
diretamente — sempre através da interface.

## Alternativas consideradas
- **Acoplar direto a um único provider de API** (mais rápido no curto prazo): rejeitado —
  contradiz requisito explícito da especificação e cria risco de dependência de fornecedor único
  para uma capacidade central do produto.
- **Suportar todos os providers citados desde o dia 1**: rejeitado — esforço de manutenção e
  superfície de teste desproporcional; nenhum deles tem uso real ainda validado.

## Consequências
- Troca ou adição de provider é um novo adapter atrás da interface existente, não um refactor de
  domínio.
- Custo/latência/qualidade por provider são medidos via observabilidade (ver
  [OBSERVABILITY.md](../OBSERVABILITY.md)) antes de decidir expandir a lista de providers suportados
  em produção.
