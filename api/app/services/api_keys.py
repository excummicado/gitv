"""Keys to the stream API (routers/stream_api.py), issued by a super admin on the profile page.

A key is "gitv_" and 32 random bytes; it's shown once, at issue, and only its SHA-256 is stored (the key is random
enough that a plain hash can't be reversed), with its first characters to tell keys apart in the list."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from ..models import ApiKey

PREFIX = "gitv_"
SHOWN = 12  # characters of the key kept in the clear: "gitv_" and seven more
# How often a key's last use is written down: every request would be a write per overlay refresh.
TOUCH_EVERY = timedelta(minutes=1)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue(session: Session, note: str, created_by=None) -> tuple[ApiKey, str]:
    """A new key with its note; returns the row and the key itself, the only time it can be seen."""
    raw = PREFIX + secrets.token_urlsafe(32)
    row = ApiKey(
        note=note, key_hash=hash_key(raw), prefix=raw[:SHOWN], created_at=datetime.now(UTC), created_by=created_by
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row, raw


def check(session: Session, raw: str | None, now: datetime | None = None) -> ApiKey | None:
    """The key's row when it's a key that works (issued and not revoked), else None; notes its use."""
    if not raw or not raw.startswith(PREFIX):
        return None
    row = session.exec(select(ApiKey).where(ApiKey.key_hash == hash_key(raw))).first()
    if row is None or row.revoked_at is not None:
        return None
    now = now or datetime.now(UTC)
    last = row.last_used_at
    if last is not None and last.tzinfo is None:  # SQLite gives times back without their zone
        last = last.replace(tzinfo=UTC)
    if last is None or now - last >= TOUCH_EVERY:
        row.last_used_at = now
        session.add(row)
        session.commit()
    return row
