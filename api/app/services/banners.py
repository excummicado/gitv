"""Banners chosen by hand for an organizer's tournaments, used instead of the tournament's own image.

Some organizers upload tiny banners to the site; their tournaments get a sharper one from the frontend's
public/banners folder. Keyed by the organizer's site user id (tournamentinfo.organizer_id).
"""

ORGANIZER_BANNERS = {
    "689310f298475bdb81632e61": "/banners/astro-liber.svg",  # Astro Liber (HotH / Abyss Weekend), vectorized
}


def banner_for(organizer_id: str | None, image: str | None) -> str | None:
    """The organizer's banner if they have one, else the tournament's own image."""
    return ORGANIZER_BANNERS.get(organizer_id or "", image)
