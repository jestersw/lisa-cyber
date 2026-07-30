"""activity events

Revision ID: 5c906d37b5e9
Revises: 8a6a272a9f28
Create Date: 2026-07-30 20:44:41.929832
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5c906d37b5e9"
down_revision: str | None = "8a6a272a9f28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "activity_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=True),
        sa.Column("app", sa.String(length=150), nullable=False),
        sa.Column("activity_type", sa.String(length=50), nullable=False),
        sa.Column("role", sa.String(length=100), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("timestamp", sa.TIMESTAMP(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_activity_events_agent_id"), "activity_events", ["agent_id"], unique=False
    )
    op.create_index(op.f("ix_activity_events_id"), "activity_events", ["id"], unique=False)
    op.create_index(
        op.f("ix_activity_events_timestamp"), "activity_events", ["timestamp"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_activity_events_timestamp"), table_name="activity_events")
    op.drop_index(op.f("ix_activity_events_id"), table_name="activity_events")
    op.drop_index(op.f("ix_activity_events_agent_id"), table_name="activity_events")
    op.drop_table("activity_events")
