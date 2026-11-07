"""add matchwinner

Revision ID: 3b7e5d2a9c41
Revises: 1f44fc03dfd7
Create Date: 2026-11-08 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '3b7e5d2a9c41'
down_revision: Union[str, Sequence[str], None] = '1f44fc03dfd7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'matchwinner',
        sa.Column('match_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('player_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('source', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['match_id'], ['match.id'], ),
        sa.PrimaryKeyConstraint('match_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('matchwinner')
