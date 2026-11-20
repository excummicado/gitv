"""stream nickname spellings an admin said aren't a player

Revision ID: e2b8c4f1a957
Revises: d7a3f9b2e614
Create Date: 2026-11-20 00:02:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'e2b8c4f1a957'
down_revision: Union[str, Sequence[str], None] = 'd7a3f9b2e614'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'namerejection',
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('name', 'user_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('namerejection')
