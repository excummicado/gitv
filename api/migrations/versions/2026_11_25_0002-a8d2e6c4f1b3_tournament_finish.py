"""tournaments finished by hand

Revision ID: a8d2e6c4f1b3
Revises: f3c9a1d7b2e8
Create Date: 2026-11-25 00:02:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'a8d2e6c4f1b3'
down_revision: Union[str, Sequence[str], None] = 'f3c9a1d7b2e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'tournamentfinish',
        sa.Column('tournament_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('finished_by', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('tournament_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('tournamentfinish')
