"""Health check — SYNC, sem tenant, sem tocar em nada caro (ver ADR-0008)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
