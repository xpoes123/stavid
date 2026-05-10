"""add user_preferences table

Per-user playoff preferences (custom pillar names + check-in hour). All
override columns are nullable so a single row can carry partial overrides.

Revision ID: 0a1b2c3d4e5f
Revises: f3a2b4c5d6e7
Create Date: 2026-05-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a1b2c3d4e5f'
down_revision: Union[str, Sequence[str], None] = 'f3a2b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_preferences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('pillar1', sa.Text(), nullable=True),
        sa.Column('pillar2', sa.Text(), nullable=True),
        sa.Column('pillar3', sa.Text(), nullable=True),
        sa.Column('checkin_hour', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_user_preferences_guild_id'),
        'user_preferences',
        ['guild_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_user_preferences_user_id'),
        'user_preferences',
        ['user_id'],
        unique=False,
    )
    op.create_index(
        'ix_user_preferences_guild_user',
        'user_preferences',
        ['guild_id', 'user_id'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_user_preferences_guild_user', table_name='user_preferences')
    op.drop_index(op.f('ix_user_preferences_user_id'), table_name='user_preferences')
    op.drop_index(op.f('ix_user_preferences_guild_id'), table_name='user_preferences')
    op.drop_table('user_preferences')
