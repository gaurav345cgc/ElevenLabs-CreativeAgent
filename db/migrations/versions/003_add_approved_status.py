"""Add APPROVED to transcript status check constraint.

Revision ID: 003
Revises: 002
Create Date: 2026-07-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_transcript_status", "transcript", type_="check")
    op.create_check_constraint(
        "ck_transcript_status",
        "transcript",
        "status IN ('CREATED', 'PENDING_ENHANCEMENT', 'ENHANCING', 'ENHANCED', 'APPROVED', 'FAILED_ENHANCEMENT', 'REVIEW_REQUIRED')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_transcript_status", "transcript", type_="check")
    op.create_check_constraint(
        "ck_transcript_status",
        "transcript",
        "status IN ('CREATED', 'PENDING_ENHANCEMENT', 'ENHANCING', 'ENHANCED', 'FAILED_ENHANCEMENT', 'REVIEW_REQUIRED')",
    )
