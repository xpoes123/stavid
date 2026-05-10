"""add last_bought_at to supply_items

Revision ID: 2c3d4e5f6a7b
Revises: 0a1b2c3d4e5f
Create Date: 2026-05-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c3d4e5f6a7b'
down_revision: Union[str, Sequence[str], None] = '0a1b2c3d4e5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'supply_items',
        sa.Column('last_bought_at', sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('supply_items', 'last_bought_at')
