"""Uploaded images (player avatars): checked by their bytes, stored under api/media, served at /api/v1/media."""

import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

MEDIA_DIR = Path(__file__).resolve().parents[2] / "media"
MAX_AVATAR_BYTES = 2 * 1024 * 1024

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


async def save_avatar(upload: UploadFile) -> str:
    """Stores the image and returns its path relative to MEDIA_DIR."""
    data = await upload.read(MAX_AVATAR_BYTES + 1)
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="The avatar must be 2 MB or smaller.")
    ext = image_type(data[:16])
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="The avatar must be a PNG, JPEG or WebP image."
        )
    relative = f"avatars/{uuid.uuid4().hex}.{ext}"
    path = MEDIA_DIR / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return relative


def delete_media(relative: str | None) -> None:
    if relative:
        (MEDIA_DIR / relative).unlink(missing_ok=True)


def media_url(relative: str | None) -> str | None:
    return f"/api/v1/media/{relative}" if relative else None
