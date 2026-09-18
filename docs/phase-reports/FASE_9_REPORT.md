# Relatório de Checkpoint — Fase 9 (Assistente)

Ver critério de saída em [IMPLEMENTATION_ROADMAP.md](../IMPLEMENTATION_ROADMAP.md#fase-9--assistente-escopo-mínimo-contexto-de-tela--ações-da-fase-78):
"assistente responde 'o que está faltando?' citando evidência real do dossiê da Fase 8."

## IMPLEMENTADO

- `ai_platform/llm/provider.py`: `LLMProvider` (Protocol, contrato mínimo — só `complete`, sem
  `stream` ainda, ver ADR-0003) + `get_llm_provider()`, fábrica configurável por `LLM_PROVIDER`.
  **Decisão explícita do usuário** (retomando a Fase 9 depois de adiada): arquitetura híbrida
  plugável — qualquer modelo self-hosted (Ollama, vLLM, LM Studio, de 2B a 128B+ parâmetros,
  dependendo do hardware que o usuário tiver no momento) ou de API externa, trocável só por
  configuração, nunca por mudança de código.
- `ai_platform/llm/openai_compatible_provider.py`: um único provider cobrindo tanto a API da
  OpenAI quanto **qualquer servidor self-hosted que fale o protocolo `/v1/chat/completions`**
  (Ollama, vLLM, LM Studio, text-generation-inference etc.) — só troca `base_url`/`api_key`/
  `model_name`. `ai_platform/llm/anthropic_provider.py`: API da Anthropic (Messages API, formato
  diferente — `system` separado do array de mensagens). Os dois via `httpx` direto, sem SDK
  pesado (mesmo raciocínio dos conectores de ingestão).
- `domains/assistant/`: `AssistantSession`/`AssistantMessage` (ver DOMAIN_MODEL.md) e
  `run_action()` — ponto de entrada único, 3 ações (das ~6 sugeridas na spec, escopo mínimo
  "3-4, não todas de uma vez"):
  1. **`missing_requirements`** ("O que está faltando?", exigida pelo critério de saída) — gera
     a `Analysis` sob demanda se ainda não existir, lista todo `Finding` com status ≠ `MET`.
  2. **`understand_tender`** ("Entender edital") — resumo do `Tender` + `TenderItem`.
  3. **`explain_requirement`** ("Explicar este requisito") — um `Requirement` específico.
  Cada ação é uma chamada de ferramenta determinística (nunca um prompt livre reinterpretado, ver
  UX_AND_ASSISTANT_SPEC.md) — o contexto vem de query determinística contra dado já existente
  (Fase 6/8), o LLM só sintetiza a linguagem natural sobre fatos já corretos; a citação
  estruturada (`evidence_refs`) é sempre gerada por código, nunca extraída do texto do LLM (ADR-0007:
  IA sintetiza, o dado estruturado vem do banco).
- `api/v1/assistant.py`: `POST /v1/assistant/actions` — `opportunity_id` + `action` (+
  `requirement_id` quando a ação exige), nunca aceita contexto de tenant do cliente (mesma
  restrição de segurança explícita da spec). `503` quando nenhum provider está configurado,
  `502` quando o provider configurado falha ao responder — nunca finge uma resposta.
- `core/config.py`: `LLM_PROVIDER`/`LLM_MODEL_NAME`/`LLM_API_KEY`/`LLM_BASE_URL`/
  `LLM_MAX_TOKENS`. Nenhuma credencial real configurada neste ambiente (ver RISCOS).

## AMBIENTE (setup real)

Smoke test manual de ponta a ponta com um `LLMProvider` falso e determinístico antes de escrever
qualquer teste formal (mesma disciplina das fases anteriores): as 3 ações rodaram contra dado
real (Tender/TenderItem/Requirement/Analysis já existentes das Fases 6/7/8), citação correta em
cada uma, e a mesma `AssistantSession` foi reaproveitada entre ações do mesmo usuário+oportunidade.

## TESTADO

- `ruff`, `mypy --strict`, `import-linter` — limpos (171 arquivos-fonte).
- Migration (`assistant_sessions`, `assistant_messages`, RLS nas 2, 2 ENUMs novos)
  `upgrade`/`downgrade`/`upgrade` — reversível.
- `pytest -v` — **179 testes passando**, três rodadas consecutivas (59s/57s/57s).
  - `tests/unit/test_llm_providers.py` (6 testes, respx — sem credencial real): forma da
    requisição/resposta de cada provider (OpenAI-compatible com e sem `api_key`, Anthropic
    separando `system`), erro claro em falha HTTP e em resposta malformada, fábrica levanta
    `LLMProviderNotConfiguredError` no estado padrão (sem `LLM_MODEL_NAME`).
  - `tests/integration/test_assistant_service.py` (5 testes, Postgres real + LLM fake): "o que
    está faltando" gera a Analysis sob demanda e cita evidência real; "entender edital" cita
    Tender + contagem de itens; "explicar requisito" cita seção/página; erro claro para
    requisito inexistente; sessão reaproveitada entre ações do mesmo usuário+oportunidade.
  - `tests/integration/test_assistant_api.py` (4 testes): exige autenticação; 404 para
    oportunidade inexistente; **503 no estado padrão real deste ambiente** (sem credencial
    configurada); **caminho feliz completo via HTTP mockado** (settings configuradas +
    `respx` no endpoint `/chat/completions`) — prova que a rota liga `run_action` →
    `get_llm_provider()` → o provider de verdade ponta a ponta.
  - `tests/security/test_assistant_isolation.py` (1 teste): as 2 tabelas novas isoladas por
    tenant via RLS.

## PROBLEMAS (encontrados e corrigidos durante esta fase)

Nenhum bug de código novo encontrado nesta fase — dois erros de asserção nos próprios testes
(não no código): (1) o teste de "o que está faltando" checava um trecho do texto do requisito
que na verdade não aparece no resumo de um `Finding` `MISSING` (o resumo determinístico cita a
ausência de certidão, não o texto do requisito em si); (2) três testes truncavam
`unique_text(...)[:20]` de forma que cortava o sufixo aleatório inteiro antes dele aparecer,
colidindo `content_hash` entre execuções — corrigido usando `uuid.uuid4().hex[:8]` direto para o
marcador, sem o corte acidental.

## RISCOS

- **Nenhum provider real foi exercitado com credencial de verdade** — os dois providers são
  testados contra HTTP mockado (forma da requisição/resposta correta), nunca contra um modelo
  real respondendo. O usuário precisa validar isso ao configurar `LLM_API_KEY` ou um servidor
  self-hosted real pela primeira vez.
- O prompt de sistema instrui o modelo a "nunca inventar dado fora do contexto" e "nunca afirmar
  conclusão jurídica definitiva" — isso é uma instrução ao modelo, não uma garantia estrutural
  como a fronteira regra-vs-IA do resto do projeto. Diferente de, por exemplo, `Certificate` vs.
  `Requirement` (Fase 8), aqui não há um mecanismo determinístico que impeça o modelo de alucinar
  além do que os `evidence_refs` (gerados por código, não pelo LLM) já garantem estarem corretos
  — o texto sintetizado em si não é verificado.
- Sem memória de longo prazo entre sessões (deliberado, ver DECISÕES) — cada
  `AssistantSession` é só o histórico daquela oportunidade, não aprende com feedback entre
  tenants nem entre oportunidades diferentes do mesmo tenant.
- `ai_platform/llm/provider.py` importa `ai_platform.llm.anthropic_provider`/
  `openai_compatible_provider` dinamicamente dentro de `get_llm_provider()` (não no topo do
  módulo) — evita importar `httpx`/os dois providers concretos quando nenhum é usado, mas é um
  padrão levemente incomum neste código-base; revisar se isso causar confusão de manutenção.

## DECISÕES

- **Arquitetura híbrida plugável para o provider de LLM, por pedido explícito do usuário**: a
  Fase 9 tinha sido adiada por depender de uma decisão de provider — o usuário pediu
  especificamente para poder trocar entre qualquer LLM self-hosted (2B, 4B, 35B, 128B+
  parâmetros, dependendo do hardware disponível no momento) ou de nuvem, sem travar em um único
  fornecedor. Resolvido com o padrão já estabelecido pelo ADR-0003 (que já previa exatamente
  isso desde a Fase 0) — `LLMProvider` Protocol + `OpenAICompatibleProvider` (cobre self-hosted
  via qualquer servidor OpenAI-compatible) + `AnthropicProvider` (API externa).
- **`OpenAICompatibleProvider` único para self-hosted E nuvem OpenAI**: em vez de um adapter por
  motor de inferência (Ollama, vLLM, LM Studio...), um só provider parametrizado por `base_url`
  — todos esses servidores falam o mesmo protocolo REST, então a escolha de qual rodar é
  inteiramente do usuário/infraestrutura, nunca do código.
- **Sem modo "console" para o Assistente** (diferente do Notification Engine, Fase 10): um
  assistente que não pode responder de verdade não tem um "log em vez de responder" que sirva ao
  usuário — falha explícita (`LLMProviderNotConfiguredError` → 503), nunca finge uma resposta.
- **3 ações, não as ~6 sugeridas na spec**: as que já têm dado real disponível (Fase 6/8) sem
  depender de Legal/Pricing (Fase 12, ainda não implementada — ver decisão de adiá-la também
  nesta sessão). "Analisar preço"/"Ver riscos"/"Comparar histórico" ficam para quando essas
  fases existirem.
- **Sem memória de longo prazo entre sessões**: DOMAIN_MODEL.md já registrava isso como
  responsabilidade de uma camada futura sobre `TenantKnowledge`/`Feedback`/`Decision` (Fase 14,
  Feedback & Learning) — implementar antes disso seria construir sobre uma base que ainda não
  existe.
- **Frontend (botão flutuante) continua fora do escopo**: mesma decisão já tomada quando a Fase
  9 foi adiada ("só backend por enquanto") — só o retomar do provider de LLM foi pedido
  explicitamente, não o frontend.

## PENDÊNCIAS

1. Validar `SmtpEmailChannel`-equivalente para LLM (`OpenAICompatibleProvider`/
   `AnthropicProvider`) contra um modelo real (self-hosted ou de API) assim que houver
   credencial/servidor disponível — hoje só o formato da requisição/resposta foi testado.
2. Adicionar `stream` ao `LLMProvider` quando houver uma tela real precisando de token-a-token
   (não antes — mesmo princípio "é barato definir, caro remendar depois" já citado no ADR-0003,
   mas sem construir especulativamente o que nada consome ainda).
3. Calibrar/testar o prompt de sistema contra respostas reais de diferentes modelos (o
   comportamento de "nunca inventar" varia por modelo e não há garantia estrutural, ver RISCOS).
4. Ações adicionais ("Analisar preço", "Ver riscos", "Comparar histórico") quando Legal/Pricing
   (Fase 12) e Competitive Intelligence (Fase 13) existirem.

## PRÓXIMA FASE

Fases 12/13 (Legal Intelligence + Pricing Engine, Competitive Intelligence) continuam
bloqueadas por dependerem de base jurídica curada real e de cliente piloto real (ver decisão
tomada nesta sessão antes de retomar a Fase 9). Fase 11 (Frontend) segue adiada por decisão do
usuário. Próximos passos backend-only viáveis: Fase 14 (Feedback + Learning, infraestrutura de
loop de feedback sem exigir cliente piloto real ainda) ou Fase 15 (Observability + Security
hardening).
