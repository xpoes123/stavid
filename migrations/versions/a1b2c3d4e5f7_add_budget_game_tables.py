"""add budget game tables

Revision ID: a1b2c3d4e5f7
Revises: 3d4e5f6a7b8c
Create Date: 2026-08-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f7'
down_revision: Union[str, Sequence[str], None] = '3d4e5f6a7b8c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'game_players',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('monthly_cap_cents', sa.Integer(), nullable=False, server_default='120000'),
        sa.Column('streak', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('freezes_remaining', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('freeze_month', sa.Text(), nullable=False, server_default=''),
        sa.Column('last_scored', sa.Text(), nullable=False, server_default=''),
        sa.Column('last_brief_date', sa.Text(), nullable=False, server_default=''),
        sa.Column('access_url', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_game_players_guild_id'), 'game_players', ['guild_id'])
    op.create_index(op.f('ix_game_players_user_id'), 'game_players', ['user_id'])

    op.create_table(
        'game_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('simplefin_id', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False, server_default=''),
        sa.Column('kind', sa.Text(), nullable=False, server_default='card'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_game_accounts_user_id'), 'game_accounts', ['user_id'])
    op.create_index(op.f('ix_game_accounts_simplefin_id'), 'game_accounts', ['simplefin_id'])

    op.create_table(
        'game_txns',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('simplefin_id', sa.Text(), nullable=False),
        sa.Column('account_id', sa.Text(), nullable=False, server_default=''),
        sa.Column('posted_date', sa.Date(), nullable=False),
        sa.Column('cents', sa.Integer(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('money_type', sa.Text(), nullable=False, server_default='Variable'),
        sa.Column('category', sa.Text(), nullable=False, server_default='Other'),
        sa.Column('confidence', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('needs_review', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('simplefin_id'),
    )
    op.create_index(op.f('ix_game_txns_user_id'), 'game_txns', ['user_id'])
    op.create_index(op.f('ix_game_txns_simplefin_id'), 'game_txns', ['simplefin_id'])
    op.create_index(op.f('ix_game_txns_posted_date'), 'game_txns', ['posted_date'])

    op.create_table(
        'game_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('merchant_key', sa.Text(), nullable=False),
        sa.Column('category', sa.Text(), nullable=False),
        sa.Column('money_type', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_game_rules_user_id'), 'game_rules', ['user_id'])
    op.create_index(op.f('ix_game_rules_merchant_key'), 'game_rules', ['merchant_key'])


def downgrade() -> None:
    op.drop_table('game_rules')
    op.drop_table('game_txns')
    op.drop_table('game_accounts')
    op.drop_table('game_players')
