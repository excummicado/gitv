"""Short news for the home page's news column: anyone reads them; writers, event organizers and admins write one
there (plain text, up to MAX_TEXT characters); its author or an admin removes it. Articles are routers/articles.py."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import select

from ..database import SessionDep
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
    author: str  # the writer's nickname
    author_id: str
    created_at: datetime


def out(session: SessionDep, rows: list[NewsItem]) -> list[NewsItemOut]:
    authors = {u.id: u for u in session.exec(select(User).where(User.id.in_({r.created_by for r in rows})))}
    return [
        NewsItemOut(
            id=r.id,
            text=r.text,
            author=authors[r.created_by].nickname if r.created_by in authors else "",
            author_id=str(r.created_by),
            created_at=r.created_at.replace(tzinfo=UTC) if r.created_at.tzinfo is None else r.created_at,
        )
        for r in rows
    ]


@router.get("", response_model=list[NewsItemOut])
def list_news(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 5,
    before: Annotated[int | None, Query(description="Only items older than this one (the next page)")] = None,
):
    """The latest news, newest first."""
    query = select(NewsItem).order_by(NewsItem.created_at.desc(), NewsItem.id.desc()).limit(limit)
    if before is not None:
        query = query.where(NewsItem.id < before)
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


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_news(item_id: int, session: SessionDep, user: Annotated[User, Depends(get_current_news_writer)]):
    """Its author or an admin removes it."""
    row = session.get(NewsItem, item_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such news.")
    if row.created_by != user.id and not user.role.is_staff:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only its author or an admin can remove it.")
    session.delete(row)
    session.commit()
