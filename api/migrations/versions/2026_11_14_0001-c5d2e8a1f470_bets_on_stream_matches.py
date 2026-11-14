"""bets on the streams' matches: a market may belong to a stream match

Revision ID: c5d2e8a1f470
Revises: b81f4d2a6c39
Create Date: 2026-11-14 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'c5d2e8a1f470'
down_revision: Union[str, Sequence[str], None] = 'b81f4d2a6c39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('betmarket') as batch_op:
        batch_op.add_column(sa.Column('stream_match_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.create_index(batch_op.f('ix_betmarket_stream_match_id'), ['stream_match_id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('betmarket') as batch_op:
        batch_op.drop_index(batch_op.f('ix_betmarket_stream_match_id'))
        batch_op.drop_column('stream_match_id')
