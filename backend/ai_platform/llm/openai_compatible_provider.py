"""Provider compativel com o padrao OpenAI `/v1/chat/completions` — cobre tanto a API da OpenAI
quanto qualquer servidor self-hosted que fale o mesmo protocolo (Ollama, vLLM, LM Studio,
text-generation-inference, etc.), configurado so pela troca de `base_url`/`api_key`/`model_name`
(ver docstring de provider.py e ADR-0003).
"""

from __future__ import annotations

import httpx

from ai_platform.llm.provider import LLMMessage, LLMProviderError

_TIMEOUT_SECONDS = 60.0


class OpenAICompatibleProvider:
    def __init__(self, *, base_url: str, api_key: str | None, model_name: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.model_name = model_name

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> str:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            # Servidor self-hosted sem autenticacao (comum em Ollama/vLLM local) nao exige
            # header nenhum — so envia Authorization quando ha uma chave de verdade.
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = {
            "model": self.model_name,
            "messages": [{"role": m.role.value, "content": m.content} for m in messages],
            "max_tokens": max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions", json=payload, headers=headers
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"Falha ao chamar {self._base_url}: {exc}") from exc

        body = response.json()
        try:
            return str(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError(f"Resposta inesperada do provider: {body}") from exc
