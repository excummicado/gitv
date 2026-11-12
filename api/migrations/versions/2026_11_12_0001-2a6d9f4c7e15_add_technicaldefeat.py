"""add technicaldefeat

Revision ID: 2a6d9f4c7e15
Revises: 63d518357604
Create Date: 2026-11-12 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '2a6d9f4c7e15'
down_revision: Union[str, Sequence[str], None] = '63d518357604'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'technicaldefeat',
        sa.Column('draft_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('slot', sa.Integer(), nullable=False),
        sa.Column('match_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('set_by', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['draft_id'], ['matchdraft.id'], ),
        sa.ForeignKeyConstraint(['match_id'], ['match.id'], ),
        sa.PrimaryKeyConstraint('draft_id'),
    )
    op.create_index(op.f('ix_technicaldefeat_match_id'), 'technicaldefeat', ['match_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_technicaldefeat_match_id'), table_name='technicaldefeat')
    op.drop_table('technicaldefeat')
