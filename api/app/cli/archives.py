"""Commands that bring in old tournaments: Telegram channel exports, draft.aspirine.su, games entered by
hand."""

from sqlmodel import Session

from ..database import engine
from ..services.rosters import build_rosters


def export_telegram(channel: str, photos: bool) -> None:
    """Saves a Telegram channel's history to telegram/<channel>.json (see services/telegram_export.py)."""
    try:
        from ..services.telegram_export import export_channel
    except ImportError as e:
        raise SystemExit("Telethon isn't installed: venv/bin/pip install -r requirements-dev.txt") from e
    out, count, failed = export_channel(channel, *telegram_keys(), photos)
    print(
        f"{count} posts saved to {out}." + (f" {failed} photos failed: run it again to retry them." if failed else "")
    )


def telegram_keys():
    from ..config import settings

    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise SystemExit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env (my.telegram.org > API development tools).")
    return settings.telegram_api_id, settings.telegram_api_hash


def telegram_photos(channel: str, posts: str | None, since: str | None, until: str | None) -> None:
    """Downloads the photos of an exported channel's posts whose text matches (by default the results posts; every
    post when dates are given without --posts), between the dates if given."""
    from ..services.telegram_export import RESULT_POSTS, download_photos

    pattern = posts or ("" if since or until else RESULT_POSTS)
    wanted, saved, failed = download_photos(channel, *telegram_keys(), pattern, since or "", until or "9999")
    print(
        f"{wanted} posts: {saved} photos saved" + (f", {failed} failed: run it again to retry them." if failed else ".")
    )


def telegram_ocr(channel: str) -> None:
    """Reads the text on a channel's downloaded photos (macOS only)."""
    try:
        from ..services.telegram_export import recognize_photos

        out, count = recognize_photos(channel)
    except ImportError as e:
        raise SystemExit("Text recognition needs macOS and ocrmac: venv/bin/pip install -r requirements-dev.txt") from e
    print(f"Text of {count} photos in {out}.")


def add_manual_games(path: str) -> None:
    """Stores the games of hand-entered tournaments from a JSON file (see services/manual_games.py)."""
    import json

    from ..services.manual_games import import_manual_games

    with open(path, encoding="utf-8") as f, Session(engine) as session:
        try:
            stored = import_manual_games(session, json.load(f))
        except ValueError as e:
            raise SystemExit(str(e)) from e
    for tid, n in stored.items():
        print(f"{tid}: {n} matches.")


def export_aspirine(slugs: list[str]) -> None:
    """Saves old tournaments' games, replays and character list from draft.aspirine.su (services/aspirine_export.py)."""
    from ..services.aspirine_export import OUT, export

    counts = export(slugs, log=lambda line: print(line, flush=True))
    print(
        f"Saved to {OUT}: {counts['tournaments']} tournaments, {counts['replays']} replays"
        + (f"; {counts['failed']} not fetched: run it again to retry them." if counts["failed"] else ".")
    )


def import_aspirine() -> None:
    """Stores the old tournaments export-aspirine saved as matches (services/aspirine_import.py)."""
    from ..services.aspirine_import import import_aspirine as run

    with Session(engine) as session:
        try:
            counts = run(session)
        except (ValueError, FileNotFoundError) as e:
            raise SystemExit(str(e)) from e
        build_rosters(session)
    for tid, n in counts.items():
        print(
            f"{tid}: {n['matches']} matches, {n['games']} games ({n['replays']} with their draft), "
            f"{n['unknown players']} players the site doesn't know"
        )
