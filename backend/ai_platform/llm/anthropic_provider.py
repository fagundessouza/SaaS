"""Provider da API da Anthropic (Messages API) — via `httpx` direto, sem SDK pesado (mesmo
raciocinio ja aplicado aos conectores de ingestao, ver ingestion/connectors/pncp.py: uma chamada
REST simples nao justifica uma dependencia nova so por conveniencia).
"""

from __future__ import annotations

import httpx

from ai_platform.llm.provider import LLMMessage, LLMProviderError, LLMRole

_TIMEOUT_SECONDS = 60.0
_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"


class AnthropicProvider:
    def __init__(self, *, api_key: str, model_name: str) -> None:
        self._api_key = api_key
        self.model_name = model_name

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> str:
        # Messages API separa `system` do array `messages` (diferente do formato OpenAI, onde o
        # system entra como uma mensagem de role "system" no mesmo array).
        system_messages = [m.content for m in messages if m.role == LLMRole.SYSTEM]
        conversation = [
            {"role": m.role.value, "content": m.content}
            for m in messages
            if m.role != LLMRole.SYSTEM
        ]

        payload: dict[str, object] = {
            "model": self.model_name,
            "max_tokens": max_tokens,
            "messages": conversation,
        }
        if system_messages:
            payload["system"] = "\n\n".join(system_messages)

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.post(_API_URL, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"Falha ao chamar a API da Anthropic: {exc}") from exc

        body = response.json()
        try:
            return str(body["content"][0]["text"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError(f"Resposta inesperada da API da Anthropic: {body}") from exc
