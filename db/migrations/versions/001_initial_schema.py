"""Initial transcript schema — entities, versions, audit events.

Revision ID: 001
Revises:
Create Date: 2026-07-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TRANSCRIPT_STATUS = (
    "CREATED",
    "PENDING_ENHANCEMENT",
    "ENHANCING",
    "ENHANCED",
    "FAILED_ENHANCEMENT",
    "REVIEW_REQUIRED",
)

VERSION_KIND = (
    "RAW_PATTERN",
    "ELEVENLABS_ENHANCED",
    "ELEVENLABS_TAGGED",
    "APPROVED_FINAL",
)

ENHANCEMENT_MODE = ("plain_paste", "api_chunked", "v3_tagged")


def upgrade() -> None:
    status_check = sa.text(
        "status IN ("
        + ", ".join(f"'{value}'" for value in TRANSCRIPT_STATUS)
        + ")"
    )
    version_kind_check = sa.text(
        "version_kind IN ("
        + ", ".join(f"'{value}'" for value in VERSION_KIND)
        + ")"
    )
    enhancement_mode_check = sa.text(
        "enhancement_mode IS NULL OR enhancement_mode IN ("
        + ", ".join(f"'{value}'" for value in ENHANCEMENT_MODE)
        + ")"
    )

    op.create_table(
        "transcript",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("generation_code", sa.Text(), nullable=True),
        sa.Column("wound_id", sa.Text(), nullable=True),
        sa.Column("stage_no", sa.Integer(), nullable=True),
        sa.Column("pillar_code", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "enhancement_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(status_check, name="ck_transcript_status"),
    )

    op.create_table(
        "transcript_version",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_kind", sa.Text(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("content_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by_agent", sa.Text(), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "source_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Raw version this enhancement was derived from",
        ),
        sa.Column(
            "enhancement_mode",
            sa.Text(),
            nullable=True,
            comment="Output mode for enhanced versions; drives idempotency",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id"],
            ["transcript.id"],
            name="fk_transcript_version_transcript_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["transcript_version.id"],
            name="fk_transcript_version_source_version_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(version_kind_check, name="ck_transcript_version_kind"),
        sa.CheckConstraint(enhancement_mode_check, name="ck_transcript_version_enhancement_mode"),
    )

    op.create_foreign_key(
        "fk_transcript_current_version_id",
        "transcript",
        "transcript_version",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "transcript_job_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id"],
            ["transcript.id"],
            name="fk_transcript_job_event_transcript_id",
            ondelete="CASCADE",
        ),
    )

    op.create_index("ix_transcript_status", "transcript", ["status"])
    op.create_index("ix_transcript_tenant_id", "transcript", ["tenant_id"])
    op.create_index("ix_transcript_current_version_id", "transcript", ["current_version_id"])
    op.create_index("ix_transcript_version_transcript_id", "transcript_version", ["transcript_id"])
    op.create_index("ix_transcript_version_version_kind", "transcript_version", ["version_kind"])
    op.create_index(
        "ix_transcript_job_event_transcript_id",
        "transcript_job_event",
        ["transcript_id"],
    )

    # One enhanced output per raw version + enhancement mode (Lambda 2 idempotency).
    op.create_index(
        "uq_transcript_version_enhancement_per_mode",
        "transcript_version",
        ["source_version_id", "enhancement_mode"],
        unique=True,
        postgresql_where=sa.text(
            "source_version_id IS NOT NULL AND enhancement_mode IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_transcript_version_enhancement_per_mode",
        table_name="transcript_version",
    )
    op.drop_index("ix_transcript_job_event_transcript_id", table_name="transcript_job_event")
    op.drop_index("ix_transcript_version_version_kind", table_name="transcript_version")
    op.drop_index("ix_transcript_version_transcript_id", table_name="transcript_version")
    op.drop_index("ix_transcript_current_version_id", table_name="transcript")
    op.drop_index("ix_transcript_tenant_id", table_name="transcript")
    op.drop_index("ix_transcript_status", table_name="transcript")

    op.drop_table("transcript_job_event")
    op.drop_constraint("fk_transcript_current_version_id", "transcript", type_="foreignkey")
    op.drop_table("transcript_version")
    op.drop_table("transcript")
