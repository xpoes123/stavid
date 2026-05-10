"""add chore_templates and chore_instances

Revision ID: 1b2c3d4e5f60
Revises: 0a1b2c3d4e5f
Create Date: 2026-05-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1b2c3d4e5f60'
down_revision: Union[str, Sequence[str], None] = '0a1b2c3d4e5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chore_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('recurrence', sa.Text(), nullable=False),
        sa.Column('default_assignee_id', sa.BigInteger(), nullable=True),
        sa.Column('last_assignee_id', sa.BigInteger(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_chore_templates_guild_id'),
        'chore_templates',
        ['guild_id'],
        unique=False,
    )

    op.create_table(
        'chore_instances',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('template_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('assignee_id', sa.BigInteger(), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('completed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_by', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_chore_instances_guild_id'),
        'chore_instances',
        ['guild_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_chore_instances_due_date'),
        'chore_instances',
        ['due_date'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_chore_instances_due_date'), table_name='chore_instances')
    op.drop_index(op.f('ix_chore_instances_guild_id'), table_name='chore_instances')
    op.drop_table('chore_instances')
    op.drop_index(op.f('ix_chore_templates_guild_id'), table_name='chore_templates')
    op.drop_table('chore_templates')
