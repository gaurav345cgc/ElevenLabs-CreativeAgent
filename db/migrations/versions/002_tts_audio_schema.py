"""TTS plane audio job, chunk, asset, and event tables.

Revision ID: 002
Revises: 001
Create Date: 2026-07-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AUDIO_JOB_STATUS = (
    "CREATED",
    "PLANNING",
    "READY",
    "GENERATING",
    "PARTIALLY_FAILED",
    "COMPLETED",
    "FAILED",
    "REVIEW_REQUIRED",
)

AUDIO_CHUNK_STATUS = (
    "PLANNED",
    "GENERATING",
    "COMPLETED",
    "FAILED",
    "RETRYING",
    "SKIPPED",
)


def upgrade() -> None:
    job_status_check = sa.text(
        "status IN (" + ", ".join(f"'{value}'" for value in AUDIO_JOB_STATUS) + ")"
    )
    chunk_status_check = sa.text(
        "status IN (" + ", ".join(f"'{value}'" for value in AUDIO_CHUNK_STATUS) + ")"
    )

    op.create_table(
        "transcript_audio_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transcript_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("voice_profile_code", sa.Text(), nullable=True),
        sa.Column("voice_id", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("output_format", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("total_chunks", sa.Integer(), nullable=True),
        sa.Column(
            "completed_chunks",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "failed_chunks",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "enable_logging",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "apply_text_normalization",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'auto'"),
        ),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("estimated_duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("final_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("failure_notes", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["transcript_id"],
            ["transcript.id"],
            name="fk_transcript_audio_job_transcript_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transcript_version_id"],
            ["transcript_version.id"],
            name="fk_transcript_audio_job_transcript_version_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(job_status_check, name="ck_transcript_audio_job_status"),
        sa.UniqueConstraint("idempotency_key", name="uq_transcript_audio_job_idempotency_key"),
    )

    op.create_table(
        "transcript_audio_chunk",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("audio_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transcript_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("previous_text", sa.Text(), nullable=True),
        sa.Column("next_text", sa.Text(), nullable=True),
        sa.Column(
            "previous_request_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "next_request_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("eleven_request_id", sa.Text(), nullable=True),
        sa.Column("output_object_key", sa.Text(), nullable=True),
        sa.Column("output_format", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("estimated_duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("actual_duration_ms", sa.BigInteger(), nullable=True),
        sa.Column(
            "response_headers_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
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
        sa.ForeignKeyConstraint(
            ["audio_job_id"],
            ["transcript_audio_job.id"],
            name="fk_transcript_audio_chunk_audio_job_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id"],
            ["transcript.id"],
            name="fk_transcript_audio_chunk_transcript_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transcript_version_id"],
            ["transcript_version.id"],
            name="fk_transcript_audio_chunk_transcript_version_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(chunk_status_check, name="ck_transcript_audio_chunk_status"),
        sa.UniqueConstraint(
            "audio_job_id",
            "chunk_index",
            name="uq_transcript_audio_chunk_job_index",
        ),
    )

    op.create_table(
        "transcript_audio_asset",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("audio_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_kind", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("checksum", sa.Text(), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["audio_job_id"],
            ["transcript_audio_job.id"],
            name="fk_transcript_audio_asset_audio_job_id",
            ondelete="CASCADE",
        ),
    )

    op.create_foreign_key(
        "fk_transcript_audio_job_final_asset_id",
        "transcript_audio_job",
        "transcript_audio_asset",
        ["final_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "transcript_audio_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("audio_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["audio_job_id"],
            ["transcript_audio_job.id"],
            name="fk_transcript_audio_event_audio_job_id",
            ondelete="CASCADE",
        ),
    )

    op.create_index(
        "ix_transcript_audio_job_transcript_id",
        "transcript_audio_job",
        ["transcript_id"],
    )
    op.create_index(
        "ix_transcript_audio_job_transcript_version_id",
        "transcript_audio_job",
        ["transcript_version_id"],
    )
    op.create_index("ix_transcript_audio_job_status", "transcript_audio_job", ["status"])
    op.create_index("ix_transcript_audio_job_tenant_id", "transcript_audio_job", ["tenant_id"])

    op.create_index(
        "ix_transcript_audio_chunk_audio_job_id",
        "transcript_audio_chunk",
        ["audio_job_id"],
    )
    op.create_index(
        "ix_transcript_audio_chunk_transcript_id",
        "transcript_audio_chunk",
        ["transcript_id"],
    )
    op.create_index(
        "ix_transcript_audio_chunk_transcript_version_id",
        "transcript_audio_chunk",
        ["transcript_version_id"],
    )
    op.create_index("ix_transcript_audio_chunk_status", "transcript_audio_chunk", ["status"])
    op.create_index(
        "ix_transcript_audio_chunk_chunk_index",
        "transcript_audio_chunk",
        ["chunk_index"],
    )

    op.create_index(
        "ix_transcript_audio_asset_audio_job_id",
        "transcript_audio_asset",
        ["audio_job_id"],
    )
    op.create_index(
        "ix_transcript_audio_event_audio_job_id",
        "transcript_audio_event",
        ["audio_job_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_transcript_audio_event_audio_job_id", table_name="transcript_audio_event")
    op.drop_index("ix_transcript_audio_asset_audio_job_id", table_name="transcript_audio_asset")
    op.drop_index("ix_transcript_audio_chunk_chunk_index", table_name="transcript_audio_chunk")
    op.drop_index("ix_transcript_audio_chunk_status", table_name="transcript_audio_chunk")
    op.drop_index(
        "ix_transcript_audio_chunk_transcript_version_id",
        table_name="transcript_audio_chunk",
    )
    op.drop_index("ix_transcript_audio_chunk_transcript_id", table_name="transcript_audio_chunk")
    op.drop_index("ix_transcript_audio_chunk_audio_job_id", table_name="transcript_audio_chunk")
    op.drop_index("ix_transcript_audio_job_tenant_id", table_name="transcript_audio_job")
    op.drop_index("ix_transcript_audio_job_status", table_name="transcript_audio_job")
    op.drop_index(
        "ix_transcript_audio_job_transcript_version_id",
        table_name="transcript_audio_job",
    )
    op.drop_index("ix_transcript_audio_job_transcript_id", table_name="transcript_audio_job")

    op.drop_table("transcript_audio_event")
    op.drop_constraint(
        "fk_transcript_audio_job_final_asset_id",
        "transcript_audio_job",
        type_="foreignkey",
    )
    op.drop_table("transcript_audio_asset")
    op.drop_table("transcript_audio_chunk")
    op.drop_table("transcript_audio_job")
