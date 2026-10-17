"""Request limits for sign-in and for everything members write, so a script can't flood the API.

Counts live in memory (per API process) over a sliding window; a restart forgets them, which is fine for
this purpose. Behind a reverse proxy, set TRUST_FORWARDED_FOR so clients are told apart by the
X-Forwarded-For address instead of the proxy's.
"""

import math
import threading
import time
from collections import defaultdict, deque
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request, status

from .config import settings
from .dependencies import get_current_active_user
from .models import User


class RateLimiter:
    def __init__(self):
        self._hits: dict[tuple, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: tuple, times: int, seconds: int, now: float | None = None) -> float:
        """Counts a request; returns 0 if it's allowed, else the seconds until the next one is."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - seconds:
                hits.popleft()
            if len(hits) >= times:
                return hits[0] + seconds - now
            hits.append(now)
            return 0.0

    def clear(self):
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    if settings.trust_forwarded_for and (forwarded := request.headers.get("x-forwarded-for")):
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def too_many(wait: float) -> HTTPException:
    minutes = max(1, math.ceil(wait / 60))
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Too many requests. Try again in {minutes} min.",
        headers={"Retry-After": str(math.ceil(wait))},
    )


def rate_limit(name: str, times: int, seconds: int, per: Literal["ip", "user"] = "ip"):
    """A dependency allowing `times` requests per `seconds` for each client address or signed-in member."""
    if per == "user":

        async def by_user(user: Annotated[User, Depends(get_current_active_user)]):
            if wait := limiter.hit((name, str(user.id)), times, seconds):
                raise too_many(wait)

        return by_user

    async def by_ip(request: Request):
        if wait := limiter.hit((name, client_ip(request)), times, seconds):
            raise too_many(wait)

    return by_ip
