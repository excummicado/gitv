"""News on the home page: anyone reads them; writers, event organizers and admins add one by importing a Word file
(.docx, up to 100 MB) or a Google document link (services/news.py), and may attach its translation into the other
language the same way; whoever imported it or an admin changes or removes it, with its pictures. Nothing is added to the
news automatically.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlmodel import select

from ..database import SessionDep
from ..dependencies import get_current_news_writer
from ..models import NewsPost, User
from ..rate_limit import rate_limit
from ..services.news import (
    DocumentError,
    delete_pictures,
    docx_to_html,
    fetch_google_doc,
    language,
    picture_files,
    unused_pictures,
)

router = APIRouter(prefix="/news", tags=["news"])


class NewsOut(BaseModel):
    id: int
    title: str
    body_html: str  # cleaned: safe to show as HTML
    source: str
    author: str  # as given by hand when importing, else the nickname of whoever imported it
    imported_by: str  # nickname
    created_at: datetime
    # A translation into the other language, uploaded by hand
    lang: str | None  # the post's: "ru" or "en"
    title_tr: str | None
    body_html_tr: str | None  # cleaned like body_html; None without a translation


def out(session: SessionDep, rows: list[NewsPost]) -> list[NewsOut]:
    authors = {u.id: u.nickname for u in session.exec(select(User).where(User.id.in_({r.created_by for r in rows})))}
    return [
        NewsOut(
            id=r.id,
            title=r.title,
            body_html=r.body_html,
            source=r.source,
            author=r.author_name or authors.get(r.created_by, "deleted member"),
            imported_by=authors.get(r.created_by, "deleted member"),
            created_at=r.created_at.replace(tzinfo=UTC) if r.created_at.tzinfo is None else r.created_at,
            lang=r.lang,
            title_tr=r.title_tr,
            body_html_tr=r.body_html_tr,
        )
        for r in rows
    ]


def read_document(file: UploadFile | None, google_url: str | None) -> tuple[str, str, str, list[str]]:
    """(source, title found in it, cleaned body, its pictures) of an uploaded .docx or a Google document link."""
    if (file is None) == (not google_url):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Upload a .docx file or give a Google Docs link."
        )
    try:
        if file is not None:
            # Starlette keeps a big upload on disk: it's read from there, not into memory
            doc, source = file.file, file.filename or "document.docx"
        else:
            doc, source = fetch_google_doc(google_url), google_url.strip()
        return source, *docx_to_html(doc)
    except DocumentError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)) from e


def editable(session: SessionDep, news_id: int, user: User) -> NewsPost:
    """The post, when this user may change it: whoever imported it, or an admin."""
    row = session.get(NewsPost, news_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such news.")
    if row.created_by != user.id and not user.role.is_staff:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only its author or an admin can change it.")
    return row


@router.get("", response_model=list[NewsOut])
def list_news(session: SessionDep, limit: Annotated[int, Query(ge=1, le=50)] = 10):
    """The latest news, newest first."""
    rows = session.exec(select(NewsPost).order_by(NewsPost.created_at.desc()).limit(limit)).all()
    return out(session, list(rows))


@router.get("/{news_id}", response_model=NewsOut)
def read_news(news_id: int, session: SessionDep):
    row = session.get(NewsPost, news_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such news.")
    return out(session, [row])[0]


@router.post(
    "",
    response_model=NewsOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("news", 20, 3600, per="user"))],
)
async def add_news(
    session: SessionDep,
    user: Annotated[User, Depends(get_current_news_writer)],
    file: Annotated[UploadFile | None, File(description="A Word document (.docx)")] = None,
    google_url: Annotated[str | None, Form(max_length=300)] = None,
    title: Annotated[str | None, Form(max_length=200)] = None,
    author: Annotated[str | None, Form(max_length=100)] = None,
):
    """Imports a news post from a .docx file or a Google document shared by link (one of the two). The title is the
    given one, else the document's first heading or line; the author is the given one (who wrote the article), else
    whoever imports it."""
    source, found, body, pictures = read_document(file, google_url)
    heading = (title or "").strip() or found
    if not heading or (not body and not found):
        delete_pictures(pictures)
        detail = "Give the news a title." if not heading else "The document is empty."
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)
    row = NewsPost(
        title=heading,
        body_html=body,
        source=source,
        author_name=(author or "").strip() or None,
        created_by=user.id,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return out(session, [row])[0]


@router.delete("/{news_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_news(news_id: int, session: SessionDep, user: Annotated[User, Depends(get_current_news_writer)]):
    """Its author or an admin removes a news post, with its pictures (its translation's too)."""
    row = editable(session, news_id, user)
    session.delete(row)
    session.commit()
    delete_pictures(list(dict.fromkeys(picture_files(row.body_html) + picture_files(row.body_html_tr or ""))))


@router.put(
    "/{news_id}/translation",
    response_model=NewsOut,
    dependencies=[Depends(rate_limit("news", 20, 3600, per="user"))],
)
async def set_translation(
    news_id: int,
    session: SessionDep,
    user: Annotated[User, Depends(get_current_news_writer)],
    file: Annotated[UploadFile | None, File(description="The translated document (.docx)")] = None,
    google_url: Annotated[str | None, Form(max_length=300)] = None,
    title: Annotated[str | None, Form(max_length=200)] = None,
):
    """Attaches (or replaces) the post's translation into the other language, from a .docx file or a Google document
    link. The title is the given one, else the document's first heading or line. The post's own language is told from
    its text; the translation has to be in the other one."""
    row = editable(session, news_id, user)
    _, found, body, pictures = read_document(file, google_url)
    lang = language(row.title + " " + row.body_html)
    if language(found + " " + body) == lang:
        delete_pictures(pictures)
        other = "Russian" if lang == "en" else "English"
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"The translation should be in {other}."
        )
    old = unused_pictures(row.body_html_tr or "", row.body_html, body)
    row.lang, row.title_tr, row.body_html_tr = lang, (title or "").strip() or found or row.title, body
    session.add(row)
    session.commit()
    session.refresh(row)
    delete_pictures(old)
    return out(session, [row])[0]


@router.delete("/{news_id}/translation", status_code=status.HTTP_204_NO_CONTENT)
def delete_translation(news_id: int, session: SessionDep, user: Annotated[User, Depends(get_current_news_writer)]):
    row = editable(session, news_id, user)
    old = unused_pictures(row.body_html_tr or "", row.body_html)
    row.lang = row.title_tr = row.body_html_tr = None
    session.add(row)
    session.commit()
    delete_pictures(old)
