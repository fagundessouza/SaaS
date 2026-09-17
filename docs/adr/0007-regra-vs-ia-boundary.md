# ADR-0007: Fronteira explícita entre regra determinística e IA

## Status
Aceito

## Contexto
A seção 28 do prompt mestre estabelece o princípio ("regra quando determinístico, IA quando exige
interpretação semântica") mas não define onde, na prática, cada decisão do sistema cai. Sem essa
fronteira explícita por decisão, há risco de usar LLM para coisas que uma regra resolveria com mais
confiabilidade e menos custo (e vice-versa, usar regra rígida onde exige interpretação).

## Decisão

| Decisão do sistema | Mecanismo | Motivo |
|---|---|---|
| Validade de CNPJ/CNAE, prazos, comparação de datas | Regra determinística | Fato verificável, sem ambiguidade |
| Filtro inicial de compatibilidade (CNAE, região, faixa de valor) | Regra determinística | Primeira barreira de custo antes de qualquer chamada de IA |
| Similaridade semântica entre objeto do edital e produtos/serviços do tenant | IA (embeddings) | Sinônimos e reformulações não são capturados por regra de palavra-chave |
| Extração de requisitos de texto de edital | IA assistindo regra (classificação sobre texto extraído) | Interpretação de linguagem natural variável entre editais |
| Cálculo de piso econômico, margem, preço mínimo interno | Regra determinística (Deterministic Pricing Engine) | Fórmula definida pelo próprio tenant, não interpretação |
| Aplicabilidade de um critério legal a um tipo de contratação | Regra contextual com metadado de jurisdição/vigência (nunca `if` universal) | Ver [DATA_AND_KNOWLEDGE_ARCHITECTURE.md](../DATA_AND_KNOWLEDGE_ARCHITECTURE.md) |
| Recuperação de jurisprudência relacionada a um requisito | IA (RAG) sobre base curada | Exige interpretação semântica do requisito |
| Geração de texto explicativo/resumo para o usuário | IA | Síntese de linguagem natural |
| Score final de "vale a pena participar" | Nenhum score único automático — decomposição visível (compatibilidade, viabilidade operacional, viabilidade econômica) | Evita falsa precisão (ver [00-CRITICAL_ANALYSIS.md](../00-CRITICAL_ANALYSIS.md), seção 7) |

## Consequências
- Toda nova feature, ao ser especificada, precisa classificar explicitamente cada decisão que
  contém nesta tabela (ou adicionar uma nova linha justificada) antes de ser implementada — isso
  vira parte do processo de design de feature, não uma reflexão pós-hoc.
