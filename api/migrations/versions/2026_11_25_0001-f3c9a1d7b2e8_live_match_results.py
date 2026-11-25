"""upcoming matches resolved by hand

Revision ID: f3c9a1d7b2e8
Revises: e2b8c4f1a957
Create Date: 2026-11-25 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'f3c9a1d7b2e8'
down_revision: Union[str, Sequence[str], None] = 'e2b8c4f1a957'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'livematchresult',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('tournament_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('player1_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('player1_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('player2_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('player2_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('winner_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('set_by', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('set_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_livematchresult_tournament_id'), 'livematchresult', ['tournament_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_livematchresult_tournament_id'), table_name='livematchresult')
    op.drop_table('livematchresult')
