"""assistant: assistant_sessions, assistant_messages (fase 9)

Revision ID: 06755c28507c
Revises: 02ef8d69ba9c
Create Date: 2026-09-17 22:43:22.525593

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "06755c28507c"
down_revision: str | None = "02ef8d69ba9c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Ambas as tabelas desta migration sao TENANT (ver docs/DOMAIN_MODEL.md) — RLS aplicado
# individualmente (defesa em profundidade, mesmo padrao ja usado nas Fases 7/8/10).
_RLS_TABLES = ("assistant_sessions", "assistant_messages")


def upgrade() -> None:
    op.create_table(
        "assistant_sessions",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("opportunity_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_assistant_sessions_opportunity_id"),
        "assistant_sessions",
        ["opportunity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_assistant_sessions_tenant_id"), "assistant_sessions", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_assistant_sessions_user_id"), "assistant_sessions", ["user_id"], unique=False
    )
    op.create_table(
        "assistant_messages",
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column(
            "role", sa.Enum("USER", "ASSISTANT", name="assistant_message_role"), nullable=False
        ),
        sa.Column(
            "action",
            sa.Enum(
                "MISSING_REQUIREMENTS",
                "UNDERSTAND_TENDER",
                "EXPLAIN_REQUIREMENT",
                name="assistant_action",
            ),
            nullable=True,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["assistant_sessions.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_assistant_messages_session_id"), "assistant_messages", ["session_id"], unique=False
    )
    op.create_index(
        op.f("ix_assistant_messages_tenant_id"), "assistant_messages", ["tenant_id"], unique=False
    )

    # --- RLS (ver ADR-0002 e SECURITY_MODEL.md) ---
    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON {table}
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
            """
        )


def downgrade() -> None:
    for table in _RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index(op.f("ix_assistant_messages_tenant_id"), table_name="assistant_messages")
    op.drop_index(op.f("ix_assistant_messages_session_id"), table_name="assistant_messages")
    op.drop_table("assistant_messages")
    op.drop_index(op.f("ix_assistant_sessions_user_id"), table_name="assistant_sessions")
    op.drop_index(op.f("ix_assistant_sessions_tenant_id"), table_name="assistant_sessions")
    op.drop_index(op.f("ix_assistant_sessions_opportunity_id"), table_name="assistant_sessions")
    op.drop_table("assistant_sessions")

    # op.drop_table nao remove o tipo ENUM associado (ver migrations anteriores).
    op.execute("DROP TYPE IF EXISTS assistant_message_role")
    op.execute("DROP TYPE IF EXISTS assistant_action")
