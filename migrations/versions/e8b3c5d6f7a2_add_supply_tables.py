"""add supply_items and supply_check_results tables

Revision ID: e8b3c5d6f7a2
Revises: d7a2f4c8e1b9
Create Date: 2026-04-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8b3c5d6f7a2'
down_revision: Union[str, Sequence[str], None] = 'd7a2f4c8e1b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create supply_items and supply_check_results tables.

    supply_items holds the per-guild list of household supplies to track.
    supply_check_results records which items were flagged as needing restock
    each week, keyed by (guild_id, week_of, item_id, user_id).
    """
    op.create_table(
        'supply_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_supply_items_guild_id'), 'supply_items', ['guild_id'], unique=False
    )

    op.create_table(
        'supply_check_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('week_of', sa.Date(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_supply_check_results_guild_id'),
        'supply_check_results',
        ['guild_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_supply_check_results_guild_id'), table_name='supply_check_results'
    )
    op.drop_table('supply_check_results')
    op.drop_index(op.f('ix_supply_items_guild_id'), table_name='supply_items')
    op.drop_table('supply_items')
