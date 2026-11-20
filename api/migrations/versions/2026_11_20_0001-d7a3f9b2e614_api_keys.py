"""api keys for the stream api

Revision ID: d7a3f9b2e614
Revises: c5d2e8a1f470
Create Date: 2026-11-20 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'd7a3f9b2e614'
down_revision: Union[str, Sequence[str], None] = 'c5d2e8a1f470'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'apikey',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('note', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
        sa.Column('key_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('prefix', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('apikey') as batch_op:
        batch_op.create_index(batch_op.f('ix_apikey_key_hash'), ['key_hash'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('apikey') as batch_op:
        batch_op.drop_index(batch_op.f('ix_apikey_key_hash'))
    op.drop_table('apikey')
