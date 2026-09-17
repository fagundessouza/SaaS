"""Interface de provider de embeddings (ver ADR-0003: fina, nao especulativa).

Um unico provider concreto por enquanto (self-hosted, `fastembed_provider.py`) — um segundo
(API externa) so entra quando houver necessidade real de comparar custo/qualidade contra dados
de uso real, nao especulativamente (mesmo principio ja aplicado a `core/llm` — ver ADR-0003).
"""

from __future__ import annotations

from typing import Protocol


class EmbeddingProvider(Protocol):
    model_name: str
    dimension: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
