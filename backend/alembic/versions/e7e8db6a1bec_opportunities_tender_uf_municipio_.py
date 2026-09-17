"""opportunities + tender uf/municipio + company products/services (fase 7)

Revision ID: e7e8db6a1bec
Revises: 4f7180d7c953
Create Date: 2026-09-17 14:48:28.137199

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7e8db6a1bec"
down_revision: str | None = "4f7180d7c953"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RLS_TABLES = ("opportunities", "opportunity_matches")


def upgrade() -> None:
    op.create_table(
        "opportunities",
        sa.Column("tender_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "DISCOVERED",
                "UNDER_REVIEW",
                "QUALIFIED",
                "PURSUING",
                "SUBMITTED",
                "WON",
                "LOST",
                "WITHDRAWN",
                name="opportunity_status",
            ),
            nullable=False,
        ),
        sa.Column("assigned_to_user_id", sa.UUID(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["assigned_to_user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"],
            ["tenders.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "tender_id", name="uq_opportunities_tenant_tender"),
    )
    op.create_index(op.f("ix_opportunities_status"), "opportunities", ["status"], unique=False)
    op.create_index(
        op.f("ix_opportunities_tenant_id"), "opportunities", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_opportunities_tender_id"), "opportunities", ["tender_id"], unique=False
    )
    op.create_table(
        "opportunity_matches",
        sa.Column("opportunity_id", sa.UUID(), nullable=False),
        sa.Column("compatibility", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("opportunity_id", name="uq_opportunity_matches_opportunity"),
    )
    op.create_index(
        op.f("ix_opportunity_matches_opportunity_id"),
        "opportunity_matches",
        ["opportunity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_opportunity_matches_tenant_id"),
        "opportunity_matches",
        ["tenant_id"],
        unique=False,
    )

    # server_default so para as linhas existentes (ha CompanyProfile em uso desde a Fase 2) —
    # removido em seguida porque o modelo usa default Python (list), nao server_default. Mesmo
    # padrao da migration 751d998f6213 (page_texts, Fase 5).
    for column in ("products", "services"):
        op.add_column(
            "company_profiles",
            sa.Column(
                column,
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="[]",
            ),
        )
        op.alter_column("company_profiles", column, server_default=None)

    op.add_column("tenders", sa.Column("uf", sa.String(length=2), nullable=True))
    op.add_column("tenders", sa.Column("municipio", sa.String(length=120), nullable=True))
    op.create_index(op.f("ix_tenders_uf"), "tenders", ["uf"], unique=False)

    # --- Backfill de uf/municipio a partir do raw_payload ja ingerido (Fases 3-6) ---
    # Sem isto, todo Tender ingerido antes desta migration ficaria com uf NULL e seria descartado
    # pelo filtro de regiao de qualquer tenant que declare UFs (ver _evaluate_region em
    # domains/procurement/opportunities/matching.py) — o Opportunity Engine nasceria cego para
    # todo o acervo ja ingerido. O dado sempre existiu, so estava inacessivel para filtro dentro
    # do JSONB de TenderVersion. DISTINCT ON pega a versao mais recente de cada Tender.
    op.execute(
        """
        UPDATE tenders t
        SET uf = LEFT(v.uf, 2),
            municipio = LEFT(v.municipio, 120)
        FROM (
            SELECT DISTINCT ON (tv.tender_id)
                   tv.tender_id,
                   tv.raw_payload -> 'unidadeOrgao' ->> 'ufSigla' AS uf,
                   tv.raw_payload -> 'unidadeOrgao' ->> 'municipioNome' AS municipio
            FROM tender_versions tv
            ORDER BY tv.tender_id, tv.version_number DESC
        ) v
        WHERE t.id = v.tender_id
          AND v.uf IS NOT NULL
        """
    )

    # --- RLS (ver ADR-0002 e SECURITY_MODEL.md). opportunity_matches tem tenant_id proprio e
    # politica propria de proposito, apesar de ser DERIVADA de Opportunity no DOMAIN_MODEL:
    # defesa em profundidade — um bug de join nao vaza match entre tenants. ---
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

    op.drop_index(op.f("ix_tenders_uf"), table_name="tenders")
    op.drop_column("tenders", "municipio")
    op.drop_column("tenders", "uf")
    op.drop_column("company_profiles", "services")
    op.drop_column("company_profiles", "products")
    op.drop_index(op.f("ix_opportunity_matches_tenant_id"), table_name="opportunity_matches")
    op.drop_index(op.f("ix_opportunity_matches_opportunity_id"), table_name="opportunity_matches")
    op.drop_table("opportunity_matches")
    op.drop_index(op.f("ix_opportunities_tender_id"), table_name="opportunities")
    op.drop_index(op.f("ix_opportunities_tenant_id"), table_name="opportunities")
    op.drop_index(op.f("ix_opportunities_status"), table_name="opportunities")
    op.drop_table("opportunities")
    # O tipo enum criado implicitamente por sa.Enum nao e removido por drop_table — sem isto, um
    # upgrade depois de um downgrade falha com "type opportunity_status already exists".
    op.execute("DROP TYPE IF EXISTS opportunity_status")
