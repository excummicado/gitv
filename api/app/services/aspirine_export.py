"""Save what draft.aspirine.su has on old Abyss Cup tournaments (app.cli export-aspirine), before it's gone: each
tournament's page data (stages, games with room times, restarts, penalties and both teams), the replay of every game
(the draft: bans and picks in order), and the site's character list (its own ids with the game's character ids).

That server often stops a response after about 16 KB and the connection hangs; over HTTP/1.0 about every other
request comes in whole. So everything is fetched with curl over HTTP/1.0 (Python's own clients can't make that request
through its Cloudflare) and tried again until it's complete, with a pause between requests. Static files (the
character list) are asked for in byte ranges under that size, which do come in whole. Pages already saved are kept,
so a second run only fetches what's missing.

Files, under api/aspirine/ (not in git): tournaments/<slug>.json, replays/<game id>.json and db.js.
"""

import html
import json
import subprocess
import time
from pathlib import Path

SITE = "https://draft.aspirine.su"
OUT = Path(__file__).resolve().parents[2] / "aspirine"
USER_AGENT = "Mozilla/5.0 (GITV stats)"
TRIES = 12
PAUSE = 2.0  # seconds between requests
# The character list script, as the site's pages load it
DB_SCRIPT = "/js/db.js?0.6.13"
CHUNK = 15_000  # bytes per range request, under the size where responses stop


def fetch(path: str, *options: str) -> bytes:
    """One HTTP/1.0 request; b"" when it fails or times out."""
    done = subprocess.run(
        ["curl", "-s", "--http1.0", "--max-time", "20", "-A", USER_AGENT, *options, SITE + path],
        capture_output=True,
        check=False,
    )
    return done.stdout


def fetch_ranges(path: str) -> bytes:
    """A static file, CHUNK bytes at a time until a range comes back short; cut short when a range fails."""
    body = b""
    while True:
        part = fetch(path, "-r", f"{len(body)}-{len(body) + CHUNK - 1}")
        body += part
        if len(part) < CHUNK:
            return body


def page_data(body: bytes) -> dict | None:
    """The JSON a page carries in its <textarea id="data">, or None when the page came in cut short."""
    text = body.decode("utf-8", errors="replace")
    start = text.find('<textarea id="data"')
    end = text.find("</textarea>", start)
    if start < 0 or end < 0:
        return None
    try:
        return json.loads(html.unescape(text[text.index(">", start) + 1 : end]).strip())
    except ValueError:
        return None


def fetch_data(path: str) -> dict | None:
    """A page's data, trying again until it comes in whole (at most TRIES times)."""
    for _ in range(TRIES):
        data = page_data(fetch(path))
        time.sleep(PAUSE)
        if data is not None:
            return data
    return None


def fetch_script(path: str) -> bytes | None:
    """A script: the same twice in a row counts as whole."""
    last = None
    for _ in range(TRIES):
        body = fetch_ranges(path)
        time.sleep(PAUSE)
        if body and body == last:
            return body
        last = body
    return None


def export(slugs: list[str], log=print) -> dict[str, int]:
    """Saves the tournaments (draft.aspirine.su/tournament/<slug>/), the replays of all their games and the character
    list; returns counts of what's saved and what couldn't be fetched."""
    (OUT / "tournaments").mkdir(parents=True, exist_ok=True)
    (OUT / "replays").mkdir(parents=True, exist_ok=True)
    counts = {"tournaments": 0, "replays": 0, "failed": 0}
    games = []
    for slug in slugs:
        path = OUT / "tournaments" / f"{slug}.json"
        data = json.loads(path.read_text()) if path.exists() else fetch_data(f"/tournament/{slug}/")
        if data is None:
            log(f"{slug}: couldn't get the whole page")
            counts["failed"] += 1
            continue
        path.write_text(json.dumps(data, ensure_ascii=False))
        counts["tournaments"] += 1
        found = [m for stage in data.get("stages", []) for m in stage.get("matches", []) if m.get("draft")]
        log(f"{slug}: {data.get('title')}, {len(found)} games")
        games += found
    for n, game in enumerate(games, start=1):
        path = OUT / "replays" / f"{game['id']}.json"
        if not path.exists():
            data = fetch_data(game["draft"])
            if data is None:
                log(f"  replay {game['id']}: couldn't get it whole")
                counts["failed"] += 1
                continue
            path.write_text(json.dumps(data, ensure_ascii=False))
        counts["replays"] += 1
        if n % 20 == 0:
            log(f"  {n} of {len(games)} replays...")
    db = OUT / "db.js"
    if not db.exists():
        body = fetch_script(DB_SCRIPT)
        if body:
            db.write_bytes(body)
        else:
            log("db.js: couldn't get it whole")
            counts["failed"] += 1
    return counts
