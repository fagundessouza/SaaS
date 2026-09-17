# Modelo de Segurança

## Prioridade #1: isolamento de tenant

Este é o requisito de segurança mais importante do produto — mais que autenticação, mais que
qualquer outro item desta lista — porque uma falha aqui expõe dados comerciais sensíveis (preços,
margens, estratégia, documentos privados) de uma empresa para outra, o que é um evento de confiança
fatal para um SaaS B2B neste setor.

Estratégia de defesa em profundidade, camada por camada:

| Camada | Mecanismo primário | Defesa adicional |
|---|---|---|
| PostgreSQL | `tenant_id` obrigatório em toda tabela `TENANT`, aplicado no ORM/repositório | **Row-Level Security (RLS)** nativa do Postgres como segunda barreira — mesmo uma query com bug de filtro não vaza, porque o banco recusa a linha fora da sessão de tenant |
| Qdrant | Filtro `tenant_id` obrigatório na assinatura da função de retrieval (não opcional) | Teste automatizado de isolamento (tenant A não pode recuperar chunk de tenant B) rodando em CI a cada mudança em `platform/retrieval` |
| MinIO/S3 | Prefixo de objeto por tenant (`tenant/{tenant_id}/...`) | Signed URLs de curta duração para acesso a documento, nunca URL pública permanente; policy de bucket nega leitura fora do prefixo do token |
| Redis | Toda chave prefixada por `tenant_id` quando o dado é de tenant | Nunca cache de dado de tenant sem prefixo, nem por engano em uma chave "global" mal nomeada |
| Jobs assíncronos | `tenant_id` é parte obrigatória do payload do job, carregado explicitamente no contexto de execução | Worker rejeita job sem `tenant_id` quando o tipo de job opera sobre dado de tenant |
| Logs | `tenant_id` como campo estruturado de log, nunca dado de outro tenant em mensagem de erro exposta ao usuário | Logs de erro para o usuário final nunca incluem stack trace ou payload cru |
| Memória do assistente | Ver [UX_AND_ASSISTANT_SPEC.md](UX_AND_ASSISTANT_SPEC.md) — contexto montado pelo backend, nunca aceito do cliente | Ferramentas do assistente não têm parâmetro de tenant arbitrário |

Isso é tratado como requisito estrutural, não como responsabilidade individual do desenvolvedor em
cada função — daí RLS como segunda barreira: mesmo um bug de aplicação não deve resultar em
vazamento, porque o banco também aplica a regra.

## Autenticação e autorização

- Autenticação: sessão/JWT de curta duração + refresh token, um usuário pertence a exatamente um
  tenant (ver [DOMAIN_MODEL.md](DOMAIN_MODEL.md) — simplifica isolamento).
- RBAC simples no MVP: `owner` (gerencia assinatura e usuários), `admin` (gerencia dados da empresa
  e usuários), `member` (opera oportunidades, sem gerenciar conta). Não construir motor de
  permissões granulares customizáveis sem demanda real validada (YAGNI).
- Toda rota de API valida `tenant_id` da entidade solicitada contra o `tenant_id` da sessão antes
  de retornar qualquer dado — mesmo que o ID do recurso tenha sido adivinhado/enumerado.

## Segredos e criptografia

- Segredos (credenciais de provider LLM, credenciais de BSP de WhatsApp, chaves de storage) em
  cofre de segredos do ambiente de deploy, nunca em código ou `.env` versionado.
- Dados sensíveis em repouso: criptografia do storage (MinIO/S3 com criptografia server-side) e do
  banco (criptografia de disco no provedor).
- Documentos de terceiros (editais, atestados de concorrentes) tratados com o mesmo rigor que
  documentos próprios do tenant, mesmo quando parcialmente públicos — o *cruzamento* feito pelo
  tenant sobre esse documento é informação privada dele.

## Uploads e proteção contra prompt injection via documento

Documentos enviados pelo usuário (e mesmo editais públicos) são tratados como **conteúdo não
confiável** ao entrarem no contexto de um LLM ou agente:

