"""operator organizer roles

Revision ID: 9d4a2b7e1c58
Revises: 7c2e4f1a9b63
Create Date: 2026-11-08 00:03:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9d4a2b7e1c58'
down_revision: Union[str, Sequence[str], None] = '7c2e4f1a9b63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = ('user', 'writer', 'event_organizer', 'admin', 'super_admin')
NEW = (
    'user', 'writer', 'event_organizer', 'organizer_abyss_cup', 'organizer_hoth', 'organizer_newgen',
    'organizer_icephoenix', 'organizer_abyss_ascend', 'admin', 'super_admin',
)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('role',
               existing_type=sa.Enum(*OLD, name='role'),
               type_=sa.Enum(*NEW, name='role'),
               existing_nullable=False,
               existing_server_default=sa.text("'user'"))


def downgrade() -> None:
    """Downgrade schema: an operator's organizer becomes an event organizer."""
    op.execute("UPDATE user SET role = 'event_organizer' WHERE role LIKE 'organizer\\_%' ESCAPE '\\'")
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('role',
               existing_type=sa.Enum(*NEW, name='role'),
               type_=sa.Enum(*OLD, name='role'),
               existing_nullable=False,
               existing_server_default=sa.text("'user'"))
