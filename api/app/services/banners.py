"""Banners chosen by hand, used instead of the tournament's own image.

Some organizers upload tiny banners to the site; their tournaments get a sharper one from the frontend's
public/banners folder. Keyed by the organizer's site user id (tournamentinfo.organizer_id), or by the start of
the title for a series whose organizer also runs other tournaments.
"""

ORGANIZER_BANNERS = {
    "689310f298475bdb81632e61": "/banners/astro-liber.svg",  # Astro Liber (HotH / Abyss Weekend), vectorized
}

SERIES_BANNERS = {
    "abyss fast soup": "/banners/fast-soup.svg",  # Xeity's weekly cup (the beige edition), vectorized
    "new gen all-star": "/banners/new-gen-all-star.jpg",  # Abyss New Gen's; says All-Star, so not their other events
}


def banner_for(organizer_id: str | None, title: str | None, image: str | None) -> str | None:
    """The series' or organizer's banner if there is one, else the tournament's own image."""
    name = (title or "").casefold()
    for prefix, banner in SERIES_BANNERS.items():
        if name.startswith(prefix):
            return banner
    return ORGANIZER_BANNERS.get(organizer_id or "", image)
