"""bets for points: balances, markets, bets and the bet tester mark

Revision ID: b81f4d2a6c39
Revises: 2a6d9f4c7e15
Create Date: 2026-11-13 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b81f4d2a6c39'
down_revision: Union[str, Sequence[str], None] = '2a6d9f4c7e15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('user') as batch_op:
        batch_op.add_column(sa.Column('bet_tester', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        'betbalance',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('month', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('balance', sa.Integer(), nullable=False),
        sa.Column('handicap', sa.Integer(), nullable=False),
        sa.Column('streak', sa.Integer(), nullable=False),
        sa.Column('last_bonus_day', sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('user_id', 'month'),
    )
    op.create_table(
        'betmarket',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scheduled_match_id', sa.Integer(), nullable=True),
        sa.Column('month', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('tournament_title', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('player1_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('player1_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('player2_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('player2_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('starts_at', sa.DateTime(), nullable=False),
        sa.Column('start_p1', sa.Float(), nullable=False),
        sa.Column('stake1', sa.Integer(), nullable=False),
        sa.Column('stake2', sa.Integer(), nullable=False),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('winner', sa.Integer(), nullable=True),
        sa.Column('settled_by', sa.Uuid(), nullable=True),
        sa.Column('settled_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_betmarket_scheduled_match_id'), 'betmarket', ['scheduled_match_id'])
    op.create_index(op.f('ix_betmarket_month'), 'betmarket', ['month'])
    op.create_table(
        'bet',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('market_id', sa.Integer(), nullable=False),
        sa.Column('month', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('side', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('odds', sa.Float(), nullable=False),
        sa.Column('payout', sa.Integer(), nullable=False),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['market_id'], ['betmarket.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_bet_user_id'), 'bet', ['user_id'])
    op.create_index(op.f('ix_bet_market_id'), 'bet', ['market_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('bet')
    op.drop_table('betmarket')
    op.drop_table('betbalance')
    with op.batch_alter_table('user') as batch_op:
        batch_op.drop_column('bet_tester')
