"""user token version, for signing out everywhere

Revision ID: 6f3a9c2e8d14
Revises: a4c1e7d93b52
Create Date: 2026-11-10 00:02:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6f3a9c2e8d14'
down_revision: Union[str, Sequence[str], None] = 'a4c1e7d93b52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Existing tokens carry no version and count as 0, so every account starts there and nobody is signed out.
    with op.batch_alter_table('user') as batch_op:
        batch_op.add_column(sa.Column('token_version', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('user') as batch_op:
        batch_op.drop_column('token_version')
