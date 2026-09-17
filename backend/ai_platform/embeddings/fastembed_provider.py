"""Provider de embeddings local via fastembed (ONNX Runtime — sem PyTorch, sem GPU). Ver
core/config.py (`embedding_model_name`) para o modelo default e a justificativa da escolha
(multilingue, leve o suficiente para CPU em tempo de dev razoavel).

`TextEmbedding.embed()` do fastembed e sincrono/CPU-bound — rodado em thread separada
(`asyncio.to_thread`) para nao bloquear o event loop, mesmo padrao usado para outras chamadas
sincronas pesadas no projeto (ex.: boto3 em core/storage/client.py).
"""

from __future__ import annotations

import asyncio

from fastembed import TextEmbedding

from core.config import get_settings


class UnknownEmbeddingModelError(Exception):
    pass


def _model_dimension(model_name: str) -> int:
    for model in TextEmbedding.list_supported_models():
        if model["model"] == model_name:
            return int(model["dim"])
    raise UnknownEmbeddingModelError(f"Modelo de embedding desconhecido: {model_name}")


class FastEmbedProvider:
    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or get_settings().embedding_model_name
        self.dimension = _model_dimension(self.model_name)
        self._model = TextEmbedding(model_name=self.model_name)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        def _embed_sync() -> list[list[float]]:
            return [vector.tolist() for vector in self._model.embed(texts)]

        return await asyncio.to_thread(_embed_sync)


_provider: FastEmbedProvider | None = None


def get_embedding_provider() -> FastEmbedProvider:
    global _provider
    if _provider is None:
        _provider = FastEmbedProvider()
    return _provider
