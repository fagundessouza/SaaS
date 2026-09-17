"""Busca semantica no Global Knowledge Layer — qualquer usuario autenticado pode consultar,
porque o conteudo indexado e sempre GLOBAL/publico (editais ja ingeridos, ver
domains/procurement/tenders). Nao ha escopo de tenant aqui de proposito (ver ADR-0005).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ai_platform.retrieval.search import search_global_knowledge
from api.deps import CurrentUser, get_current_user

router = APIRouter(prefix="/v1/knowledge", tags=["knowledge"])


class SearchResultResponse(BaseModel):
    document_id: UUID
    document_version_id: UUID
    section: str | None
    heading_path: list[str]
    chunk_type: str
    page_start: int
    page_end: int
    content: str
    score: float

    model_config = {"from_attributes": True}


@router.get("/search", response_model=list[SearchResultResponse])
async def search(
    q: str = Query(min_length=3, max_length=500),
    limit: int = Query(default=5, ge=1, le=20),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[SearchResultResponse]:
    results = await search_global_knowledge(q, limit=limit)
    return [SearchResultResponse.model_validate(r) for r in results]
