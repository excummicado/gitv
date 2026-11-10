"""News posts from documents: a Word file (.docx) or a Google document shared by link ("anyone with the link can view"),
which Google exports as .docx. The document becomes HTML with mammoth (headings, paragraphs, lists, bold, italics,
links, tables, pictures; headings of every level, so its chapters, with anchors, Word's own table of contents left out
since the page draws one) and is then cleaned with nh3 so only those tags remain: no scripts, styles or event
handlers, links only to http(s) and mail. Pictures are saved as files under media/news (checked by their bytes) and
removed with their post. The title is the given one, else the document's first heading or line.
"""

import html
import re
import shutil
import tempfile
import uuid
import zipfile
from typing import BinaryIO

import httpx
import mammoth
import nh3

from .media import MEDIA_DIR, image_type

# The server has little memory and disk: mammoth unpacks a document in memory and its pictures are kept as files
MAX_BYTES = 20 * 1024 * 1024
MAX_UNPACKED = 200 * 1024 * 1024  # all of the archive's entries, unpacked
MAX_ENTRIES = 2000
MAX_PICTURE = 10 * 1024 * 1024
MAX_PICTURES = 100
TOO_BIG = "The document must be 20 MB or smaller."
GOOGLE_DOC = re.compile(r"https://docs\.google\.com/document/d/([A-Za-z0-9_-]{20,})")
GOOGLE_EXPORT = "https://docs.google.com/document/d/{id}/export?format=docx"
TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "br", "strong", "b", "em", "i", "u", "s", "sub", "sup", "ul", "ol", "li",
    "a", "img", "table", "thead", "tbody", "tr", "th", "td", "blockquote", "hr",
}  # fmt: skip
ATTRIBUTES = {"a": {"href"}, "img": {"src", "alt"}, "td": {"colspan", "rowspan"}, "th": {"colspan", "rowspan"}}
# A post's pictures are files under media/news, served at /api/v1/media/news/<name>
PICTURES = "news"
PICTURE = re.compile(r"/api/v1/media/news/[0-9a-f]{32}\.(png|jpg|gif|webp)")


class DocumentError(ValueError):
    """The document can't be read: not a .docx, too big, or a Google document that isn't shared."""


def keep(tag: str, attribute: str, value: str) -> str | None:
    """nh3's attribute filter: links to the web or mail only, pictures only the post's own files."""
    if tag == "a" and attribute == "href":
        return value if re.match(r"(?i)(https?:|mailto:)", value) else None
    if tag == "img" and attribute == "src":
        return value if PICTURE.fullmatch(value) else None
    return value


def clean(body: str) -> str:
    return nh3.clean(
        body,
        tags=TAGS,
        attributes=ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
        attribute_filter=keep,
        link_rel="noopener noreferrer nofollow",
    )


def picture_files(body: str) -> list[str]:
    """The post's pictures, as paths under MEDIA_DIR (to remove them with it)."""
    return [m[0].removeprefix("/api/v1/media/") for m in PICTURE.finditer(body)]


def delete_pictures(paths: list[str]) -> None:
    for relative in paths:
        (MEDIA_DIR / relative).unlink(missing_ok=True)


def unused_pictures(old: str, *kept: str) -> list[str]:
    """The pictures of an old text that none of the kept ones show (a translation may reuse the original's)."""
    used = {path for body in kept for path in picture_files(body)}
    return [path for path in dict.fromkeys(picture_files(old)) if path not in used]


HEADING = re.compile(r"<(h[1-6])>(.*?)</\1>", re.S)
# Word's own table of contents: a heading like these, up to the next heading of its level or higher
CONTENTS = re.compile(r"(?i)^\s*(contents|table of contents|содержание|оглавление)\s*$")


def heading_text(inner: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", inner)).strip()


def drop_contents(body: str) -> str:
    """The document without Word's table of contents (the page shows its own, from the chapters)."""
    for m in HEADING.finditer(body):
        if CONTENTS.match(heading_text(m[2])):
            level = int(m[1][1])
            end = next((n.start() for n in HEADING.finditer(body, m.end()) if int(n[1][1]) <= level), len(body))
            if end == len(body):  # nothing after it but the list: keep the document as it is
                return body
            return body[: m.start()] + body[end:]
    return body


def chapters(body: str) -> str:
    """Each heading gets an anchor ("ch-1", "ch-2", …) for the chapter list and links to it."""
    count = iter(range(1, 10_000))
    return HEADING.sub(lambda m: f'<{m[1]} id="ch-{next(count)}">{m[2]}</{m[1]}>', body)


def brief(body: str, limit: int = 400) -> str:
    """The start of a cleaned body as text, for a list's excerpt: a list needn't carry whole articles. Still escaped,
    as body_html is shown as HTML."""
    text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", body)).split())
    return html.escape(text[:limit], quote=False)


def check_archive(doc: BinaryIO) -> None:
    """Refuse a .docx whose zip unpacks to far more than it weighs (or into too many entries) before mammoth unpacks
    it in memory. The sizes are the ones the archive states; a picture is read only up to MAX_PICTURE anyway."""
    try:
        with zipfile.ZipFile(doc) as z:
            entries = z.infolist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, ValueError) as e:
        raise DocumentError("Couldn't read the document.") from e
    finally:
        doc.seek(0)
    if len(entries) > MAX_ENTRIES or sum(e.file_size for e in entries) > MAX_UNPACKED:
        raise DocumentError("The document unpacks to too much. Make it smaller, or with smaller pictures.")


