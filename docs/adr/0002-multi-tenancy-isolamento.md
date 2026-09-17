# ADR-0002: Estratégia de isolamento multi-tenant por camada de dado

## Status
Aceito

## Contexto
O produto é B2B com dados comerciais sensíveis por tenant (custos, margens, documentos privados).
Vazamento entre tenants é o risco mais severo do sistema (ver
[00-CRITICAL_ANALYSIS.md](../00-CRITICAL_ANALYSIS.md)). É preciso uma estratégia concreta por
tecnologia de dado, não apenas o princípio geral "isolar tenants".

## Decisão

| Dado | Estratégia | Justificativa |
|---|---|---|
| PostgreSQL | Schema compartilhado, `tenant_id` em toda tabela `TENANT`, aplicado no repositório + **Row-Level Security** como segunda barreira | Schema-per-tenant ou database-per-tenant não escalam operacionalmente (migrations em N schemas, connection pooling complexo) para o volume de tenants esperado; RLS dá defesa em profundidade sem esse custo |
| Qdrant | Uma collection compartilhada por camada (Global, Tenant) com `tenant_id` como payload indexado e filtro obrigatório na assinatura da função de retrieval | Collection-per-tenant não escala (overhead de gestão e HNSW ineficiente em coleções pequenas); filtro obrigatório na assinatura (não opcional) elimina a classe de bug "esqueci o filtro" |
| MinIO/S3 | Prefixo de objeto por tenant + signed URLs de curta duração | Bucket-per-tenant não escala operacionalmente; prefixo + policy de acesso é suficiente com o cuidado de nunca gerar URL pública permanente |
| Redis | Toda chave de dado de tenant prefixada por `tenant_id` | Simples e suficiente dado que Redis aqui é cache/fila, não fonte de verdade |
| Jobs assíncronos | `tenant_id` obrigatório no payload, worker rejeita ausência quando aplicável | Evita job "órfão" de tenant processando com contexto errado |

## Alternativas consideradas
- **Database-per-tenant**: mais forte isoladamente, mas custo operacional (migrations, pooling,
  backup) inviável para o número de tenants e o estágio de maturidade da equipe.
- **Confiar apenas em filtro de aplicação, sem RLS**: rejeitado — um único bug de código vira
  incidente de confiança fatal; RLS é barato de implementar e dá segunda barreira real.

## Consequências
- Toda função de retrieval/repositório de dado `TENANT` precisa de teste de isolamento automatizado
  (ver [DEVELOPMENT.md](../DEVELOPMENT.md)), obrigatório em CI para qualquer PR que toque essas
  camadas.
- RLS adiciona alguma complexidade de configuração de sessão de banco (definir `tenant_id` de
  sessão a cada conexão) — aceito como custo necessário.
