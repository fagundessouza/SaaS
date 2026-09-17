"""JobRun — rastreamento de execucao de job assincrono, por tenant (RLS habilitado).

E o exemplo de referencia da Fase 1 para "job assincrono rodando fim a fim e visivel em
metricas" (ver docs/IMPLEMENTATION_ROADMAP.md, criterio de saida da Fase 1).
"""

from __future__ import annotations

import enum
from typing import Any

from sqlalchemy import Enum, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, IdMixin, TenantScopedMixin, TimestampMixin


class JobStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobRun(IdMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "job_runs"

    job_type: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), nullable=False, default=JobStatus.PENDING
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
