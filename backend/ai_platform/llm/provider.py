"""Interface de provider de LLM — fina, nao especulativa (ver ADR-0003, mesmo raciocinio ja
aplicado a EmbeddingProvider na Fase 5). Contrato minimo: so `complete` (sem `stream` ainda —
nenhuma tela deste projeto precisa de token-a-token ainda; adicionar quando houver, nao antes).

Nenhum dominio de negocio importa um SDK de provider diretamente, sempre atraves desta interface
— o que torna trocar de provider (ou adicionar um novo) um adapter novo atras da interface
existente, nunca um refactor de dominio (ver docs/adr/0003-llm-embedding-provider-abstraction.md).

Dois providers concretos: um de API externa (`AnthropicProvider`) e um compativel com o padrao
OpenAI `/v1/chat/completions` (`OpenAICompatibleProvider`) — que cobre tanto a propria API da
OpenAI quanto qualquer servidor self-hosted que fale o mesmo protocolo (Ollama, vLLM, LM Studio,
text-generation-inference, etc., ver ADR-0003: "self-hosted compativel com Ollama para modelos
como Qwen/DeepSeek"). A escolha entre eles — e entre modelo/tamanho de parametros — e inteira do
usuario via configuracao (`LLM_PROVIDER`/`LLM_BASE_URL`/`LLM_MODEL_NAME`, ver core/config.py),
nunca hardcoded: o mesmo hardware que roda um modelo de 2B hoje pode rodar um de 128B amanha, ou
o usuario pode trocar para um plano de API diferente — nenhum dos dois exige mudar codigo.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol


class LLMRole(enum.StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class LLMMessage:
    role: LLMRole
    content: str


class LLMProviderError(Exception):
    """Falha ao chamar o provider (rede, autenticacao, resposta malformada) — nunca deixada
    propagar como uma excecao generica para quem chama `complete`, para que o consumidor (ver
    domains/assistant/service.py) possa distinguir "sem provider configurado" de "provider
    configurado mas indisponivel agora"."""


class LLMProviderNotConfiguredError(LLMProviderError):
    """Nenhum provider configurado neste ambiente (sem API key nem base_url self-hosted) — ao
    contrario dos canais "console" do Notification Engine (Fase 10), um Assistente que nao pode
    responder de verdade nao tem um modo "log em vez de enviar" que faca sentido: falha de forma
    explicita, nunca finge uma resposta."""


class LLMProvider(Protocol):
    model_name: str

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> str: ...


@lru_cache
def get_llm_provider() -> LLMProvider:
    from core.config import get_settings

    settings = get_settings()

    if settings.llm_provider == "anthropic":
        if not settings.llm_api_key:
            raise LLMProviderNotConfiguredError(
                "LLM_PROVIDER=anthropic requer LLM_API_KEY configurada."
            )
        from ai_platform.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            api_key=settings.llm_api_key,
            model_name=settings.llm_model_name or "claude-sonnet-4-5",
        )

    if settings.llm_provider == "openai_compatible":
        from ai_platform.llm.openai_compatible_provider import OpenAICompatibleProvider

        if not settings.llm_model_name:
            raise LLMProviderNotConfiguredError(
                "LLM_PROVIDER=openai_compatible requer LLM_MODEL_NAME configurado (nome do "
                "modelo servido pelo endpoint em LLM_BASE_URL)."
            )
        return OpenAICompatibleProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model_name=settings.llm_model_name,
        )

    raise LLMProviderNotConfiguredError(
        f"LLM_PROVIDER='{settings.llm_provider}' desconhecido (esperado 'anthropic' ou "
        "'openai_compatible')."
    )
