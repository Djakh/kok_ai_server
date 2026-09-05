"""Make a push installation globally unique.

Revision ID: 20260821_0008
Revises: 20260821_0007
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260821_0008"
down_revision: str | None = "20260821_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep the most recently updated record if historical data contains duplicates.
    op.execute(
        """
        DELETE FROM device_installations older
        USING device_installations newer
        WHERE older.installation_id = newer.installation_id
          AND (older.updated_at, older.id) < (newer.updated_at, newer.id)
        """
    )
    op.drop_constraint("uq_device_user_installation", "device_installations", type_="unique")
    op.create_unique_constraint(
        "uq_device_installation_id", "device_installations", ["installation_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_device_installation_id", "device_installations", type_="unique")
    op.create_unique_constraint(
        "uq_device_user_installation",
        "device_installations",
        ["user_id", "installation_id"],
    )
