"""drop dead playoff_series and daily_results tables

These tables stopped being read or written when playoff scoring was
converted from joint to individual (PR #33). They've been carrying
stale data ever since. Removing them and merging the two existing
heads (chore tables + supply last_bought_at) into a single head.

Revision ID: 3d4e5f6a7b8c
Revises: 1b2c3d4e5f60, 2c3d4e5f6a7b
Create Date: 2026-05-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d4e5f6a7b8c'
down_revision: Union[str, Sequence[str], None] = (
    '1b2c3d4e5f60',
    '2c3d4e5f6a7b',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # daily_results — single index on guild_id
    op.drop_index(op.f('ix_daily_results_guild_id'), table_name='daily_results')
    op.drop_table('daily_results')

    # playoff_series — single index on guild_id (the user_id index was
    # dropped earlier in c4f1d2e3a5b6_make_playoff_series_shared)
    op.drop_index(op.f('ix_playoff_series_guild_id'), table_name='playoff_series')
    op.drop_table('playoff_series')


def downgrade() -> None:
    # Re-create the tables in their final pre-drop shape so a future
    # downgrade can restore an empty schema. Historical data is gone.
    op.create_table(
        'playoff_series',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('week_start', sa.Date(), nullable=False),
        sa.Column('wins', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('losses', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.Text(), nullable=False, server_default='ongoing'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('david_days', sa.Integer(), nullable=True),
        sa.Column('steph_days', sa.Integer(), nullable=True),
        sa.Column('david_p1', sa.Integer(), nullable=True),
        sa.Column('david_p2', sa.Integer(), nullable=True),
        sa.Column('david_p3', sa.Integer(), nullable=True),
        sa.Column('steph_p1', sa.Integer(), nullable=True),
        sa.Column('steph_p2', sa.Integer(), nullable=True),
        sa.Column('steph_p3', sa.Integer(), nullable=True),
        sa.Column('best_streak', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_playoff_series_guild_id'), 'playoff_series', ['guild_id'], unique=False
    )

    op.create_table(
        'daily_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('result_date', sa.Date(), nullable=False),
        sa.Column('david_complete', sa.Boolean(), nullable=False),
        sa.Column('steph_complete', sa.Boolean(), nullable=False),
        sa.Column('won', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_daily_results_guild_id'), 'daily_results', ['guild_id'], unique=False
    )
