"""user organizers instead of the operator organizer roles

Revision ID: 63d518357604
Revises: 6f3a9c2e8d14
Create Date: 2026-11-10 00:02:00.000000

"""
from datetime import UTC, datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '63d518357604'
down_revision: Union[str, Sequence[str], None] = '6f3a9c2e8d14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = (
    'user', 'writer', 'event_organizer', 'organizer_abyss_cup', 'organizer_hoth', 'organizer_newgen',
    'organizer_icephoenix', 'organizer_abyss_ascend', 'admin', 'super_admin',
)
NEW = ('user', 'writer', 'event_organizer', 'admin', 'super_admin')

# Frozen copy of services/organizers.py OPERATORS as it was when the roles were dropped: the names (as the site
# showed the organizer) each role was limited to, compared without case or punctuation; a trailing star is a prefix.
OPERATORS = {
    'organizer_abyss_cup': ('Abyss Cup',),
    'organizer_hoth': ('House of the Hearth', 'HotH'),
    'organizer_newgen': ('Abyss New Gen', 'NewGen'),
    'organizer_icephoenix': ('Icephoenix*',),
    'organizer_abyss_ascend': ('Abyss Ascend',),
}


def normalize(name: str) -> str:
    """Frozen copy of services/challonge.normalize."""
    return ''.join(ch for ch in name.casefold() if ch.isalnum())


def matches(role: str, name: str | None) -> bool:
    if not name:
        return False
    shown = normalize(name)
    return any(
        shown == normalize(n) or (n.endswith('*') and shown.startswith(normalize(n[:-1])))
        for n in OPERATORS[role]
    )


def role_accounts(conn) -> dict[str, set[str]]:
    """{role: the organizer accounts (as they count after merges) its holders ran}, told as the code did when the
    roles were dropped (services/organizers.operator_of_organizer): by the organizer's shown name (its own name set
    with set-organizer; else, for a merged account, its organizer's name on the site; else its own name on the
    site) or by its own name on the site."""
    aliases = {
        oid: (name, into)
        for oid, name, into in conn.execute(sa.text('SELECT organizer_id, name, into_id FROM organizeralias'))
    }
    site_names: dict[str, str | None] = {}
    accounts: list[tuple[str, str | None]] = []
    for oid, name in conn.execute(sa.text(
        'SELECT organizer_id, organizer_name FROM tournamentinfo WHERE organizer_id IS NOT NULL'
    )):
        site_names.setdefault(oid, name)
        accounts.append((oid, name))
    accounts += [(oid, None) for oid in aliases]  # organizers known only by a name or merge set by hand

    def root(oid: str) -> str:
        seen = set()
        while (a := aliases.get(oid)) and a[1] and a[1] not in seen:
            seen.add(oid)
            oid = a[1]
        return oid

    found: dict[str, set[str]] = {role: set() for role in OPERATORS}
    for oid, own_name in accounts:
        final = root(oid)
        alias_name = aliases.get(final, (None, None))[0]
        shown = alias_name or (site_names.get(final) if final != oid else None) or own_name
        for role in OPERATORS:
            if matches(role, shown) or matches(role, own_name):
                found[role].add(final)
    return found


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    holders = conn.execute(sa.text(
        "SELECT id, nickname, role FROM user WHERE role LIKE 'organizer\\_%' ESCAPE '\\'"
    )).all()
    accounts = role_accounts(conn) if holders else {}
    # Checked before anything changes: SQLite doesn't roll back a created table, and a rerun must start clean.
    missing = [f'{nickname} ({role})' for _, nickname, role in holders if not accounts.get(role)]
    if missing:
        raise RuntimeError(
            'No organizer account on the site goes by the name of these members\' organizer roles, so their '
            'access can\'t be carried over: ' + ', '.join(missing) + '. Set the organizer\'s name with '
            'app.cli set-organizer (or change the member\'s role) and run the migration again.'
        )
    op.create_table(
        'userorganizer',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('organizer_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('granted_by', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('user_id', 'organizer_id'),
    )
    if holders:
        now = datetime.now(UTC).replace(tzinfo=None)
        for user_id, _, role in holders:
            for oid in sorted(accounts[role]):
                conn.execute(
                    sa.text('INSERT INTO userorganizer (user_id, organizer_id, granted_by, created_at) '
                            'VALUES (:u, :o, NULL, :t)'),
                    {'u': user_id, 'o': oid, 't': now},
                )
        # The member keeps running those tournaments through the rows above; their token, made for the old role,
        # stops working, so they sign in again.
        conn.execute(sa.text("UPDATE user SET role = 'user' WHERE role LIKE 'organizer\\_%' ESCAPE '\\'"))
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('role',
               existing_type=sa.Enum(*OLD, name='role'),
               type_=sa.Enum(*NEW, name='role'),
               existing_nullable=False,
               existing_server_default=sa.text("'user'"))


def downgrade() -> None:
    """Downgrade schema: a member who ran some organizers' tournaments becomes an event organizer (the old roles
    can't be told back from the accounts)."""
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('role',
               existing_type=sa.Enum(*NEW, name='role'),
               type_=sa.Enum(*OLD, name='role'),
               existing_nullable=False,
               existing_server_default=sa.text("'user'"))
    op.execute(
        "UPDATE user SET role = 'event_organizer' WHERE role = 'user' "
        "AND id IN (SELECT user_id FROM userorganizer)"
    )
    op.drop_table('userorganizer')
