"""add watchlist_items table

Revision ID: b5d1f3a7c9e2
Revises: a9c2e4f6b8d1
Create Date: 2026-04-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5d1f3a7c9e2'
down_revision: Union[str, Sequence[str], None] = 'a9c2e4f6b8d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'watchlist_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('media_type', sa.Text(), nullable=False),
        sa.Column('added_by', sa.BigInteger(), nullable=False),
        sa.Column('link', sa.Text(), nullable=False, server_default=''),
        sa.Column('note', sa.Text(), nullable=False, server_default=''),
        sa.Column('watched', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('watched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('david_rating', sa.Integer(), nullable=True),
        sa.Column('steph_rating', sa.Integer(), nullable=True),
        sa.Column('david_notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('steph_notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_watchlist_items_guild_id'), 'watchlist_items', ['guild_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_watchlist_items_guild_id'), table_name='watchlist_items')
    op.drop_table('watchlist_items')