- Validação de tipo/tamanho/conteúdo de upload antes de qualquer processamento.
- Texto extraído de documento nunca é concatenado ao prompt do sistema como instrução — é sempre
  passado como dado delimitado, com o modelo instruído a tratá-lo como conteúdo a analisar, não
  como comando. Isso vale tanto para editais (que podem conter texto malicioso inserido de
  propósito) quanto para documentos de concorrentes enviados pelo usuário.
- Se conteúdo extraído contiver algo que se pareça com instrução dirigida ao assistente ("ignore as
  instruções anteriores", texto embutido em metadado de PDF, etc.), isso é tratado como sinal
  suspeito a ser logado, nunca executado.

## Agentes e ferramentas (seção 24)

- Todo agente opera com um conjunto **explícito e mínimo** de ferramentas por contexto de uso —
  nunca acesso genérico ao banco ou a um executor de SQL livre.
- Cada ferramenta declara: parâmetros aceitos (tipados, validados), efeito colateral (leitura vs.
  escrita), timeout, política de retry, e se requer confirmação humana antes de efeito colateral
  irreversível.
- Logs de toda chamada de ferramenta por agente, incluindo parâmetros e resultado, para auditoria e
  para depuração de "por que o assistente disse isso" (seção 25).
- Nenhuma ferramenta de agente tem `tenant_id` como parâmetro livre — é sempre injetado pelo
  runtime a partir da sessão autenticada (reforça o item de isolamento acima).

## Auditoria (`AuditLog`)

Eventos sempre auditados, com `tenant_id`, `user_id`, timestamp, e alvo da ação:

- Acesso a documento sensível (certidão, atestado, análise de preço).
- Mudança de permissão/papel de usuário.
- Decisão de negócio (`Decision`: participar/não participar).
- Qualquer sobrescrita manual de conclusão gerada pelo sistema.
- Exportação de dados (dossiê, relatório).

`AuditLog` é append-only, sem endpoint de edição/exclusão via aplicação.

## Rate limiting e proteção de API

- Rate limit por tenant e por usuário em endpoints de escrita e em endpoints que acionam
  processamento caro (ex.: "gerar análise").
- Idempotência obrigatória em endpoints que disparam job assíncrono caro, usando chave de
  idempotência fornecida pelo cliente ou derivada do estado (evita reprocessamento duplicado por
  duplo clique/retry de rede).

## Responsabilidade de conteúdo gerado (jurídico e preço)

Complementa [ADR-0006](adr/0006-legal-grounding-e-revisao-humana.md):

- Toda saída classificada como jurídica ou de precificação carrega, na própria estrutura de dados
  (não só na UI), um nível de confiança e a lista de evidências que a sustentam.
- Saídas sem evidência suficiente são marcadas `REQUIRES_HUMAN_REVIEW` e não podem ser
  apresentadas como conclusão definitiva na interface — aparecem com o rótulo de rascunho/sugestão.
- Termos de uso e disclaimers de produto deixam explícito que a plataforma é ferramenta de apoio à
  decisão, não assessoria jurídica ou garantia de resultado em licitação — isso é decisão de
  produto/jurídico do negócio, mas a arquitetura precisa suportar a exibição consistente desse aviso
  em todo ponto onde conteúdo jurídico aparece (não é responsabilidade só do time de marketing/legal
  colar um texto uma vez).

## LGPD

- Base legal e finalidade de tratamento documentadas por categoria de dado coletado (dados da
  empresa do tenant, dados de terceiros/concorrentes coletados de fonte pública, dados de uso da
  plataforma).
- Retenção de dados definida por categoria (ex.: logs de auditoria vs. documentos de análise vs.
  dados de sessão), não um prazo único genérico — a definir com o negócio antes da Fase 2, mas o
  schema já precisa ter campos de data de criação/expiração desde o início para não exigir migração
  retroativa dolorosa.
- Direito de exclusão do titular considerado desde o modelo: dado de terceiro (ex.: documento de
  concorrente coletado de fonte pública) precisa de trilha de origem para permitir resposta a
  eventual solicitação.
