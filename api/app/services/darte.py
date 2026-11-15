"""Where the tournament site (darte.gg's Abyss) lives: its pages, its public API and its drafts' socket.

Everything that asks the site takes the address from here, so a move to another address is one setting (SITE_URL in
.env, config.site_url) and nothing in the code. What the site is asked for, and which of its fields are read, is
checked against a live site by `python -m app.cli check-site` (services/site_check.py).
"""

from urllib.parse import urlsplit

from ..config import settings

SITE = settings.site_url.rstrip("/")
API = f"{SITE}/api/abyss"
_parts = urlsplit(SITE)
# socket.io v4 on the site's own host, namespace /draft
SOCKET = f"{'ws' if _parts.scheme == 'http' else 'wss'}://{_parts.netloc}/socket.io/draft/"


def draft_url(draft_id: str, key: str) -> str:
    """A draft's page for a spectator. Built when it's shown, never stored, so it follows the site's address."""
    return f"{SITE}/draft?draft_id={draft_id}&session_key={key}&show_costs=true&show_controls"
