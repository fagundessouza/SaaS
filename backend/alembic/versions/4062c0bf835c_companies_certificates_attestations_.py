"""companies certificates attestations, analysis findings evidences (fase 8)

Revision ID: 4062c0bf835c
Revises: e7e8db6a1bec
Create Date: 2026-09-17 19:51:01.905151

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4062c0bf835c"
down_revision: str | None = "e7e8db6a1bec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Todas as 5 tabelas desta migration sao TENANT (ver docs/DOMAIN_MODEL.md) — RLS aplicado a cada
# uma individualmente (defesa em profundidade, mesmo raciocinio ja documentado para
# opportunity_matches na Fase 7: um bug de join nao vaza dado entre tenants).
_RLS_TABLES = ("attestations", "certificates", "analyses", "findings", "evidences")


def upgrade() -> None:
    op.create_table(
        "attestations",
        sa.Column("company_profile_id", sa.UUID(), nullable=False),
        sa.Column("issuing_org", sa.String(length=255), nullable=False),
        sa.Column("object_description", sa.Text(), nullable=False),
        sa.Column("contract_value", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
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
        sa.ForeignKeyConstraint(["company_profile_id"], ["company_profiles.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_attestations_company_profile_id"),
        "attestations",
        ["company_profile_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_attestations_tenant_id"), "attestations", ["tenant_id"], unique=False
    )
    op.create_table(
        "certificates",
        sa.Column("company_profile_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("issued_at", sa.Date(), nullable=True),
        sa.Column("expires_at", sa.Date(), nullable=True),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["company_profile_id"], ["company_profiles.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_certificates_category"), "certificates", ["category"], unique=False
    )
    op.create_index(
        op.f("ix_certificates_company_profile_id"),
        "certificates",
        ["company_profile_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_certificates_tenant_id"), "certificates", ["tenant_id"], unique=False
    )
    op.create_table(
        "analyses",
        sa.Column("opportunity_id", sa.UUID(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("opportunity_id", name="uq_analyses_opportunity"),
    )
    op.create_index(op.f("ix_analyses_opportunity_id"), "analyses", ["opportunity_id"], unique=False)
    op.create_index(op.f("ix_analyses_tenant_id"), "analyses", ["tenant_id"], unique=False)
    op.create_table(
        "findings",
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("requirement_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column(
            "status",
            sa.Enum("MET", "MISSING", "EXPIRED", "NEEDS_REVIEW", name="finding_status"),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum("BLOCKING", "WARNING", "INFO", name="finding_severity"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.ForeignKeyConstraint(["requirement_id"], ["requirements.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_findings_analysis_id"), "findings", ["analysis_id"], unique=False)
    op.create_index(op.f("ix_findings_category"), "findings", ["category"], unique=False)
    op.create_index(
        op.f("ix_findings_requirement_id"), "findings", ["requirement_id"], unique=False
    )
    op.create_index(op.f("ix_findings_severity"), "findings", ["severity"], unique=False)
    op.create_index(op.f("ix_findings_status"), "findings", ["status"], unique=False)
    op.create_index(op.f("ix_findings_tenant_id"), "findings", ["tenant_id"], unique=False)
    op.create_table(
        "evidences",
        sa.Column("finding_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "REQUIREMENT_TEXT", "CERTIFICATE_DATA", "ATTESTATION_DATA", name="evidence_kind"
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("document_version_id", sa.UUID(), nullable=True),
        sa.Column("section", sa.String(length=200), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("certificate_id", sa.UUID(), nullable=True),
        sa.Column("attestation_id", sa.UUID(), nullable=True),
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
        sa.ForeignKeyConstraint(["attestation_id"], ["attestations.id"]),
        sa.ForeignKeyConstraint(["certificate_id"], ["certificates.id"]),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"]),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_evidences_finding_id"), "evidences", ["finding_id"], unique=False)
    op.create_index(op.f("ix_evidences_tenant_id"), "evidences", ["tenant_id"], unique=False)

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

    op.drop_index(op.f("ix_evidences_tenant_id"), table_name="evidences")
    op.drop_index(op.f("ix_evidences_finding_id"), table_name="evidences")
    op.drop_table("evidences")
    op.drop_index(op.f("ix_findings_tenant_id"), table_name="findings")
    op.drop_index(op.f("ix_findings_status"), table_name="findings")
    op.drop_index(op.f("ix_findings_severity"), table_name="findings")
    op.drop_index(op.f("ix_findings_requirement_id"), table_name="findings")
    op.drop_index(op.f("ix_findings_category"), table_name="findings")
    op.drop_index(op.f("ix_findings_analysis_id"), table_name="findings")
    op.drop_table("findings")
    op.drop_index(op.f("ix_analyses_tenant_id"), table_name="analyses")
    op.drop_index(op.f("ix_analyses_opportunity_id"), table_name="analyses")
    op.drop_table("analyses")
    op.drop_index(op.f("ix_certificates_tenant_id"), table_name="certificates")
    op.drop_index(op.f("ix_certificates_company_profile_id"), table_name="certificates")
    op.drop_index(op.f("ix_certificates_category"), table_name="certificates")
    op.drop_table("certificates")
    op.drop_index(op.f("ix_attestations_tenant_id"), table_name="attestations")
    op.drop_index(op.f("ix_attestations_company_profile_id"), table_name="attestations")
    op.drop_table("attestations")

    # op.drop_table nao remove o tipo ENUM associado (ver migrations anteriores).
    op.execute("DROP TYPE IF EXISTS finding_status")
    op.execute("DROP TYPE IF EXISTS finding_severity")
    op.execute("DROP TYPE IF EXISTS evidence_kind")
