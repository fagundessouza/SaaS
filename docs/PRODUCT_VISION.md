# Visão de Produto

## O que é

Uma plataforma B2B por assinatura que faz o trabalho pesado de encontrar, entender e qualificar
oportunidades de contratação pública no Brasil para empresas fornecedoras, e que consegue provar
cada conclusão com evidência rastreável até a fonte original.

## O que não é

- Não é um motor de busca de licitações (existem vários; não é onde está o valor).
- Não é um chatbot genérico "converse com seus PDFs".
- Não é um escritório de advocacia digital — não emite pareceres jurídicos definitivos.
- Não é, na v1, um substituto completo do processo de elaboração de propostas — é o que decide
  **se vale a pena** entrar e **o que falta** para entrar bem preparado.

## Para quem

Empresas de pequeno e médio porte que vendem para o setor público de forma recorrente e não têm
uma equipe jurídica/de inteligência dedicada e grande o suficiente para vasculhar manualmente
centenas de editais por semana. O comprador típico é quem hoje perde horas em portais de
transparência e planilhas para decidir em quais licitações participar.

## Proposta de valor central

> "Eu não preciso entender o sistema. O sistema entende o que eu preciso."
> — e, quando eu quiser conferir, ele me mostra exatamente o documento, a página e a regra por
> trás de cada conclusão.

Isso se traduz em três promessas concretas e testáveis:

1. **Redução de ruído**: de milhares de publicações por dia para um punhado de oportunidades
   realmente compatíveis, com o motivo de cada uma.
2. **Redução de risco de decisão**: nenhuma conclusão de preço, prazo ou elegibilidade é
   apresentada sem a evidência que a sustenta.
3. **Redução de tempo até a decisão**: o dossiê de uma oportunidade (requisitos, pendências,
   preço, risco) fica pronto antes que o usuário precise pedir.

## Fora de escopo (explicitamente, para a v1 e para o horizonte de 12 meses)

- Emissão de pareceres jurídicos vinculantes ou substituição de advogado.
- Execução de lances/propostas automatizada (RPA de portal) sem confirmação humana.
- Geração de propostas comerciais completas prontas para envio (fica para depois do MVP — ver
  [00-CRITICAL_ANALYSIS.md](00-CRITICAL_ANALYSIS.md), seção 8).
- Cobertura de 100% dos portais municipais do país no dia 1 (PNCP primeiro — ver
  [ADR-0009](adr/0009-pncp-fonte-canonica.md)).

## Métricas de sucesso do produto (norte para priorização, não vaidade)

| Métrica | O que mede | Por que importa |
|---|---|---|
| Tempo até a primeira oportunidade relevante mostrada | Ativação | Se demorar, o usuário não volta |
| % de oportunidades no radar que o usuário marca como relevante | Precisão do matching | Sinal direto de que o filtro determinístico + semântico está calibrado |
| % de conclusões com evidência aberta pelo usuário | Confiança | Se ninguém confere a evidência, ou ela é irrelevante, ou a confiança já quebrou antes |
| Custo de IA por oportunidade analisada | Unit economics | Ver seção 10T do prompt mestre e [00-CRITICAL_ANALYSIS.md](00-CRITICAL_ANALYSIS.md) item 5 |
| Tempo de usuário até a decisão (participar/não participar) | Valor de tempo | Promessa central do produto |

## Princípios de produto (não negociáveis, valem para toda fase)

1. Progressive disclosure: resumo → explicação → detalhe → evidência → fonte (seção 21).
2. Determinístico antes de IA sempre que a decisão for baseada em fato verificável (seção 28).
3. Toda conclusão de alto risco (jurídico, preço, elegibilidade) é rastreável a uma evidência
   concreta (seção 12).
4. Nenhum dado de um tenant é acessível a outro, em nenhuma camada (seção 7).
5. Nenhuma feature de IA entra no roadmap sem passar no teste da seção 29 ("o que isso permite que
   busca tradicional não permitiria?").
