"""deployments table

Revision ID: d7f3a9c2b1e4
Revises: 83d5372b35ec
Create Date: 2026-10-24 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7f3a9c2b1e4"
down_revision: str | None = "83d5372b35ec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One row per deployment attempt (operator pushes/updates an agent onto a
    # set of hosts via an orchestration backend — Ansible today, #212). The
    # runner moves status pending -> running -> succeeded | failed | unavailable
    # and records the playbook's return code and output tail for the panel.
    op.create_table(
        "deployments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.String(length=50), nullable=False),
        sa.Column("backend", sa.String(length=20), nullable=False, server_default="ansible"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("targets", sa.JSON(), nullable=True),
        sa.Column("returncode", sa.Integer(), nullable=True),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now(), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deployments_id", "deployments", ["id"])
    op.create_index("ix_deployments_agent_id", "deployments", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_deployments_agent_id", table_name="deployments")
    op.drop_index("ix_deployments_id", table_name="deployments")
    op.drop_table("deployments")
