"""add bucket_list_items table

Revision ID: e2a4c6d8f1b3
Revises: b5d1f3a7c9e2
Create Date: 2026-04-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2a4c6d8f1b3'
down_revision: Union[str, Sequence[str], None] = 'b5d1f3a7c9e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'bucket_list_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('category', sa.Text(), nullable=False, server_default='other'),
        sa.Column('added_by', sa.BigInteger(), nullable=False),
        sa.Column('link', sa.Text(), nullable=False, server_default=''),
        sa.Column('note', sa.Text(), nullable=False, server_default=''),
        sa.Column('completed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_bucket_list_items_guild_id'), 'bucket_list_items', ['guild_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_bucket_list_items_guild_id'), table_name='bucket_list_items')
    op.drop_table('bucket_list_items')
