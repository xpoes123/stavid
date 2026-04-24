"""add datenight, wishlist, log, and special_dates tables

Revision ID: b2d4f6a8c1e3
Revises: a9c2e4f6b8d1
Create Date: 2026-04-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2d4f6a8c1e3'
down_revision: Union[str, Sequence[str], None] = 'a9c2e4f6b8d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'datenight_planner',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('last_planner_id', sa.BigInteger(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_datenight_planner_guild_id', 'datenight_planner', ['guild_id'])

    op.create_table(
        'datenight_wishlist',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('added_by', sa.BigInteger(), nullable=False),
        sa.Column('visited', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('visited_at', sa.Date(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_datenight_wishlist_guild_id', 'datenight_wishlist', ['guild_id'])

    op.create_table(
        'datenight_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('planned_by', sa.BigInteger(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('place', sa.Text(), nullable=False, server_default=''),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('rating', sa.Integer(), nullable=True),
        sa.Column('wishlist_item_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_datenight_log_guild_id', 'datenight_log', ['guild_id'])

    op.create_table(
        'special_dates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('label', sa.Text(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('day', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('gift_ideas', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_special_dates_guild_id', 'special_dates', ['guild_id'])


def downgrade() -> None:
    op.drop_index('ix_special_dates_guild_id', table_name='special_dates')
    op.drop_table('special_dates')
    op.drop_index('ix_datenight_log_guild_id', table_name='datenight_log')
    op.drop_table('datenight_log')
    op.drop_index('ix_datenight_wishlist_guild_id', table_name='datenight_wishlist')
    op.drop_table('datenight_wishlist')
    op.drop_index('ix_datenight_planner_guild_id', table_name='datenight_planner')
    op.drop_table('datenight_planner')
