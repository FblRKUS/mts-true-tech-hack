"""add thread-aware memory and summaries

Revision ID: 20260412_0002
Revises: 20260412_0001
Create Date: 2026-04-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260412_0002"
down_revision: Union[str, None] = "20260412_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chat_memories", sa.Column("thread_id", sa.String(length=128), nullable=False, server_default=""))
    op.add_column("chat_memories", sa.Column("role", sa.String(length=32), nullable=False, server_default="user"))
    op.create_index(
        "ix_chat_memories_user_thread_created",
        "chat_memories",
        ["user_id", "thread_id", "created_at"],
    )

    op.create_table(
        "chat_thread_summaries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("thread_id", sa.String(length=128), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "thread_id", name="uq_chat_thread_summaries_user_thread"),
    )
    op.create_index(
        "ix_chat_thread_summaries_user_updated_at",
        "chat_thread_summaries",
        ["user_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_thread_summaries_user_updated_at", table_name="chat_thread_summaries")
    op.drop_table("chat_thread_summaries")

    op.drop_index("ix_chat_memories_user_thread_created", table_name="chat_memories")
    op.drop_column("chat_memories", "role")
    op.drop_column("chat_memories", "thread_id")
