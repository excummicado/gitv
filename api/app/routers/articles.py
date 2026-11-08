"""Articles (/articles; the short news of the home page's column are routers/news.py): anyone reads them; writers,
event organizers and admins add one by importing a Word file (.docx, up to 100 MB) or a Google document link
(services/news.py), and may attach its translation into the other language the same way; whoever imported it or an
admin changes or removes it, with its pictures. Nothing is added automatically.

An article imported by anyone but an admin (or from the command line) is a draft until an admin approves it: only
admins and whoever imported it see it, on the list (with drafts=true) and on its page; approving it publishes it
dated then. Its author or an admin edits it on its page (its text in the browser, or a new version of the document);
an edit by anyone but an admin sends a published article back for approval.

Each article counts its reads: the page reports one when a reader has had it open for READ_SECONDS (count_read).
A browser reports an article once, and the same address counts once per article per READ_WINDOW; the addresses
are only held in memory for that (rate_limit.py), never stored.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlmodel import select

from ..database import RowId, SessionDep
from ..dependencies import get_current_news_writer, get_current_staff, get_optional_user
from ..models import NewsPost, User
from ..rate_limit import client_ip, limiter, rate_limit
from ..security import CSRF_HEADER
from ..services.news import (
    DocumentError,
    brief,
    delete_pictures,
    docx_to_html,
    edited_html,
    fetch_google_doc,
    language,
    picture_files,
    unused_pictures,
)

router = APIRouter(prefix="/articles", tags=["articles"])

READ_SECONDS = 30  # as the page waits before reporting a read (web/app/articles/ArticlesPage.tsx)
READ_WINDOW = 24 * 3600


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
    reads: int  # readers who stayed on it at least READ_SECONDS
    approved: bool  # False: a draft, waiting for an admin


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
            reads=r.reads or 0,
            approved=r.approved_at is not None,
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such article.")
    if row.created_by != user.id and not user.role.is_staff:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only its author or an admin can change it.")
    return row


def can_see(row: NewsPost, user: User | None) -> bool:
    """Anyone sees a published article; a draft only admins and whoever imported it."""
    return row.approved_at is not None or (
        user is not None and (user.role.is_staff or (row.created_by == user.id and user.role.can_write_news))
    )


@router.get("", response_model=list[NewsOut])
def list_news(
    session: SessionDep,
    user: Annotated[User | None, Depends(get_optional_user)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    drafts: bool = False,
):
    """The latest news, newest first. drafts: the drafts this user may see come first (the articles page)."""
    query = select(NewsPost).order_by(NewsPost.created_at.desc())
    published = session.exec(query.where(NewsPost.approved_at.is_not(None)).limit(limit)).all()
    waiting = []
    if drafts and user is not None:
        waiting = [r for r in session.exec(query.where(NewsPost.approved_at.is_(None))) if can_see(r, user)]
    rows = [*waiting, *published]
    # Only the start of each text: the home page and the list show an excerpt, the article's own page loads the rest
    return [
        item.model_copy(
            update={
                "body_html": brief(item.body_html),
                "body_html_tr": brief(item.body_html_tr) if item.body_html_tr is not None else None,
            }
        )
        for item in out(session, list(rows))
    ]


@router.get("/{news_id}", response_model=NewsOut)
def read_news(news_id: RowId, session: SessionDep, user: Annotated[User | None, Depends(get_optional_user)]):
    row = session.get(NewsPost, news_id)
    if row is None or not can_see(row, user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such article.")
    return out(session, [row])[0]


class ReadsOut(BaseModel):
    reads: int


@router.post("/{news_id}/read", response_model=ReadsOut, dependencies=[Depends(rate_limit("article-read", 60, 3600))])
def count_read(news_id: RowId, request: Request, session: SessionDep):
    """A reader has had the article open for READ_SECONDS: one more read, unless this address was counted for it in
    the last READ_WINDOW. Anyone may report it, from the site's own pages (its request header)."""
    if request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing the site's request header.")
    row = session.get(NewsPost, news_id)
    if row is None or row.approved_at is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such article.")
    if not limiter.hit(("article-read", client_ip(request), news_id), 1, READ_WINDOW):
        row.reads = (row.reads or 0) + 1
        session.add(row)
        session.commit()
    return {"reads": row.reads or 0}


@router.post(
    "",
    response_model=NewsOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("news", 20, 3600, per="user"))],
)
def add_news(  # not async: converting a document takes a while, and would stop every other request meanwhile
    session: SessionDep,
    user: Annotated[User, Depends(get_current_news_writer)],
    file: Annotated[UploadFile | None, File(description="A Word document (.docx)")] = None,
    google_url: Annotated[str | None, Form(max_length=300)] = None,
    title: Annotated[str | None, Form(max_length=200)] = None,
    author: Annotated[str | None, Form(max_length=100)] = None,
):
    """Imports a news post from a .docx file or a Google document shared by link (one of the two). The title is the
    given one, else the document's first heading or line; the author is the given one (who wrote the article), else
    whoever imports it. An admin's article is published at once; anyone else's waits as a draft for an admin."""
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
    if user.role.is_staff:
        row.approved_at, row.approved_by = row.created_at, user.id
    session.add(row)
    session.commit()
    session.refresh(row)
    return out(session, [row])[0]


