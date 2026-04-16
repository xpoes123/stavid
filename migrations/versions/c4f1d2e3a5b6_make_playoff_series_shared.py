"""make playoff series shared

Revision ID: c4f1d2e3a5b6
Revises: b3e7c9d1f2a4
Create Date: 2026-04-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4f1d2e3a5b6'
down_revision: Union[str, Sequence[str], None] = 'b3e7c9d1f2a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop user_id from playoff_series so the record is shared per guild/week.

    Existing per-user rows cannot be meaningfully converted to the shared model
    (a shared win requires both players to have won the same day, which can't be
    derived from the cached per-user tallies). Clearing the table is safe: the
    series state is always recalculated from playoff_checkins, so it will be
    rebuilt automatically on the next check-in.
    """
    op.execute("DELETE FROM playoff_series")
    op.drop_index(op.f('ix_playoff_series_user_id'), table_name='playoff_series')
    op.drop_column('playoff_series', 'user_id')


def downgrade() -> None:
    """Restore per-user series rows (column re-added as nullable for safety)."""
    op.add_column(
        'playoff_series',
        sa.Column('user_id', sa.BigInteger(), nullable=True),
    )
    op.create_index(
        op.f('ix_playoff_series_user_id'),
        'playoff_series',
        ['user_id'],
        unique=False,
    )
