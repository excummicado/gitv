"""Uploaded images (news pictures): checked by their bytes, stored under api/media, served at /api/v1/media."""

from pathlib import Path

MEDIA_DIR = Path(__file__).resolve().parents[2] / "media"

# Only raster formats, recognised by their first bytes; the file name and the browser's content type
# aren't trusted (an SVG or HTML file renamed to .png is refused).
SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpg",
}


def image_type(head: bytes) -> str | None:
    for signature, ext in SIGNATURES.items():
        if head.startswith(signature):
            return ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None
