"""add weekly stats columns to playoff_series

Revision ID: e3f5a7b9c1d2
Revises: d7a2f4c8e1b9
Create Date: 2026-05-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3f5a7b9c1d2'
down_revision: Union[str, Sequence[str], None] = 'd7a2f4c8e1b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add per-person, per-pillar, and best-streak columns to playoff_series.

    All columns are nullable so existing rows remain valid.  They are
    populated (and back-filled for stale rows) the next time a week is
    finalized via sunday_review or the series_history auto-heal.
    """
    op.add_column('playoff_series', sa.Column('david_days', sa.Integer(), nullable=True))
    op.add_column('playoff_series', sa.Column('steph_days', sa.Integer(), nullable=True))
    op.add_column('playoff_series', sa.Column('david_p1', sa.Integer(), nullable=True))
    op.add_column('playoff_series', sa.Column('david_p2', sa.Integer(), nullable=True))
    op.add_column('playoff_series', sa.Column('david_p3', sa.Integer(), nullable=True))
    op.add_column('playoff_series', sa.Column('steph_p1', sa.Integer(), nullable=True))
    op.add_column('playoff_series', sa.Column('steph_p2', sa.Integer(), nullable=True))
    op.add_column('playoff_series', sa.Column('steph_p3', sa.Integer(), nullable=True))
    op.add_column('playoff_series', sa.Column('best_streak', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('playoff_series', 'best_streak')
    op.drop_column('playoff_series', 'steph_p3')
    op.drop_column('playoff_series', 'steph_p2')
    op.drop_column('playoff_series', 'steph_p1')
    op.drop_column('playoff_series', 'david_p3')
    op.drop_column('playoff_series', 'david_p2')
    op.drop_column('playoff_series', 'david_p1')
    op.drop_column('playoff_series', 'steph_days')
    op.drop_column('playoff_series', 'david_days')
