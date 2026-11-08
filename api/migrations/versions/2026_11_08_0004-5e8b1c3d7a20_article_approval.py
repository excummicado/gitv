"""article approval

Revision ID: 5e8b1c3d7a20
Revises: 9d4a2b7e1c58
Create Date: 2026-11-08 00:04:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e8b1c3d7a20'
down_revision: Union[str, Sequence[str], None] = '9d4a2b7e1c58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('newspost', schema=None) as batch_op:
        batch_op.add_column(sa.Column('approved_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('approved_by', sa.Uuid(), nullable=True))
        batch_op.create_foreign_key('fk_newspost_approved_by_user', 'user', ['approved_by'], ['id'])
    # Every article already there was published as it was imported
    op.execute("UPDATE newspost SET approved_at = created_at")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('newspost', schema=None) as batch_op:
        batch_op.drop_constraint('fk_newspost_approved_by_user', type_='foreignkey')
        batch_op.drop_column('approved_by')
        batch_op.drop_column('approved_at')
