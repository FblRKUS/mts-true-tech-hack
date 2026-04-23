"""create media_gallery_items table

Revision ID: 20260414_0006
Revises: 20260412_0005
Create Date: 2026-04-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20260414_0006"
down_revision: Union[str, None] = "20260412_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "media_gallery_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("media_url", sa.Text(), nullable=False),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("chat_id", sa.String(length=128), nullable=True),
        sa.Column("message_id", sa.String(length=128), nullable=True),
        sa.Column("thread_id", sa.String(length=128), nullable=True),
        sa.Column("prompt_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("model_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("source_ref", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_media_gallery_items_owner_created_at",
        "media_gallery_items",
        ["owner_id", "created_at"],
    )
    op.create_index(
        "ix_media_gallery_items_owner_kind_created_at",
        "media_gallery_items",
        ["owner_id", "kind", "created_at"],
    )
    op.create_index(
        "ix_media_gallery_items_owner_chat_created_at",
        "media_gallery_items",
        ["owner_id", "chat_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_media_gallery_items_owner_chat_created_at", table_name="media_gallery_items")
    op.drop_index("ix_media_gallery_items_owner_kind_created_at", table_name="media_gallery_items")
    op.drop_index("ix_media_gallery_items_owner_created_at", table_name="media_gallery_items")
    op.drop_table("media_gallery_items")
