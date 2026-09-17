"""Inbox de Alert/Notification, preferencias de canal e assinaturas de Web Push do usuario
corrente (Fase 10, ver core/notifications/)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import CurrentUser, get_current_user
from core.notifications.models import DeliveryStatus, NotificationChannelType
from core.notifications.preferences_service import list_preferences, set_preference
from core.notifications.push_subscriptions_service import (
    PushSubscriptionNotFoundError,
    create_push_subscription,
    delete_push_subscription,
)
from core.notifications.service import list_alerts_for_user

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])


class NotificationDeliveryResponse(BaseModel):
    channel: NotificationChannelType
    status: DeliveryStatus
    sent_at: datetime | None
    error: str | None

    model_config = {"from_attributes": True}


class AlertResponse(BaseModel):
    id: UUID
    topic: str
    payload: dict[str, Any]
    created_at: datetime
    deliveries: list[NotificationDeliveryResponse]


class PreferenceResponse(BaseModel):
    topic: str
    channel: NotificationChannelType
    enabled: bool

    model_config = {"from_attributes": True}


class SetPreferenceRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=120)
    channel: NotificationChannelType
    enabled: bool


class PushSubscriptionResponse(BaseModel):
    id: UUID
    endpoint: str

    model_config = {"from_attributes": True}


class CreatePushSubscriptionRequest(BaseModel):
    endpoint: str = Field(min_length=1)
    p256dh_key: str = Field(min_length=1)
    auth_key: str = Field(min_length=1)


@router.get("", response_model=list[AlertResponse])
async def list_notifications(
    current_user: CurrentUser = Depends(get_current_user),
) -> list[AlertResponse]:
    rows = await list_alerts_for_user(user_id=current_user.user_id)
    return [
        AlertResponse(
            id=alert.id,
            topic=alert.topic,
            payload=alert.payload,
            created_at=alert.created_at,
            deliveries=[NotificationDeliveryResponse.model_validate(n) for n in notifications],
        )
        for alert, notifications in rows
    ]


@router.get("/preferences", response_model=list[PreferenceResponse])
async def get_preferences(
    current_user: CurrentUser = Depends(get_current_user),
) -> list[PreferenceResponse]:
    preferences = await list_preferences(user_id=current_user.user_id)
    return [PreferenceResponse.model_validate(p) for p in preferences]


@router.put("/preferences", response_model=PreferenceResponse)
async def update_preference(
    payload: SetPreferenceRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> PreferenceResponse:
    preference = await set_preference(
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        topic=payload.topic,
        channel=payload.channel,
        enabled=payload.enabled,
    )
    return PreferenceResponse.model_validate(preference)


@router.post("/push-subscriptions", response_model=PushSubscriptionResponse, status_code=201)
async def add_push_subscription(
    payload: CreatePushSubscriptionRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> PushSubscriptionResponse:
    subscription = await create_push_subscription(
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        endpoint=payload.endpoint,
        p256dh_key=payload.p256dh_key,
        auth_key=payload.auth_key,
    )
    return PushSubscriptionResponse.model_validate(subscription)


@router.delete("/push-subscriptions/{subscription_id}", status_code=204)
async def remove_push_subscription(
    subscription_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
) -> None:
    try:
        await delete_push_subscription(subscription_id=subscription_id)
    except PushSubscriptionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Assinatura nao encontrada") from exc
