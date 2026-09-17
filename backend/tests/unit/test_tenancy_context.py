import uuid

import pytest

from core.tenancy.context import (
    TenantContextError,
    get_current_tenant_id,
    get_current_tenant_id_or_none,
    tenant_scope,
)


def test_get_current_tenant_id_raises_without_scope() -> None:
    with pytest.raises(TenantContextError):
        get_current_tenant_id()


def test_get_current_tenant_id_or_none_returns_none_without_scope() -> None:
    assert get_current_tenant_id_or_none() is None


def test_tenant_scope_sets_and_resets_context() -> None:
    tenant_id = uuid.uuid4()

    assert get_current_tenant_id_or_none() is None
    with tenant_scope(tenant_id):
        assert get_current_tenant_id() == tenant_id
    assert get_current_tenant_id_or_none() is None


def test_nested_tenant_scope_restores_outer_value() -> None:
    outer = uuid.uuid4()
    inner = uuid.uuid4()

    with tenant_scope(outer):
        with tenant_scope(inner):
            assert get_current_tenant_id() == inner
        assert get_current_tenant_id() == outer
