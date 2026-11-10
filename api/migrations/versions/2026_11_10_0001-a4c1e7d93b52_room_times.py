"""room times kept out of draftstate.raw

Revision ID: a4c1e7d93b52
Revises: 5e8b1c3d7a20
Create Date: 2026-11-10 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4c1e7d93b52'
down_revision: Union[str, Sequence[str], None] = '5e8b1c3d7a20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROWS = """
    INSERT INTO roomtime (draft_id, slot, room1, room2, room3, room_count)
    SELECT NEW.draft_id, CAST(p.key AS INTEGER),
           json_extract(p.value, '$.clearTimeRoom1'), json_extract(p.value, '$.clearTimeRoom2'),
           json_extract(p.value, '$.clearTimeRoom3'),
           CASE WHEN json_valid(NEW.raw) THEN json_extract(NEW.raw, '$.roomCount') END
    FROM json_each(CASE WHEN json_valid(NEW.raw) THEN NEW.raw ELSE '{}' END, '$.players') p;
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'roomtime',
        sa.Column('draft_id', sa.String(), nullable=False),
        sa.Column('slot', sa.Integer(), nullable=False),
        sa.Column('room1', sa.Integer(), nullable=True),
        sa.Column('room2', sa.Integer(), nullable=True),
        sa.Column('room3', sa.Integer(), nullable=True),
        sa.Column('room_count', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('draft_id', 'slot'),
    )
    # The times of every game stored so far
    op.execute("""
        INSERT INTO roomtime (draft_id, slot, room1, room2, room3, room_count)
        SELECT s.draft_id, CAST(p.key AS INTEGER),
               json_extract(p.value, '$.clearTimeRoom1'), json_extract(p.value, '$.clearTimeRoom2'),
               json_extract(p.value, '$.clearTimeRoom3'), json_extract(s.raw, '$.roomCount')
        FROM draftstate s, json_each(s.raw, '$.players') p
        WHERE json_valid(s.raw)
    """)
    # From here on the database keeps them itself, on every write to draftstate
    op.execute(f"""CREATE TRIGGER IF NOT EXISTS roomtime_insert AFTER INSERT ON draftstate BEGIN
    DELETE FROM roomtime WHERE draft_id = NEW.draft_id;{ROWS}END""")
    op.execute(f"""CREATE TRIGGER IF NOT EXISTS roomtime_update AFTER UPDATE OF draft_id, raw ON draftstate BEGIN
    DELETE FROM roomtime WHERE draft_id IN (OLD.draft_id, NEW.draft_id);{ROWS}END""")
    op.execute("""CREATE TRIGGER IF NOT EXISTS roomtime_delete AFTER DELETE ON draftstate BEGIN
    DELETE FROM roomtime WHERE draft_id = OLD.draft_id;
END""")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS roomtime_insert")
    op.execute("DROP TRIGGER IF EXISTS roomtime_update")
    op.execute("DROP TRIGGER IF EXISTS roomtime_delete")
    op.drop_table('roomtime')
