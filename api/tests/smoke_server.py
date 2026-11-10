"""Serves the API on the smoke tests' small database (smoke_data.py): `python -m tests.smoke_server [port]`.

A new database file each start, in a temporary folder, so gitv.db is never touched. Nothing leaves the machine: the
background sync stays off and connections to anything but this computer are refused, so pages that would ask other
sites (running tournaments, the stream) show what they show when those sites are down, the same every run."""

import json
import os
import socket
import sys
import tempfile
import time
from pathlib import Path

# Before the app is imported: its settings and engine are read at import. Explicit values win over a local api/.env.
DB = Path(tempfile.mkdtemp(prefix="gitv-smoke-")) / "smoke.db"
os.environ.update(
    DATABASE_URL=f"sqlite:///{DB}",
    SYNC_INTERVAL="0",
    FRONTEND_URL="http://localhost:5173",
    TWITCH_CLIENT_ID="",
    TWITCH_CLIENT_SECRET="",
    HOTH_HUB_KEY="",
)
for name in ("SECRET_KEY", "DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET"):
    os.environ.setdefault(name, "smoke-only")

_connect = socket.socket.connect


def _local_only(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(host, str) and host not in ("127.0.0.1", "::1", "localhost") and not host.startswith("/"):
        raise ConnectionRefusedError(f"smoke tests stay offline: {host}")
    return _connect(self, address)


socket.socket.connect = _local_only
# getaddrinfo would still ask DNS before connecting; answer it from here for everything but this computer.
_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda host, *a, **k: (
    _getaddrinfo(host, *a, **k) if host in (None, "127.0.0.1", "::1", "localhost") else _refuse(host)
)


def _refuse(host):
    raise socket.gaierror(f"smoke tests stay offline: {host}")


def main() -> None:
    import uvicorn
    from sqlmodel import Session, SQLModel

    from app.database import engine
    from app.main import app
    from app.services import sync

    from .smoke_data import seed

    # The sync's state goes beside the database, not into api/. It says running tournaments were just asked for and
    # there are none, so the API never tries the site (and the home page shows the same every run).
    sync.STATE_FILE = DB.parent / "sync-state.json"
    sync.STATE_FILE.write_text(json.dumps({"live": {"at": time.time() + 10 * 365 * 86400, "items": []}}))

    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed(session)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8181
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
