"""agent binary_url and token

Revision ID: 81c5115e2c9d
Revises: 5c906d37b5e9
Create Date: 2026-08-02 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "81c5115e2c9d"
down_revision: str | None = "5c906d37b5e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # binary_url: relative URL where the compiled agent binary can be
    # downloaded once the builder finishes. Null while the agent is still
    # in configured / building state; set to the storage download path
    # (see agent_builder.storage) when status transitions to "ready".
    op.add_column(
        "agents",
        sa.Column("binary_url", sa.String(length=500), nullable=True),
    )
    # agent_token: bearer token this agent will present on heartbeat. Generated
    # by the builder at build time, kept in the DB so the backend can validate
    # incoming heartbeats. One agent, one token; rotating the token requires
    # a rebuild.
    op.add_column(
        "agents",
        sa.Column("agent_token", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "agent_token")
    op.drop_column("agents", "binary_url")
