"""Short news for the home page's news column: anyone reads them; writers, event organizers and admins write one
there (plain text, up to MAX_TEXT characters); its author or an admin edits or removes it. Tournament registrations
announced in Abyss Cup's and House of the Hearth's channels come in by themselves (services/registrations.py).
Articles are routers/articles.py."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import select

from ..database import MAX_ROW_ID, RowId, SessionDep
from ..dependencies import get_current_news_writer
from ..models import NewsItem, User
from ..rate_limit import rate_limit

router = APIRouter(prefix="/news", tags=["news"])

MAX_TEXT = 500


class NewsIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)


class NewsItemOut(BaseModel):
    id: int
    text: str
    author: str  # the writer's nickname, or the channel's name for one added by itself
    author_id: str | None  # None for one added by itself
    source_url: str | None  # the channel's post it came from
    created_at: datetime


def out(session: SessionDep, rows: list[NewsItem]) -> list[NewsItemOut]:
    ids = {r.created_by for r in rows if r.created_by}
    authors = {u.id: u for u in session.exec(select(User).where(User.id.in_(ids)))} if ids else {}
    return [
        NewsItemOut(
            id=r.id,
            text=r.text,
            author=authors[r.created_by].nickname if r.created_by in authors else (r.source or ""),
            author_id=str(r.created_by) if r.created_by else None,
            source_url=r.source_url,
            created_at=r.created_at.replace(tzinfo=UTC) if r.created_at.tzinfo is None else r.created_at,
        )
        for r in rows
    ]


@router.get("", response_model=list[NewsItemOut])
def list_news(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 5,
    before: Annotated[
        int | None, Query(le=MAX_ROW_ID, description="Only items older than this one (the next page)")
    ] = None,
):
    """The latest news, newest first, without registrations for tournaments that have started."""
    query = (
        select(NewsItem)
        .where(NewsItem.hidden == False)  # noqa: E712
        .where((NewsItem.ends_at == None) | (NewsItem.ends_at > datetime.now(UTC)))  # noqa: E711
        .order_by(NewsItem.created_at.desc(), NewsItem.id.desc())
    )
    if before is not None:
        last = session.get(NewsItem, before)
        if last is not None:
            query = query.where(
                (NewsItem.created_at < last.created_at)
                | ((NewsItem.created_at == last.created_at) & (NewsItem.id < before))
            )
    query = query.limit(limit)
    return out(session, list(session.exec(query)))


@router.post(
    "",
    response_model=NewsItemOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("news-item", 30, 3600, per="user"))],
)
def add_news(data: NewsIn, session: SessionDep, user: Annotated[User, Depends(get_current_news_writer)]):
    text = data.text.strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Write the news first.")
    row = NewsItem(text=text, created_by=user.id, created_at=datetime.now(UTC))
    session.add(row)
    session.commit()
    session.refresh(row)
    return out(session, [row])[0]


def own_item(session: SessionDep, item_id: int, user: User, action: str) -> NewsItem:
    """The item, when this user may change it: its author, or an admin (a channel's item has no author)."""
    row = session.get(NewsItem, item_id)
    if row is None or row.hidden:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such news.")
    if row.created_by != user.id and not user.role.is_staff:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=f"Only its author or an admin can {action} it."
        )
    return row


@router.patch("/{item_id}", response_model=NewsItemOut)
def edit_news(
    item_id: RowId, data: NewsIn, session: SessionDep, user: Annotated[User, Depends(get_current_news_writer)]
):
    """Its author or an admin changes its text; it keeps its place and date."""
    row = own_item(session, item_id, user, "edit")
    text = data.text.strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Write the news first.")
    row.text = text
    session.add(row)
    session.commit()
    session.refresh(row)
    return out(session, [row])[0]


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_news(item_id: RowId, session: SessionDep, user: Annotated[User, Depends(get_current_news_writer)]):
    """Its author or an admin removes it."""
    row = own_item(session, item_id, user, "remove")
    if row.source_url:
        row.hidden = True  # kept, so the channel's post doesn't bring it back
        session.add(row)
    else:
        session.delete(row)
    session.commit()
