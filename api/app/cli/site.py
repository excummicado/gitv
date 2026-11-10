"""Commands for the site itself: user roles, the stream, news translations and articles."""

import os
from datetime import UTC

from sqlmodel import Session, select

from ..database import engine
from ..models import (
    Role,
    StreamMatch,
    StreamStatus,
    User,
)


def set_role(nickname: str, role: Role) -> None:
    with Session(engine) as session:
        user = session.exec(select(User).where(User.nickname == nickname)).first()
        if user is None:
            raise SystemExit(f"No user with nickname {nickname!r}.")
        user.role = role
        session.add(user)
        session.commit()
    print(f"{nickname} is now {role.value}. They need to sign in again for it to take effect.")


def poll_stream() -> None:
    """Reads the streams' Telegram channels and Twitch status once (services/stream.py)."""
    from ..services.stream import poll_stream as run

    with Session(engine) as session:
        errors = run(session)
        latest = session.exec(select(StreamMatch).order_by(StreamMatch.announced_at.desc()).limit(6)).all()
        for m in reversed(latest):
            state = (
                f"won by {m.winner_name}"
                if m.winner_name
                else "finished"
                if m.finished_at
                else "on air"
                if m.live_at
                else "announced"
            )
            print(
                f"{m.announced_at:%Y-%m-%d %H:%M} {m.tournament_title}: {m.player1_name} vs {m.player2_name}, {state}"
            )
        statuses = session.exec(select(StreamStatus)).all()
        for status in statuses:
            print(f"Twitch {status.channel}: {'live' if status.live else 'offline'}")
        if not statuses:
            print("Twitch: no keys set (TWITCH_CLIENT_ID)")
    for e in errors:
        print(e)


def set_news_translation(news_id: int, path: str, title: str | None) -> None:
    """Attaches a translated .docx to a news post, as its page's upload does (routers/news.py)."""
    from ..models import NewsPost
    from ..services.news import DocumentError, delete_pictures, docx_to_html, language, unused_pictures

    with Session(engine) as session, open(path, "rb") as doc:
        post = session.get(NewsPost, news_id)
        if post is None:
            raise SystemExit(f"No news {news_id}.")
        try:
            found, body, pictures = docx_to_html(doc)
        except DocumentError as e:
            raise SystemExit(str(e)) from e
        old = unused_pictures(post.body_html_tr or "", post.body_html, body)
        post.lang = language(post.title + " " + post.body_html)
        post.title_tr, post.body_html_tr = title or found or post.title, body
        session.add(post)
        session.commit()
        delete_pictures(old)
        print(f"News {news_id}: translation «{post.title_tr}», {len(pictures)} pictures.")


def import_article(path: str, nickname: str, title: str | None, author: str | None) -> None:
    """Imports a .docx as a draft article under a member's name (routers/articles.py): it shows once an admin
    approves it on its page."""
    from datetime import datetime

    from ..models import NewsPost, User
    from ..services.news import DocumentError, docx_to_html

    with Session(engine) as session, open(path, "rb") as doc:
        user = session.exec(select(User).where(User.nickname == nickname)).first()
        if user is None:
            raise SystemExit(f"No member {nickname}.")
        try:
            found, body, pictures = docx_to_html(doc)
        except DocumentError as e:
            raise SystemExit(str(e)) from e
        post = NewsPost(
            title=title or found,
            body_html=body,
            source=os.path.basename(path),
            author_name=author,
            created_by=user.id,
            created_at=datetime.now(UTC),
        )
        session.add(post)
        session.commit()
        print(f"Draft article {post.id}: «{post.title}», {len(pictures)} pictures; /articles/{post.id}")
