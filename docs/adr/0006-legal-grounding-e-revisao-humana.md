# ADR-0006: Toda saída jurídica é ancorada em evidência versionada; gate de revisão humana

## Status
Aceito

## Contexto
Inteligência jurídica é a maior superfície de risco de responsabilidade do produto (ver
[00-CRITICAL_ANALYSIS.md](../00-CRITICAL_ANALYSIS.md), seção 4). Um LLM pode "lembrar" de
jurisprudência a partir de conhecimento paramétrico e alucinar número de processo, ementa ou
tribunal — erro que pode causar dano concreto ao usuário (deixar de recorrer, ou recorrer com
fundamento inexistente). Sugerir impugnação/recurso também pode ser confundido com assessoria
jurídica, reservada a advogado inscrito na OAB.

## Decisão
1. Nenhuma citação jurídica (norma, acórdão, súmula) é aceita como saída sem vir de recuperação
   (RAG) sobre uma base `LegalSource` curada e versionada — nunca resposta livre do LLM sobre
   jurisprudência a partir de memória paramétrica.
2. Toda citação carrega `source_url` e `document_version` rastreáveis, exibidos na UI junto à
   conclusão.
3. Saídas sem evidência suficiente são marcadas `REQUIRES_HUMAN_REVIEW` no dado, não apenas na
   apresentação, e a UI as trata como rascunho/sugestão, nunca como conclusão definitiva.
4. Linguagem de saída é sempre proporcional à evidência: "possível restrição", "requisito que
   merece análise", nunca "isto é ilegal" ou "isto é nulo" (seção 14 do prompt mestre).
5. O produto se posiciona, em termos de uso e em disclaimers de UI, como ferramenta de apoio à
   decisão — não como assessoria jurídica.

## Alternativas consideradas
- **Permitir o LLM responder livremente sobre jurisprudência, com disclaimer genérico**: rejeitado
  — disclaimer não mitiga o risco de decisão de negócio tomada sobre citação inventada; o problema é
  estrutural (fonte de dado), não de aviso na tela.
- **Bloquear completamente qualquer saída jurídica sem revisão humana síncrona**: rejeitado como
  padrão único — inviabilizaria a velocidade prometida pelo produto; o gate é seletivo
  (`REQUIRES_HUMAN_REVIEW`), não universal, aplicado quando a evidência é insuficiente ou o tema é
  de alto risco (ex.: recomendação de impugnação/recurso).

## Consequências
- Exige que a base jurídica (`LegalSource`) esteja populada e versionada antes de qualquer feature
  jurídica avançada entrar em produção — motivo pelo qual, no roadmap, o aprofundamento de Legal
  Intelligence é uma fase própria (Fase 12), não parte do MVP inicial.
- Exige campo estrutural `requires_human_review: bool` e `evidence[]` em `Finding`/`Recommendation`
  (ver [DOMAIN_MODEL.md](../DOMAIN_MODEL.md)), não apenas um texto de aviso na interface.
