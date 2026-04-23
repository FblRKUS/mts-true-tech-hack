"""create chat memories table

Revision ID: 20260412_0001
Revises: 
Create Date: 2026-04-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260412_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_memories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("tags", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_memories_user_created_at", "chat_memories", ["user_id", "created_at"])
    op.create_index("ix_chat_memories_user_source", "chat_memories", ["user_id", "source"])


def downgrade() -> None:
    op.drop_index("ix_chat_memories_user_source", table_name="chat_memories")
    op.drop_index("ix_chat_memories_user_created_at", table_name="chat_memories")
    op.drop_table("chat_memories")
