"""Assistente contextual (Fase 9, ver docs/UX_AND_ASSISTANT_SPEC.md). Cada acao e uma chamada de
ferramenta deterministica — o cliente nunca manda um prompt livre, so `opportunity_id` +
`action` (+ `requirement_id` quando a acao exige). O contexto (tenant, usuario) vem
exclusivamente da sessao autenticada, nunca de parametro do cliente (mesma restricao de
seguranca explicita da spec).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ai_platform.llm.provider import LLMProviderError, LLMProviderNotConfiguredError
from api.deps import CurrentUser, get_current_user
from domains.assistant.models import AssistantAction, AssistantMessageRole
from domains.assistant.service import (
    OpportunityNotFoundError,
    RequirementNotFoundError,
    run_action,
)

router = APIRouter(prefix="/v1/assistant", tags=["assistant"])


class RunActionRequest(BaseModel):
    opportunity_id: UUID
    action: AssistantAction
    requirement_id: UUID | None = None


class AssistantMessageResponse(BaseModel):
    id: UUID
    role: AssistantMessageRole
    action: AssistantAction | None
    content: str
    evidence_refs: list[dict[str, Any]]
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post("/actions", response_model=AssistantMessageResponse, status_code=201)
async def execute_action(
    payload: RunActionRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> AssistantMessageResponse:
    try:
        message = await run_action(
            tenant_id=current_user.tenant_id,
            user_id=current_user.user_id,
            opportunity_id=payload.opportunity_id,
            action=payload.action,
            requirement_id=payload.requirement_id,
        )
    except (OpportunityNotFoundError, RequirementNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Recurso não encontrado") from exc
    except LLMProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=503, detail=f"Assistente indisponível: {exc}"
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=502, detail=f"Falha ao consultar o provedor de LLM: {exc}"
        ) from exc

    return AssistantMessageResponse.model_validate(message)
