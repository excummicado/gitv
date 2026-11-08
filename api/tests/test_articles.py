import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.database import get_session
from app.main import app
from app.models import Role, User
from app.rate_limit import limiter
from app.security import create_access_token
from app.services.news import docx_to_html

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
    b"\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def docx(paragraphs: list[str], links: dict[str, str] | None = None, images: dict[str, bytes] | None = None) -> bytes:
    """A minimal Word document: paragraphs of WordprocessingML (a "Heading1" style for headings), hyperlinks and
    pictures (relationship id -> PNG bytes, placed with picture())."""
    rels = "".join(
        f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        f'hyperlink" Target="{url}" TargetMode="External"/>'
        for rid, url in (links or {}).items()
    )
    rels += "".join(
        f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        f'Target="media/{rid}.png"/>'
        for rid in images or {}
    )
    body = "".join(paragraphs)
    files = {
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
        'content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships'
        '+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" '
        'ContentType="image/png"/><Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
        'relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/_rels/document.xml.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.'
        f'org/package/2006/relationships">{rels}</Relationships>',
        "word/document.xml": f'<?xml version="1.0"?><w:document {W} {R}><w:body>{body}</w:body></w:document>',
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
        for rid, data in (images or {}).items():
            z.writestr(f"word/media/{rid}.png", data)
    return out.getvalue()


def p(text: str, style: str | None = None) -> str:
    props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{props}<w:r><w:t>{text}</w:t></w:r></w:p>"


def picture(rid: str) -> str:
    ns = (
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
    )
    return (
        f'<w:p><w:r><w:drawing><wp:inline {ns}><wp:docPr id="1" name="pic"/><a:graphic><a:graphicData '
        f'uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:blipFill><a:blip '
        f'r:embed="{rid}"/></pic:blipFill></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
    )


def link(text: str, rid: str) -> str:
    return f'<w:p><w:hyperlink r:id="{rid}"><w:r><w:t>{text}</w:t></w:r></w:hyperlink></w:p>'


def test_a_document_becomes_clean_html():
    data = docx(
        [p("Итоги недели", "Heading1"), p("Первый абзац &lt;script&gt;alert(1)&lt;/script&gt;"), link("сайт", "l1"),
         link("плохая", "l2")],
        {"l1": "https://example.com/", "l2": "javascript:alert(1)"},
    )  # fmt: skip
    title, body, pictures = docx_to_html(io.BytesIO(data))
    assert pictures == []
    assert title == "Итоги недели" and "Итоги недели" not in body  # the heading is the title, not repeated
    assert "&lt;script&gt;" in body and "<script" not in body  # text stays text
    assert 'href="https://example.com/"' in body and "javascript:" not in body


@pytest.fixture
def writer(session):
    user = User(nickname="writer1", discord_id="1", role=Role.writer)
    session.add(user)
    session.commit()
    app.dependency_overrides[get_session] = lambda: session
    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    yield TestClient(app, headers={"Authorization": f"Bearer {token}"})
    app.dependency_overrides.clear()
    limiter.clear()


def test_import_list_and_remove(writer):
    files = {"file": ("news.docx", docx([p("Анонс"), p("Текст новости")]), "application/octet-stream")}
    created = writer.post("/api/v1/articles", files=files)
    assert created.status_code == 201, created.text
    news = writer.get("/api/v1/articles?drafts=true").json()
    assert [(n["title"], n["author"]) for n in news] == [("Анонс", "writer1")]
    assert "Текст новости" in news[0]["body_html"]
    assert writer.post("/api/v1/articles", files={"file": ("x.docx", b"not a docx", "text/plain")}).status_code == 422
    # The article's author can be given by hand; who imported it is kept apart
    files = {"file": ("b.docx", docx([p("Интервью")]), "application/octet-stream")}
    other = writer.post("/api/v1/articles", files=files, data={"author": "Spartanchick"}).json()
    assert (other["author"], other["imported_by"]) == ("Spartanchick", "writer1")
    writer.delete(f"/api/v1/articles/{other['id']}")
    assert writer.delete(f"/api/v1/articles/{news[0]['id']}").status_code == 204
    assert writer.get("/api/v1/articles?drafts=true").json() == []


def test_the_list_carries_only_the_start_of_an_article(writer):
    text = "&lt;script&gt;x&lt;/script&gt; &amp; " + "слово " * 500  # as the document's XML holds them
    files = {"file": ("long.docx", docx([p("Длинная"), p(text)]), "application/octet-stream")}
    post = writer.post("/api/v1/articles", files=files).json()
    listed = writer.get("/api/v1/articles?drafts=true").json()[0]["body_html"]
    assert len(listed) < 500 < len(post["body_html"])
    assert "<" not in listed and "&amp;" in listed
    assert len(writer.get(f"/api/v1/articles/{post['id']}").json()["body_html"]) > 500


def test_reads_are_counted_once_per_reader(writer):
    files = {"file": ("news.docx", docx([p("Анонс")]), "application/octet-stream")}
    article = writer.post("/api/v1/articles", files=files).json()
    assert article["reads"] == 0
    approve(writer, article["id"])
    anyone = TestClient(app)  # no sign-in needed
    url = f"/api/v1/articles/{article['id']}/read"
    assert anyone.post(url).status_code == 403  # not from the site's pages
    assert anyone.post(url, headers={"X-GITV": "1"}).json() == {"reads": 1}
    assert anyone.post(url, headers={"X-GITV": "1"}).json() == {"reads": 1}  # the same address again: not counted
    assert writer.get(f"/api/v1/articles/{article['id']}").json()["reads"] == 1
    assert anyone.post("/api/v1/articles/999/read", headers={"X-GITV": "1"}).status_code == 404


def test_only_news_roles():
    assert Role.writer.can_write_news and Role.event_organizer.can_write_news and Role.admin.can_write_news
    assert not Role.user.can_write_news


def test_pictures_are_files_removed_with_their_post(writer, tmp_path, monkeypatch):
    from app.services import news

    monkeypatch.setattr(news, "MEDIA_DIR", tmp_path)
    data = docx([p("С картинкой"), picture("img1"), picture("bad")], images={"img1": PNG, "bad": b"<svg/>"})
    post = writer.post("/api/v1/articles", files={"file": ("pic.docx", data, "application/octet-stream")}).json()
    saved = list((tmp_path / "news").iterdir())
    assert len(saved) == 1 and saved[0].suffix == ".png"  # the one that isn't a picture is left out
    assert f'src="/api/v1/media/news/{saved[0].name}"' in post["body_html"] and post["body_html"].count("<img") == 1
    writer.delete(f"/api/v1/articles/{post['id']}")
    assert not saved[0].exists()


def test_a_big_upload_kept_on_disk():
    import tempfile

    # The server keeps a big upload in a temporary file whose name is a number (it broke mammoth)
    upload = tempfile.SpooledTemporaryFile(max_size=1)
    upload.write(docx([p("Большой документ"), p("Текст")]))
    upload.seek(0)
    assert docx_to_html(upload)[0] == "Большой документ"


def test_chapters_get_anchors_and_words_contents_goes():
    data = docx(
        [p("Frame rate theory", "Heading1"), p("Contents", "Heading1"), p("Part 1 .... 3"), p("Part 1", "Heading1"),
         p("Theory", "Heading2"), p("Deep", "Heading5"), p("Text")],
    )  # fmt: skip
    title, body, _ = docx_to_html(io.BytesIO(data))
    assert title == "Frame rate theory" and "Contents" not in body and "Part 1 ...." not in body
    assert (
        '<h1 id="ch-1">Part 1</h1>' in body
        and '<h2 id="ch-2">Theory</h2>' in body
        and '<h5 id="ch-3">Deep</h5>' in body
    )


def test_a_translation_is_attached_by_hand(writer):
    files = {
        "file": ("en.docx", docx([p("Frame rate theory"), p("The game runs on frames")]), "application/octet-stream")
    }
    post = writer.post("/api/v1/articles", files=files).json()
    same = {"file": ("en2.docx", docx([p("Still English")]), "application/octet-stream")}
    assert (
        writer.put(f"/api/v1/articles/{post['id']}/translation", files=same).status_code == 422
    )  # not the other language
    ru = {"file": ("ru.docx", docx([p("Теория кадров"), p("Игра идёт по кадрам")]), "application/octet-stream")}
    done = writer.put(f"/api/v1/articles/{post['id']}/translation", files=ru).json()
    assert (done["lang"], done["title_tr"]) == ("en", "Теория кадров") and "по кадрам" in done["body_html_tr"]
    assert writer.delete(f"/api/v1/articles/{post['id']}/translation").status_code == 204
    assert writer.get(f"/api/v1/articles/{post['id']}").json()["body_html_tr"] is None


def test_a_translation_keeps_the_pictures_it_shares():
    from app.services.news import unused_pictures

    a, b, c = (f'<img src="/api/v1/media/news/{x * 32}.png"/>' for x in "abc")
    original, translation = f"<p>{a}{b}</p>", f"<p>{a}{c}</p>"
    assert unused_pictures(translation, original) == [f"news/{'c' * 32}.png"]
    assert unused_pictures(translation, original, translation) == []


def approve(writer, news_id):
    from app.models import NewsPost

    session = app.dependency_overrides[get_session]()
    from datetime import UTC, datetime

    post = session.get(NewsPost, news_id)
    post.approved_at = datetime.now(UTC)
    session.add(post)
    session.commit()


def member(session, nickname, role):
    user = User(nickname=nickname, discord_id=nickname, role=role)
    session.add(user)
    session.commit()
    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def test_a_writers_article_waits_for_an_admin(writer, session):
    files = {"file": ("news.docx", docx([p("Черновик"), p("Текст")]), "application/octet-stream")}
    draft = writer.post("/api/v1/articles", files=files).json()
    assert draft["approved"] is False
    anyone, other = TestClient(app), member(session, "writer2", Role.writer)
    admin = member(session, "boss", Role.admin)
    url = f"/api/v1/articles/{draft['id']}"
    # Hidden from everyone but whoever imported it and admins, and from the plain list (the home page) for them too
    assert anyone.get(url).status_code == 404 and other.get(url).status_code == 404
    assert writer.get(url).status_code == 200 and admin.get(url).status_code == 200
    assert anyone.get("/api/v1/articles?drafts=true").json() == []
    assert other.get("/api/v1/articles?drafts=true").json() == []
    assert writer.get("/api/v1/articles").json() == []
    assert [a["id"] for a in admin.get("/api/v1/articles?drafts=true").json()] == [draft["id"]]
    assert anyone.post(f"{url}/read", headers={"X-GITV": "1"}).status_code == 404
    # Only an admin approves; then it's everyone's
    assert writer.post(f"{url}/approve").status_code == 403
    done = admin.post(f"{url}/approve").json()
    assert done["approved"] is True and done["created_at"] >= draft["created_at"]
    assert [a["id"] for a in anyone.get("/api/v1/articles").json()] == [draft["id"]]


def test_an_admins_article_is_published_at_once(writer, session):
    admin = member(session, "boss", Role.admin)
    files = {"file": ("news.docx", docx([p("Сразу")]), "application/octet-stream")}
    assert admin.post("/api/v1/articles", files=files).json()["approved"] is True
    assert len(TestClient(app).get("/api/v1/articles").json()) == 1


def test_an_article_is_edited_on_its_page(writer, session):
    files = {
        "file": ("news.docx", docx([p("Заголовок"), p("Первый абзац"), p("Лишняя фраза")]), "application/octet-stream")
    }
    post = writer.post("/api/v1/articles", files=files).json()
    url = f"/api/v1/articles/{post['id']}"
    body = '<h2 id="x" onclick="evil()">Глава</h2><p>Первый абзац <b>жирно</b></p><p><br></p><script>x</script>'
    done = writer.patch(url, json={"title": "Новый заголовок", "author": "GITV", "body_html": body}).json()
    assert (done["title"], done["author"]) == ("Новый заголовок", "GITV")
    assert done["body_html"] == '<h2 id="ch-1">Глава</h2><p>Первый абзац <b>жирно</b></p>'
    assert writer.patch(url, json={"body_html": "<p> </p>"}).status_code == 422
    assert writer.patch(url, json={"body_html_tr": "<p>Text</p>"}).status_code == 422  # no translation to edit
    other = member(session, "writer2", Role.writer)
    assert other.patch(url, json={"title": "Чужая"}).status_code == 403  # only its author or an admin


def test_a_writers_edit_sends_a_published_article_back_for_approval(writer, session):
    admin = member(session, "boss", Role.admin)
    files = {"file": ("news.docx", docx([p("Статья"), p("Текст")]), "application/octet-stream")}
    post = writer.post("/api/v1/articles", files=files).json()
    url = f"/api/v1/articles/{post['id']}"
    admin.post(f"{url}/approve")
    assert admin.patch(url, json={"title": "Правка админа"}).json()["approved"] is True
    assert writer.patch(url, json={"title": "Правка автора"}).json()["approved"] is False


def test_the_document_is_replaced_with_a_new_version(writer):
    files = {"file": ("news.docx", docx([p("Статья"), p("Старый текст")]), "application/octet-stream")}
    post = writer.post("/api/v1/articles", files=files).json()
    new = {"file": ("v2.docx", docx([p("Статья v2"), p("Новый текст")]), "application/octet-stream")}
    done = writer.put(f"/api/v1/articles/{post['id']}/document", files=new).json()
    assert done["title"] == "Статья v2" and "Новый текст" in done["body_html"] and "Старый" not in done["body_html"]
