"""add daily_results table

Revision ID: d7a2f4c8e1b9
Revises: c4f1d2e3a5b6
Create Date: 2026-04-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7a2f4c8e1b9'
down_revision: Union[str, Sequence[str], None] = 'c4f1d2e3a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create daily_results table.

    Each row represents the settled, authoritative combined win/loss for a
    single day in a guild.  A row is only created once both David and Stephanie
    have submitted their check-ins for that day.  The series tally is derived
    from these rows instead of being recomputed from raw playoff_checkins.
    """
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


def downgrade() -> None:
    op.drop_index(op.f('ix_daily_results_guild_id'), table_name='daily_results')
    op.drop_table('daily_results')
