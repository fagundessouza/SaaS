"""Testes dos providers de LLM contra respostas mockadas (respx) — sem credencial real, mesmo
padrao ja usado para os conectores de ingestao (ver tests/unit/test_pncp_connector.py). Cobre a
forma da requisicao/resposta de cada provider, nao o conteudo gerado por um modelo real (nenhuma
credencial de LLM existe neste ambiente, ver docs/phase-reports/FASE_9_REPORT.md).
"""

from __future__ import annotations

import httpx
import pytest
import respx

from ai_platform.llm.anthropic_provider import AnthropicProvider
from ai_platform.llm.openai_compatible_provider import OpenAICompatibleProvider
from ai_platform.llm.provider import (
    LLMMessage,
    LLMProviderError,
    LLMProviderNotConfiguredError,
    LLMRole,
    get_llm_provider,
)
from core.config import get_settings


@respx.mock
async def test_openai_compatible_provider_sends_correct_request_and_parses_response() -> None:
    route = respx.post("http://localhost:11434/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "resposta do modelo"}}]}
        )
    )

    provider = OpenAICompatibleProvider(
        base_url="http://localhost:11434/v1", api_key=None, model_name="llama-3.3-70b"
    )
    result = await provider.complete(
        [
            LLMMessage(role=LLMRole.SYSTEM, content="seja objetivo"),
            LLMMessage(role=LLMRole.USER, content="pergunta"),
        ],
        max_tokens=256,
    )

    assert result == "resposta do modelo"
    request = route.calls.last.request
    assert b'"model":"llama-3.3-70b"' in request.content
    assert "Authorization" not in request.headers


@respx.mock
async def test_openai_compatible_provider_sends_bearer_token_when_api_key_set() -> None:
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )
    )

    provider = OpenAICompatibleProvider(
        base_url="https://api.openai.com/v1", api_key="sk-test", model_name="gpt-4o"
    )
    await provider.complete([LLMMessage(role=LLMRole.USER, content="oi")], max_tokens=10)

    sent_headers = respx.calls.last.request.headers
    assert sent_headers["Authorization"] == "Bearer sk-test"


@respx.mock
async def test_openai_compatible_provider_raises_llm_provider_error_on_http_failure() -> None:
    respx.post("http://localhost:11434/v1/chat/completions").mock(
        return_value=httpx.Response(500)
    )

    provider = OpenAICompatibleProvider(
        base_url="http://localhost:11434/v1", api_key=None, model_name="llama"
    )
    with pytest.raises(LLMProviderError):
        await provider.complete([LLMMessage(role=LLMRole.USER, content="oi")], max_tokens=10)


@respx.mock
async def test_openai_compatible_provider_raises_on_malformed_response() -> None:
    respx.post("http://localhost:11434/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )

    provider = OpenAICompatibleProvider(
        base_url="http://localhost:11434/v1", api_key=None, model_name="llama"
    )
    with pytest.raises(LLMProviderError):
        await provider.complete([LLMMessage(role=LLMRole.USER, content="oi")], max_tokens=10)


@respx.mock
async def test_anthropic_provider_separates_system_from_messages() -> None:
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200, json={"content": [{"text": "resposta claude"}]}
        )
    )

    provider = AnthropicProvider(api_key="sk-ant-test", model_name="claude-sonnet-4-5")
    result = await provider.complete(
        [
            LLMMessage(role=LLMRole.SYSTEM, content="seja objetivo"),
            LLMMessage(role=LLMRole.USER, content="pergunta"),
        ],
        max_tokens=256,
    )

    assert result == "resposta claude"
    request = route.calls.last.request
    assert request.headers["x-api-key"] == "sk-ant-test"
    body = request.content
    assert b'"system":"seja objetivo"' in body
    assert b'"role":"system"' not in body  # system nao entra no array messages da Anthropic


def test_get_llm_provider_raises_when_openai_compatible_without_model_name() -> None:
    get_settings.cache_clear()
    get_llm_provider.cache_clear()
    try:
        with pytest.raises(LLMProviderNotConfiguredError):
            get_llm_provider()
    finally:
        get_settings.cache_clear()
        get_llm_provider.cache_clear()
