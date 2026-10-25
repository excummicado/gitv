"""Export a Telegram channel's whole history as JSON (app.cli export-telegram), to find old tournaments in it: every
post's date, text, links and media, oldest first, and optionally its photos (brackets are often pictures).

It logs in as a Telegram user, with the app keys from my.telegram.org (TELEGRAM_API_ID and TELEGRAM_API_HASH in .env):
the first run asks in the terminal for the phone number and the login code Telegram sends, and the session file
(telegram.session, not in git) keeps the login for later runs. Telethon waits out Telegram's rate limits by itself.
A photo that won't download (Telegram's servers time out now and then) is noted on its post and skipped, photos
already saved aren't fetched again, so a second run picks up where the first left off, and the posts read so far
are saved even if the run stops."""

import json
import re
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[2]
SESSION = API_DIR / "telegram"  # Telethon adds .session
EXPORT_DIR = API_DIR / "telegram"
# Rate-limit waits up to this many seconds are slept through instead of failing.
FLOOD_WAIT = 300


def post_links(message) -> list[str]:
    """The links in a post: written out in the text, behind words, and on its buttons."""
    from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl

    links = []
    for entity, text in message.get_entities_text() if message.entities else []:
        if isinstance(entity, MessageEntityTextUrl):
            links.append(entity.url)
        elif isinstance(entity, MessageEntityUrl):
            links.append(text)
    for row in message.buttons or []:
        links += [b.url for b in row if getattr(b, "url", None)]
    return list(dict.fromkeys(links))


def save_photo(message, photo_dir: Path) -> tuple[str | None, str | None]:
    """(saved path relative to api/, error) for a post's photo: the copy from an earlier run if there is one, else a
    fresh download; a failed download leaves no empty file behind."""
    for done in photo_dir.glob(f"{message.id}.*"):
        if done.stat().st_size:
            return str(done.relative_to(API_DIR)), None
        done.unlink()
    try:
        saved = message.download_media(file=str(photo_dir / str(message.id)))
    except Exception as e:  # noqa: BLE001 - timeouts, server errors: note it and go on with the rest
        for partial in photo_dir.glob(f"{message.id}.*"):
            partial.unlink()
        return None, f"{type(e).__name__}: {e}"
    return (str(Path(saved).relative_to(API_DIR)) if saved else None), None


def export_channel(channel: str, api_id: int, api_hash: str, photos: bool = False) -> tuple[Path, int, int]:
    """Saves the channel's posts to telegram/<channel>.json (photos to telegram/<channel>/<post id>.jpg when asked);
    returns the file, how many posts it has and how many photos couldn't be downloaded."""
    from telethon.sync import TelegramClient

    name = channel.lstrip("@")
    out = EXPORT_DIR / f"{name}.json"
    photo_dir = EXPORT_DIR / name
    EXPORT_DIR.mkdir(exist_ok=True)
    if photos:
        photo_dir.mkdir(exist_ok=True)
    posts = []
    failed = 0
    try:
        with TelegramClient(str(SESSION), api_id, api_hash, flood_sleep_threshold=FLOOD_WAIT) as client:
            for message in client.iter_messages(name, reverse=True):
                post = {
                    "id": message.id,
                    "date": message.date.isoformat(),
                    "text": message.message or "",
                    "links": post_links(message),
                    # Posts sent together as an album share it
                    "album": message.grouped_id,
                    "media": "photo" if message.photo else "document" if message.document else None,
                    "file": message.file.name if message.document and message.file else None,
                    "views": message.views,
                }
                if photos and message.photo:
                    post["photo"], error = save_photo(message, photo_dir)
                    if error:
                        post["photo_error"] = error
                        failed += 1
                        print(f"  post {message.id}: photo not downloaded ({error})", flush=True)
                posts.append(post)
                if len(posts) % 200 == 0:
                    print(f"  {len(posts)} posts...", flush=True)
    finally:
        # Whatever was read, even if the run stopped half way
        out.write_text(json.dumps(posts, ensure_ascii=False, indent=1))
    return out, len(posts), failed


# Posts with match results (their photos show the games' timers): "Результаты матча ...", the 2024 stream recaps
# ("Первая игра была между ..."), and other results and winners posts.
RESULT_POSTS = r"результат(ы)? матч|игра была между|итоги|побед"
# What text recognition reads (a post's "photo" can also come down as a video)
PICTURES = (".jpg", ".jpeg", ".png", ".webp")


def exported_posts(channel: str) -> list[dict]:
    return json.loads((EXPORT_DIR / f"{channel.lstrip('@')}.json").read_text())


def download_photos(
    channel: str, api_id: int, api_hash: str, pattern: str = RESULT_POSTS, since: str = "", until: str = "9999"
) -> tuple[int, int, int]:
    """Downloads the photos of the exported posts whose text matches pattern and whose date (YYYY-MM-DD) is between
    since and until (see export_channel; photos already saved are kept); returns (posts wanted, photos saved now or
    before, failed)."""
    from telethon.sync import TelegramClient

    name = channel.lstrip("@")
    photo_dir = EXPORT_DIR / name
    photo_dir.mkdir(parents=True, exist_ok=True)
    ids = [
        p["id"]
        for p in exported_posts(name)
        if p["media"] == "photo" and re.search(pattern, p["text"], re.I) and since <= p["date"][:10] <= until
    ]
    saved = failed = 0
    with TelegramClient(str(SESSION), api_id, api_hash, flood_sleep_threshold=FLOOD_WAIT) as client:
        for start in range(0, len(ids), 100):
            for message in client.get_messages(name, ids=ids[start : start + 100]):
                if not message or not message.photo:
                    continue
                path, error = save_photo(message, photo_dir)
                if error:
                    failed += 1
                    print(f"  post {message.id}: photo not downloaded ({error})", flush=True)
                elif path:
                    saved += 1
            print(f"  {min(start + 100, len(ids))} of {len(ids)} posts...", flush=True)
    return len(ids), saved, failed


def recognize_photos(channel: str) -> tuple[Path, int]:
    """Reads the text on every downloaded photo with macOS's own text recognition (Vision, through ocrmac: offline,
    Russian and English) into telegram/<channel>-ocr.json: {post id: [[text, confidence, [x, y, width, height]]]},
    boxes as fractions of the picture with y from the bottom. Photos read before are kept, not read again."""
    from ocrmac import ocrmac

    name = channel.lstrip("@")
    out = EXPORT_DIR / f"{name}-ocr.json"
    done = json.loads(out.read_text()) if out.exists() else {}
    photos = sorted(
        (p for p in (EXPORT_DIR / name).glob("*.*") if p.suffix.lower() in PICTURES),
        key=lambda p: int(p.stem) if p.stem.isdigit() else 0,
    )
    try:
        for n, photo in enumerate(p for p in photos if p.stem not in done):
            try:
                lines = ocrmac.OCR(str(photo), language_preference=["ru-RU", "en-US"]).recognize()
            except Exception as e:  # noqa: BLE001 - a broken file: say so and read the rest
                print(f"  {photo.name}: not read ({e})", flush=True)
                continue
            done[photo.stem] = [[text, round(conf, 3), [round(v, 4) for v in box]] for text, conf, box in lines]
            if (n + 1) % 50 == 0:
                print(f"  {n + 1} photos read...", flush=True)
    finally:
        out.write_text(json.dumps(done, ensure_ascii=False))
    return out, len(done)
