"""add og_title, og_price, og_image to shopping_items

Revision ID: a9c2e4f6b8d1
Revises: f1a3b5c7d9e2
Create Date: 2026-04-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9c2e4f6b8d1'
down_revision: Union[str, Sequence[str], None] = 'f1a3b5c7d9e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('shopping_items', sa.Column('og_title', sa.Text(), nullable=True))
    op.add_column('shopping_items', sa.Column('og_price', sa.Text(), nullable=True))
    op.add_column('shopping_items', sa.Column('og_image', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('shopping_items', 'og_image')
    op.drop_column('shopping_items', 'og_price')
    op.drop_column('shopping_items', 'og_title')
