# ADR-0008: Separação explícita SYNC/ASYNC desde o design de API

## Status
Aceito

## Contexto
Operações de análise (LLM, RAG, reranking) têm latência inerentemente maior e mais variável que
operações de leitura de dashboard. Sem uma regra explícita, é fácil um endpoint de UI acabar
aguardando uma chamada de LLM em linha, tornando uma lentidão de provider de IA em indisponibilidade
percebida de toda a plataforma.

## Decisão
Todo endpoint de API é classificado, no momento do design, como SYNC ou ASYNC (ver budget em
[DATA_AND_KNOWLEDGE_ARCHITECTURE.md](../DATA_AND_KNOWLEDGE_ARCHITECTURE.md)):

- **SYNC**: opera sobre dado já processado/pré-computado. Nunca aciona LLM, OCR ou ingestão em
  linha. Budget de latência sub-segundo.
- **ASYNC**: dispara job em fila, retorna imediatamente com identificador de acompanhamento, e o
  resultado chega via WebSocket/notificação/polling curto. Usado para geração/atualização de
  `Analysis`, `PriceAnalysis`, ingestão, reprocessamento de documento.

Endpoints que hoje pareceriam naturalmente síncronos mas envolvem geração de conteúdo (ex.: "gerar
análise desta oportunidade") são sempre ASYNC, mesmo que a resposta normalmente seja rápida —
latência de provider de IA é variável por natureza e não deve determinar a responsividade percebida
da interface.

## Alternativas consideradas
- **Deixar a decisão sync/async a critério de cada desenvolvedor caso a caso**: rejeitado — leva a
  inconsistência e a regressões de UX quando um provider de IA degrada.

## Consequências
- Frontend precisa de um padrão consistente de "operação em andamento" (streaming/polling/websocket)
  para toda ação ASYNC, definido uma vez em [UX_AND_ASSISTANT_SPEC.md](../UX_AND_ASSISTANT_SPEC.md)
  e reutilizado, não reinventado por tela.
