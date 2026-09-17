# UX e Especificação do Assistente

## Navegação (crítica à proposta original)

A proposta original (seção 20) lista 10 itens de navegação. Aplicando o teste "cada tela precisa
responder uma necessidade real" (seção 20):

| Item original | Avaliação | Decisão |
|---|---|---|
| Visão Geral | Necessidade real: "o que mudou desde a última vez que abri isso" | Mantido |
| Radar | Núcleo do produto | Mantido |
| Oportunidades | Redundante com Radar se não houver diferença de conceito clara | **Fundido com Radar** — "Radar" é a tela, "Oportunidades" é o estado de uma vez qualificadas (ver ciclo de vida em DOMAIN_MODEL.md); não precisa ser uma tela separada, e sim um filtro de status dentro do Radar |
| Análises | Faz sentido como lista, mas o conteúdo real vive dentro de cada Oportunidade (dossiê) | Mantido como lista de acesso rápido, mas sem duplicar o dossiê |
| Minha Empresa | Necessidade real: onde o `CompanyProfile` é gerido | Mantido |
| Documentos | Necessidade real: certidões/atestados centralizados | Mantido |
| Mercado | Vago na especificação original — se virar "mais uma aba genérica", cai no risco de complexidade inútil | **Redefinido**: Inteligência Competitiva (histórico de concorrentes, taxas de vitória — o gap identificado na análise crítica), não um "mercado" genérico |
| Jurídico | Necessidade real, mas só se alimentado por base curada (ver ADR-0006) | Mantido, com disclaimer permanente de "apoio à decisão, não assessoria jurídica" |
| Agenda | Sobrepõe com notificações de prazo — avaliar se justifica tela própria ou é uma visão filtrada de Notificações | **Fundida em uma view de "Prazos"** dentro de Visão Geral, não uma aba de primeiro nível no MVP |
| Assistente | Onipresente (botão flutuante), não uma aba | Mantido como componente global, não item de navegação |

Navegação revisada (MVP): **Visão Geral · Radar · Análises · Minha Empresa · Documentos ·
Inteligência Competitiva · Jurídico**, mais o assistente como componente flutuante em todas as
telas.

## Progressive disclosure (seção 21) — aplicado concretamente

```
RESUMO           "7 oportunidades compatíveis"
  ↓
EXPLICAÇÃO       "Compatível por: CNAE 6201-5/01, região SP, valor dentro da faixa operacional"
  ↓
DETALHE          Requisitos extraídos, pendências identificadas, riscos
  ↓
EVIDÊNCIA        Trecho exato do edital que sustenta cada requisito/risco
  ↓
FONTE            Documento original, página, seção — link para o PDF na posição exata quando possível
```

Regra de UI: nenhuma tela mostra um nível sem oferecer navegação explícita para o nível seguinte
(sempre visível, nunca escondido atrás de múltiplos cliques) — é o que operacionaliza "simplicidade
+ profundidade" sem forçar todo usuário a navegar manualmente por menus para achar a evidência.

## Assistente contextual

### Contexto que o assistente recebe automaticamente (nunca pedido ao usuário)

```
context:
  tenant_id       (implícito, nunca exposto/editável pelo usuário via chat)
  user_id
  company_profile_summary
  current_screen: "opportunity_detail"
  opportunity_id (se aplicável)
    tender, items, requirements, documents, analysis, findings, evidence
  recent_history (últimas decisões/feedback relevantes ao contexto atual)
```

**Restrição de segurança explícita** (complementa [SECURITY_MODEL.md](SECURITY_MODEL.md)): o
contexto é montado pelo backend a partir do `tenant_id` da sessão autenticada — nunca aceito como
parâmetro vindo do cliente. O assistente não tem uma "ferramenta" que aceite `tenant_id` arbitrário;
isso elimina uma classe inteira de vazamento entre tenants via prompt/parâmetro manipulado.

### Ações sugeridas por tela (exemplos, não exaustivo)

Na tela de uma `Opportunity`:

```
[Entender edital]  [O que está faltando?]  [Analisar preço]
[Ver riscos]       [Comparar histórico]     [Explicar este requisito]
```

Cada botão dispara uma chamada de ferramenta específica e determinística no backend (não um prompt
livre reinterpretado) — o texto do botão é uma âncora de intenção, não uma sugestão de frase para o
usuário digitar. Isso mantém o assistente como interface de **ação**, não um chat genérico solto
(mitiga o risco de "Fake AI" identificado na análise crítica, seção 7, item 1).

### O que o assistente nunca faz

- Nunca afirma conclusão jurídica sem apontar `LegalSource` versionado (ver ADR-0006).
- Nunca expõe dado de outro tenant, mesmo que o usuário peça explicitamente ("compare comigo outra
  empresa que participou") — a ferramenta de retrieval não tem capacidade de cruzar tenants, então
  fisicamente não há como isso vazar por má interpretação de prompt.
- Nunca executa uma ação irreversível (submeter proposta, confirmar decisão de participação) sem
  confirmação explícita de UI fora do chat.

## Memória do assistente — três níveis (seção 17), aplicados

| Nível | Conteúdo | Onde vive | Pode vazar entre tenants? |
|---|---|---|---|
| Global | Conhecimento público da plataforma (como interpretar um tipo de cláusula comum) | Global Knowledge Layer | Não é dado de tenant — compartilhável por definição |
| Tenant | Perfil, documentos, histórico, preferências | Tenant Knowledge Layer | Nunca — isolamento estrutural (ver DATA_AND_KNOWLEDGE_ARCHITECTURE.md) |
| Operacional | Feedback e padrão de interação do usuário | Tenant Knowledge Layer, subconjunto | Nunca |

Feedback humano pode ajustar: recuperação (retrieval tuning), matching, priorização, prompts,
memória operacional. Feedback **não pode** alterar automaticamente regras jurídicas críticas
(`legal_thresholds`) — essas só mudam por atualização versionada de `LegalSource` ou revisão
humana explícita de um responsável autorizado, nunca por aprendizado implícito de uso.

## Dois perfis de usuário — ambos servidos pela mesma tela

- **Quer pouco**: vê "Encontramos 5 oportunidades", sem precisar abrir nada além disso para decidir
  ignorar ou aprofundar.
- **Quer investigar**: mesma tela, mas cada elemento é clicável até a fonte. Não existem duas
  telas diferentes para os dois perfis — existe uma tela com profundidade progressiva.