@router.post("/{news_id}/approve", response_model=NewsOut)
def approve_news(news_id: RowId, session: SessionDep, user: Annotated[User, Depends(get_current_staff)]):
    """An admin publishes a draft: it shows to everyone, dated now (the top of the list)."""
    row = session.get(NewsPost, news_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such article.")
    if row.approved_at is None:
        now = datetime.now(UTC)
        row.approved_at, row.approved_by, row.created_at = now, user.id, now
        session.add(row)
        session.commit()
        session.refresh(row)
    return out(session, [row])[0]


@router.delete("/{news_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_news(news_id: RowId, session: SessionDep, user: Annotated[User, Depends(get_current_news_writer)]):
    """Its author or an admin removes a news post, with its pictures (its translation's too)."""
    row = editable(session, news_id, user)
    session.delete(row)
    session.commit()
    delete_pictures(list(dict.fromkeys(picture_files(row.body_html) + picture_files(row.body_html_tr or ""))))


MAX_BODY = 2_000_000  # characters of an edited body's HTML


class NewsEdit(BaseModel):
    """Fields changed on the article's page; those left out stay. A body is HTML, cleaned like an imported one."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    author: str | None = Field(default=None, max_length=100)  # "" goes back to whoever imported it
    body_html: str | None = Field(default=None, max_length=MAX_BODY)
    title_tr: str | None = Field(default=None, min_length=1, max_length=200)
    body_html_tr: str | None = Field(default=None, max_length=MAX_BODY)


def back_to_review(row: NewsPost, user: User) -> None:
    """A published article changed by anyone but an admin waits for an admin's approval again."""
    if not user.role.is_staff:
        row.approved_at = row.approved_by = None


@router.patch("/{news_id}", response_model=NewsOut)
def edit_news(
    news_id: RowId, edit: NewsEdit, session: SessionDep, user: Annotated[User, Depends(get_current_news_writer)]
):
    """Its author or an admin edits the article on its page: title, author shown, text, and its translation's."""
    row = editable(session, news_id, user)
    old = [row.body_html, row.body_html_tr or ""]
    if edit.title is not None:
        row.title = edit.title.strip() or row.title
    if edit.author is not None:
        row.author_name = edit.author.strip() or None
    if edit.body_html is not None:
        body = edited_html(edit.body_html)
        if not body:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The article is empty.")
        row.body_html = body
    if edit.title_tr is not None or edit.body_html_tr is not None:
        if row.body_html_tr is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="It has no translation.")
        if edit.title_tr is not None:
            row.title_tr = edit.title_tr.strip() or row.title_tr
        if edit.body_html_tr is not None:
            row.body_html_tr = edited_html(edit.body_html_tr) or row.body_html_tr
    back_to_review(row, user)
    session.add(row)
    session.commit()
    session.refresh(row)
    delete_pictures([p for o in old for p in unused_pictures(o, row.body_html, row.body_html_tr or "")])
    return out(session, [row])[0]


@router.put(
    "/{news_id}/document",
    response_model=NewsOut,
    dependencies=[Depends(rate_limit("news", 20, 3600, per="user"))],
)
def replace_document(  # not async, as add_news
    news_id: RowId,
    session: SessionDep,
    user: Annotated[User, Depends(get_current_news_writer)],
    file: Annotated[UploadFile | None, File(description="A Word document (.docx)")] = None,
    google_url: Annotated[str | None, Form(max_length=300)] = None,
):
    """Replaces the article's text with a new version of its document (a .docx file or a Google document link); the
    title stays unless the document's first heading or line differs from it."""
    row = editable(session, news_id, user)
    source, found, body, pictures = read_document(file, google_url)
    if not body:
        delete_pictures(pictures)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The document is empty.")
    old = row.body_html
    row.title, row.body_html, row.source = found or row.title, body, source
    back_to_review(row, user)
    session.add(row)
    session.commit()
    session.refresh(row)
    delete_pictures(unused_pictures(old, row.body_html, row.body_html_tr or ""))
    return out(session, [row])[0]


@router.put(
    "/{news_id}/translation",
    response_model=NewsOut,
    dependencies=[Depends(rate_limit("news", 20, 3600, per="user"))],
)
def set_translation(  # not async, as add_news
    news_id: RowId,
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
def delete_translation(news_id: RowId, session: SessionDep, user: Annotated[User, Depends(get_current_news_writer)]):
    row = editable(session, news_id, user)
    old = unused_pictures(row.body_html_tr or "", row.body_html)
    row.lang = row.title_tr = row.body_html_tr = None
    session.add(row)
    session.commit()
    delete_pictures(old)
