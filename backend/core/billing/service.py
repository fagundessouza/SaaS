"""Orquestracao de billing: plano default de trial e checagem de limites (entitlements).

Sem gateway de pagamento real nesta fase (ver docs/00-CRITICAL_ANALYSIS.md, item 3 da tabela de
ambiguidades) — toda Subscription criada aqui nasce em trial, sem cobranca associada.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.models import User
from core.billing.models import Plan, Subscription, SubscriptionStatus

TRIAL_PLAN_CODE = "trial"


class PlanNotConfiguredError(RuntimeError):
    """A plataforma nao tem um plano de trial cadastrado — falha de setup, nao de usuario."""


async def get_trial_plan(session: AsyncSession) -> Plan:
    result = await session.execute(select(Plan).where(Plan.code == TRIAL_PLAN_CODE))
    plan = result.scalar_one_or_none()
    if plan is None:
        raise PlanNotConfiguredError(
            f"Plano '{TRIAL_PLAN_CODE}' nao encontrado — rode as migrations/seed de billing."
        )
    return plan


def new_trial_subscription(tenant_id: uuid.UUID, plan_id: uuid.UUID) -> Subscription:
    return Subscription(tenant_id=tenant_id, plan_id=plan_id, status=SubscriptionStatus.TRIALING)


class NoActiveSubscriptionError(RuntimeError):
    pass


async def get_active_plan(session: AsyncSession, tenant_id: uuid.UUID) -> Plan:
    """Le a Subscription do tenant corrente (RLS ja restringe ao tenant ativo da sessao) e o
    Plan associado. Chamar dentro de um `tenant_session()` do tenant em questao.
    """
    result = await session.execute(
        select(Plan)
        .join(Subscription, Subscription.plan_id == Plan.id)
        .where(Subscription.tenant_id == tenant_id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        raise NoActiveSubscriptionError(f"Tenant {tenant_id} nao possui Subscription")
    return plan


class UserLimitReachedError(RuntimeError):
    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(f"Limite de {limit} usuarios do plano atingido")


async def ensure_user_limit_not_reached(
    session: AsyncSession, tenant_id: uuid.UUID, plan: Plan
) -> None:
    max_users = plan.limits.get("max_users")
    if max_users is None:
        return  # plano sem limite explicito de usuarios

    result = await session.execute(
        select(func.count()).select_from(User).where(User.tenant_id == tenant_id)
    )
    current_count = result.scalar_one()
    if current_count >= max_users:
        raise UserLimitReachedError(max_users)
