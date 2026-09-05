"""Persist the mobile-confirmed species common name.

Revision ID: 20260821_0007
Revises: 20260821_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260821_0007"
down_revision: str | None = "20260821_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trees", sa.Column("confirmed_common_name", sa.String(255)))


def downgrade() -> None:
    op.drop_column("trees", "confirmed_common_name")
