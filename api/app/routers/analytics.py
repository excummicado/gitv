"""Page view counting (public, rate limited) and the analytics summary (admins)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field

from ..database import SessionDep
from ..dependencies import get_current_staff
from ..models import User
from ..rate_limit import client_ip, rate_limit
from ..services.analytics import record_view, should_count, summary

router = APIRouter(tags=["analytics"])


class PageView(BaseModel):
    path: str = Field(max_length=500)
    referrer: str | None = Field(default=None, max_length=500)


@router.post(
    "/analytics/view", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(rate_limit("analytics", 240, 600))]
)
def count_view(data: PageView, request: Request, session: SessionDep):
    """Counts a page view of the site. Nothing is stored for bots or for browsers asking not to be tracked."""
    agent = request.headers.get("user-agent")
    if should_count(agent, request.headers.get("dnt"), request.headers.get("sec-gpc")):
        record_view(session, data.path, client_ip(request), agent or "", data.referrer, request.headers.get("host"))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class DayCount(BaseModel):
    day: date
    views: int
    visitors: int


class PageCount(BaseModel):
    path: str
    views: int


class ReferrerCount(BaseModel):
    host: str
    visits: int


class Analytics(BaseModel):
    days: list[DayCount]  # oldest first
    views: int
    visitors: int  # sum of daily visitors (the same person on two days counts twice)
    today: DayCount
    active_now: int  # visitors seen in the last few minutes
    top_pages: list[PageCount]
    top_sections: list[PageCount]  # pages with ids grouped, e.g. /player/:id
    top_referrers: list[ReferrerCount]


@router.get("/admin/analytics", response_model=Analytics)
def read_analytics(
    session: SessionDep, _: Annotated[User, Depends(get_current_staff)], days: Annotated[int, Query(ge=1, le=90)] = 30
):
    return summary(session, days)