def docx_to_html(doc: BinaryIO) -> tuple[str, str, list[str]]:
    """(title found in it, cleaned HTML body, its pictures' paths under MEDIA_DIR) of a .docx file. Each picture
    is checked by its bytes (PNG, JPEG, GIF or WebP; others, like Word's vector drawings, are left out) and saved as a
    file; nothing is left behind if the document can't be read."""
    doc.seek(0, 2)
    if doc.tell() > MAX_BYTES:
        raise DocumentError(TOO_BIG)
    doc.seek(0)
    if doc.read(2) != b"PK":
        raise DocumentError("That isn't a Word document (.docx).")
    doc.seek(0)
    check_archive(doc)
    saved: list[str] = []
    seen = 0

    def save_picture(image) -> dict:
        nonlocal seen
        seen += 1
        if seen > MAX_PICTURES:
            return {}
        with image.open() as data:
            content = data.read(MAX_PICTURE + 1)
        if len(content) > MAX_PICTURE:
            return {}
        ext = image_type(content[:16]) or ("gif" if content[:6] in (b"GIF87a", b"GIF89a") else None)
        if ext is None:
            return {}
        relative = f"{PICTURES}/{uuid.uuid4().hex}.{ext}"
        (MEDIA_DIR / PICTURES).mkdir(parents=True, exist_ok=True)
        (MEDIA_DIR / relative).write_bytes(content)
        saved.append(relative)
        return {"src": f"/api/v1/media/{relative}"}

    try:
        # mammoth reads the file's name: a big upload, kept by the server in a temporary file, has a number there
        # instead, so it's given a named copy (on disk, not in memory)
        with tempfile.NamedTemporaryFile(suffix=".docx") as named:
            shutil.copyfileobj(doc, named)
            named.seek(0)
            result = mammoth.convert_to_html(named, convert_image=mammoth.images.img_element(save_picture))
    except Exception as e:  # noqa: BLE001 - a broken or foreign file: say so
        delete_pictures(saved)
        raise DocumentError("Couldn't read the document.") from e
    body = clean(result.value)
    body = re.sub(r"<img(?![^>]*\bsrc=)[^>]*>", "", body)  # a picture that wasn't kept
    first = re.search(r"<(h[1-6]|p)>(.*?)</\1>", body, re.S)
    title = html.unescape(re.sub(r"<[^>]+>", "", first[2])).strip() if first else ""
    if first and title:
        body = body[: first.start()] + body[first.end() :]  # the title isn't repeated in the body
    body = chapters(drop_contents(body))
    used = set(picture_files(body))
    delete_pictures([p for p in saved if p not in used])
    return title[:200], body.strip(), [p for p in saved if p in used]


def edited_html(body: str) -> str:
    """A body edited on the article's page, cleaned like an imported one: the same tags, links and own pictures only,
    and its headings given anchors again."""
    body = clean(body)
    body = re.sub(r"<img(?![^>]*\bsrc=)[^>]*>", "", body)
    body = re.sub(r"<(p|h[1-6]|li|blockquote)>(\s|&nbsp;|<br\s*/?>)*</\1>", "", body)  # emptied by the editing
    return chapters(body).strip()


def language(body: str) -> str:
    """ "ru" when most of the letters are Cyrillic, else "en"."""
    text = re.sub(r"<[^>]+>", " ", body)
    return "ru" if len(re.findall(r"[А-Яа-яЁё]", text)) > len(re.findall(r"[A-Za-z]", text)) else "en"


def fetch_google_doc(url: str) -> BinaryIO:
    """A Google document shared by link, exported as .docx, in a temporary file (up to MAX_BYTES)."""
    m = GOOGLE_DOC.match(url.strip())
    if not m:
        raise DocumentError("That isn't a Google document link (docs.google.com/document/d/…).")
    out = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    try:
        with httpx.stream("GET", GOOGLE_EXPORT.format(id=m[1]), follow_redirects=True, timeout=60) as r:
            if r.status_code != 200:
                raise DocumentError(
                    'The document isn\'t open to "anyone with the link". Share it that way, or upload it as .docx.'
                )
            for chunk in r.iter_bytes():
                out.write(chunk)
                if out.tell() > MAX_BYTES:
                    raise DocumentError(TOO_BIG)
    except httpx.HTTPError as e:
        raise DocumentError("Couldn't reach Google Docs. Try again.") from e
    out.seek(0)
    if out.read(2) != b"PK":
        raise DocumentError(
            'The document isn\'t open to "anyone with the link". Share it that way, or upload it as .docx.'
        )
    out.seek(0)
    return out
