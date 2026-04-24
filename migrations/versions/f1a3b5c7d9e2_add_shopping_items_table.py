"""add shopping_items table

Revision ID: f1a3b5c7d9e2
Revises: e8b3c5d6f7a2
Create Date: 2026-04-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a3b5c7d9e2'
down_revision: Union[str, Sequence[str], None] = 'e8b3c5d6f7a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'shopping_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('link', sa.Text(), nullable=False, server_default=''),
        sa.Column('note', sa.Text(), nullable=False, server_default=''),
        sa.Column('added_by', sa.BigInteger(), nullable=False),
        sa.Column('bought', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_shopping_items_guild_id'), 'shopping_items', ['guild_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_shopping_items_guild_id'), table_name='shopping_items')
    op.drop_table('shopping_items')
