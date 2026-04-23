"""create workspaces, workspace_nodes and workspace_audit_logs tables

Revision ID: 20260412_0005
Revises: 20260412_0004
Create Date: 2026-04-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20260412_0005"
down_revision: Union[str, None] = "20260412_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspaces_owner_created_at", "workspaces", ["owner_id", "created_at"])

    op.create_table(
        "workspace_nodes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("node_type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("mime_type", sa.String(length=128), nullable=False, server_default="text/plain"),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "path", name="uq_workspace_nodes_workspace_path"),
    )
    op.create_index("ix_workspace_nodes_workspace_parent", "workspace_nodes", ["workspace_id", "parent_id"])

    op.create_table(
        "workspace_audit_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("actor_type", sa.String(length=16), nullable=False, server_default="user"),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("node_id", sa.String(length=36), nullable=True),
        sa.Column("node_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workspace_audit_logs_workspace_created_at",
        "workspace_audit_logs",
        ["workspace_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_workspace_audit_logs_workspace_created_at", table_name="workspace_audit_logs")
    op.drop_table("workspace_audit_logs")

    op.drop_index("ix_workspace_nodes_workspace_parent", table_name="workspace_nodes")
    op.drop_table("workspace_nodes")

    op.drop_index("ix_workspaces_owner_created_at", table_name="workspaces")
    op.drop_table("workspaces")
