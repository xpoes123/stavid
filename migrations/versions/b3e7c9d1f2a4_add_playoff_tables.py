"""add playoff tables

Revision ID: b3e7c9d1f2a4
Revises: 9301254028ea
Create Date: 2026-04-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3e7c9d1f2a4'
down_revision: Union[str, Sequence[str], None] = '9301254028ea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'playoff_checkins',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('checkin_date', sa.Date(), nullable=False),
        sa.Column('pillar1', sa.Boolean(), nullable=False),
        sa.Column('pillar2', sa.Boolean(), nullable=False),
        sa.Column('pillar3', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_playoff_checkins_guild_id'), 'playoff_checkins', ['guild_id'], unique=False)
    op.create_index(op.f('ix_playoff_checkins_user_id'), 'playoff_checkins', ['user_id'], unique=False)

    op.create_table(
        'playoff_series',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('week_start', sa.Date(), nullable=False),
        sa.Column('wins', sa.Integer(), nullable=False),
        sa.Column('losses', sa.Integer(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_playoff_series_guild_id'), 'playoff_series', ['guild_id'], unique=False)
    op.create_index(op.f('ix_playoff_series_user_id'), 'playoff_series', ['user_id'], unique=False)

    op.create_table(
        'weekly_reviews',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('week_of', sa.Date(), nullable=False),
        sa.Column('review_text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_weekly_reviews_guild_id'), 'weekly_reviews', ['guild_id'], unique=False)
    op.create_index(op.f('ix_weekly_reviews_user_id'), 'weekly_reviews', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_weekly_reviews_user_id'), table_name='weekly_reviews')
    op.drop_index(op.f('ix_weekly_reviews_guild_id'), table_name='weekly_reviews')
    op.drop_table('weekly_reviews')

    op.drop_index(op.f('ix_playoff_series_user_id'), table_name='playoff_series')
    op.drop_index(op.f('ix_playoff_series_guild_id'), table_name='playoff_series')
    op.drop_table('playoff_series')

    op.drop_index(op.f('ix_playoff_checkins_user_id'), table_name='playoff_checkins')
    op.drop_index(op.f('ix_playoff_checkins_guild_id'), table_name='playoff_checkins')
    op.drop_table('playoff_checkins')
