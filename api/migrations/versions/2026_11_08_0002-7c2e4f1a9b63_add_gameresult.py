"""add gameresult

Revision ID: 7c2e4f1a9b63
Revises: 3b7e5d2a9c41
Create Date: 2026-11-08 00:02:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '7c2e4f1a9b63'
down_revision: Union[str, Sequence[str], None] = '3b7e5d2a9c41'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'gameresult',
        sa.Column('draft_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('slot', sa.Integer(), nullable=False),
        sa.Column('match_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('rooms', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('restarts', sa.Integer(), nullable=False),
        sa.Column('before', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('set_by', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['draft_id'], ['matchdraft.id'], ),
        sa.ForeignKeyConstraint(['match_id'], ['match.id'], ),
        sa.PrimaryKeyConstraint('draft_id', 'slot'),
    )
    op.create_index(op.f('ix_gameresult_match_id'), 'gameresult', ['match_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_gameresult_match_id'), table_name='gameresult')
    op.drop_table('gameresult')
