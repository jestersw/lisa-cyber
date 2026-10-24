"""agent enrollment token + enrolled flag

Revision ID: b2e7c4a1f093
Revises: d7f3a9c2b1e4
Create Date: 2026-10-24 19:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2e7c4a1f093"
down_revision: str | None = "d7f3a9c2b1e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Install-time enrollment (#201 part B). The build bakes a one-time
    # enrollment token (hashed here) instead of the real token; the agent
    # exchanges it for its real token on first run, at which point `enrolled`
    # flips true and `agent_token` holds the real token's hash.
    op.add_column(
        "agents",
        sa.Column("enrollment_token_hash", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "agents",
        sa.Column(
            "enrolled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "enrolled")
    op.drop_column("agents", "enrollment_token_hash")
