"""hosts table

Revision ID: c4b8e1a2f7d0
Revises: b2e7c4a1f093
Create Date: 2026-10-28 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4b8e1a2f7d0"
down_revision: str | None = "b2e7c4a1f093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Reusable deployment targets the operator saves once and picks from on each
    # deploy, instead of retyping hostnames (#212 follow-up).
    op.create_table(
        "hosts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("address", sa.String(length=253), nullable=False),
        sa.Column("ssh_user", sa.String(length=64), nullable=True),
        sa.Column("os_type", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address", name="uq_hosts_address"),
    )
    op.create_index("ix_hosts_id", "hosts", ["id"])


def downgrade() -> None:
    op.drop_index("ix_hosts_id", table_name="hosts")
    op.drop_table("hosts")
