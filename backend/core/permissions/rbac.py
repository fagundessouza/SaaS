"""Checagem pura de RBAC — sem FastAPI, sem banco. A dependencia HTTP que usa isto vive em
api/deps.py (mesma separacao de core/auth/security.py vs core/auth/service.py).
"""

from __future__ import annotations

from core.auth.models import Role


class PermissionDeniedError(Exception):
    def __init__(self, role: Role, allowed: tuple[Role, ...]) -> None:
        self.role = role
        self.allowed = allowed
        super().__init__(f"Papel '{role.value}' nao autorizado (requer um de {allowed})")


def ensure_role(role: Role, *allowed: Role) -> None:
    if role not in allowed:
        raise PermissionDeniedError(role, allowed)
