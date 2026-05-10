"""merge datenight, watchlist/bucket, and outing-wishlist heads into one chain

The schema diverged into three concurrent heads off ``a9c2e4f6b8d1``:
  - ``b2d4f6a8c1e3`` (datenight tables)
  - ``e2a4c6d8f1b3`` (bucket list, via watchlist)
  - ``c3a5e7f9b1d2`` (outing wishlist)

This is a no-op merge so future migrations chain off a single head again.

Revision ID: f3a2b4c5d6e7
Revises: b2d4f6a8c1e3, e2a4c6d8f1b3, c3a5e7f9b1d2
Create Date: 2026-05-10 00:00:00.000000

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = 'f3a2b4c5d6e7'
down_revision: Union[str, Sequence[str], None] = (
    'b2d4f6a8c1e3',
    'e2a4c6d8f1b3',
    'c3a5e7f9b1d2',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
