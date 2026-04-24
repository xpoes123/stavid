"""add outing_wishlist_items table

Revision ID: c3a5e7f9b1d2
Revises: a9c2e4f6b8d1
Create Date: 2026-04-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3a5e7f9b1d2'
down_revision: Union[str, Sequence[str], None] = 'a9c2e4f6b8d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'outing_wishlist_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('category', sa.Text(), nullable=False, server_default='other'),
        sa.Column('budget', sa.Text(), nullable=False, server_default=''),
        sa.Column('neighborhood', sa.Text(), nullable=False, server_default=''),
        sa.Column('link', sa.Text(), nullable=False, server_default=''),
        sa.Column('note', sa.Text(), nullable=False, server_default=''),
        sa.Column('added_by', sa.BigInteger(), nullable=False),
        sa.Column('visited', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('visited_at', sa.Date(), nullable=True),
        sa.Column('visited_notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_outing_wishlist_items_guild_id'), 'outing_wishlist_items', ['guild_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_outing_wishlist_items_guild_id'), table_name='outing_wishlist_items')
    op.drop_table('outing_wishlist_items')
