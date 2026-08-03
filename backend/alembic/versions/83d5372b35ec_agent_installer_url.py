"""agent installer_url

Revision ID: 83d5372b35ec
Revises: 81c5115e2c9d
Create Date: 2026-08-03 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "83d5372b35ec"
down_revision: str | None = "81c5115e2c9d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # installer_url: relative URL where the self-extracting installer for
    # this agent can be downloaded once the builder finishes. Null while
    # the agent is still in configured / building state; set to the storage
    # download path (see agent_builder.storage.store_installer) when status
    # transitions to "ready".
    #
    # Populated alongside binary_url in the same build step; either can be
    # used depending on the delivery layer (installer for cloud-init / golden
    # template, raw binary for hand-run scenarios where the agent is placed
    # and launched manually).
    op.add_column(
        "agents",
        sa.Column("installer_url", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "installer_url")
