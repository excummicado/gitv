import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { useAuth } from "../auth/useCurrentUser";
import { STAFF_ROLES } from "../auth/client";
import { useLang } from "../i18n";
import { deleteArticle, deleteTranslation, excerpt, importArticle, inLang, listArticles, NEWS_WRITER_ROLES, READ_SECONDS, readArticle, reportRead, setTranslation, type Article } from "./api";
import "./articles.css";

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame news-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="player-content match-content">{children}</div>
        </div>
      </div>
    </main>
  );
}

type Chapter = { id: string; level: number; text: string };

// The post's chapters: its headings, which the API gave anchors (ch-1, ch-2, …).
function chaptersOf(body: string): Chapter[] {
  const out: Chapter[] = [];
  for (const m of body.matchAll(/<h([1-6]) id="(ch-\d+)">([\s\S]*?)<\/h\1>/g)) {
    const text = m[3].replace(/<[^>]+>/g, "").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&#39;|&apos;/g, "'").replace(/&quot;/g, '"').trim();
    if (text) out.push({ id: m[2], level: Number(m[1]), text });
  }
  return out;
}

// The chapter list: the top three heading levels the document uses, indented, the one being read highlighted.
function Contents({ chapters, active, onPick }: { chapters: Chapter[]; active: string | null; onPick?: () => void }) {
  const levels = [...new Set(chapters.map((c) => c.level))].sort().slice(0, 3);
  return (
    <ol className="news-toc-list">
      {chapters.filter((c) => levels.includes(c.level)).map((c) => (
        <li key={c.id} className={`news-toc-item is-l${levels.indexOf(c.level)}${active === c.id ? " is-active" : ""}`}>
          <a href={`#${c.id}`} onClick={onPick}>{c.text}</a>
        </li>
      ))}
    </ol>
  );
}

// Attaching the post's translation into the other language: a translated .docx or Google document.
function TranslationForm({ post, onDone }: { post: Article; onDone: (post: Article) => void }) {
  const { t } = useLang();
  const [file, setFile] = useState<File | null>(null);
  const [googleUrl, setGoogleUrl] = useState("");
  const [title, setTitle] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const has = post.body_html_tr != null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file === !googleUrl.trim()) return setMessage({ text: t("A .docx file or a Google Docs link, one of the two.", "Файл .docx или ссылка на Google Документ, что-то одно."), ok: false });
    setSaving(true);
    try {
      onDone(await setTranslation(post.id, { file: file ?? undefined, googleUrl: googleUrl.trim() || undefined, title: title.trim() || undefined }));
      setMessage({ text: t("Translation saved.", "Перевод сохранён."), ok: true });
    } catch (err) {
      setMessage({ text: err instanceof Error ? err.message : t("Couldn't save it.", "Не удалось сохранить."), ok: false });
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!window.confirm(t("Remove the translation?", "Удалить перевод?"))) return;
    try {
      await deleteTranslation(post.id);
      onDone({ ...post, lang: null, title_tr: null, body_html_tr: null });
    } catch (err) {
      setMessage({ text: err instanceof Error ? err.message : t("Couldn't remove it.", "Не удалось удалить."), ok: false });
    }
  }

  return (
    <details className="news-tr-box">
      <summary className="player-label">{has ? t("Replace the translation", "Заменить перевод") : t("Add a translation", "Добавить перевод")}</summary>
      <form className="news-form" onSubmit={submit} noValidate>
        <label className="news-field">
          <span className="player-label">{t("Translated document (.docx)", "Документ с переводом (.docx)")}</span>
          <input className="match-input" type="file" accept=".docx" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setMessage(null); }} />
        </label>
        <label className="news-field">
          <span className="player-label">{t("or a Google Docs link", "или ссылка на Google Документ")}</span>
          <input className="match-input" type="url" value={googleUrl} maxLength={300} placeholder="https://docs.google.com/document/d/…" onChange={(e) => { setGoogleUrl(e.target.value); setMessage(null); }} />
        </label>
        <label className="news-field">
          <span className="player-label">{t("Translated title (optional)", "Заголовок перевода (необязательно)")}</span>
          <input className="match-input" value={title} maxLength={200} onChange={(e) => { setTitle(e.target.value); setMessage(null); }} />
        </label>
        <div className="news-actions">
          <button type="submit" className="suggest-button" disabled={saving}>{saving ? t("Saving…", "Сохранение…") : t("Save translation", "Сохранить перевод")}</button>
          {has && <button type="button" className="news-remove" onClick={remove}>{t("Remove the translation", "Удалить перевод")}</button>}
          {message && <span className={message.ok ? "suggest-ok" : "suggest-error"} role="status">{message.text}</span>}
        </div>
      </form>
    </details>
  );
}

// One article. Its body is HTML the API cleaned (only text formatting, links and pictures); a long one, with
// chapters, gets a chapter list beside it (above it on a phone).
// Counts the article as read once it has been open READ_SECONDS with its tab in view (time in a hidden tab doesn't
// count); once per browser per article. Calls back with the new count.
function useReadCounter(id: number | undefined, onCounted: (reads: number) => void) {
  useEffect(() => {
    if (id == null) return;
    const key = `gitv-read-${id}`;
    try { if (localStorage.getItem(key)) return; } catch { /* storage unavailable: count anyway */ }
    let seen = 0;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      seen += 1;
      if (seen < READ_SECONDS) return;
      window.clearInterval(timer);
      try { localStorage.setItem(key, "1"); } catch { /* storage unavailable */ }
      reportRead(id).then((reads) => { if (reads != null) onCounted(reads); });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [id]);
}

function Reads({ count: n }: { count: number }) {
  const { count } = useLang();
  return <span title={`${READ_SECONDS}+ s`}>{count(n, ["read", "reads"], ["прочтение", "прочтения", "прочтений"])}</span>;
}

export function ArticlePage() {
  const { articleId = "" } = useParams();
  const { user } = useAuth();
  const { t, date, lang } = useLang();
  const [post, setPost] = useState<Article | null | undefined>(undefined);
  // Read in the site's language when there's a translation into it; the reader can switch to the original
  const [original, setOriginal] = useState(false);
  // Whoever imported it, or an admin, may attach its translation
  const canEdit = Boolean(post && user && (STAFF_ROLES.includes(user.role) || (NEWS_WRITER_ROLES.includes(user.role) && post.imported_by === user.nickname)));
  const shown = post ? (original ? { title: post.title, body: post.body_html, translated: false } : inLang(post, lang)) : null;
  const [error, setError] = useState("");
  const [active, setActive] = useState<string | null>(null);
  // Open beside the post; folded above it on a phone, where it would push the post down
  const [tocOpen, setTocOpen] = useState(true);
  useEffect(() => { if (window.innerWidth <= 900) setTocOpen(false); }, []);
  const chapters = useMemo(() => (shown ? chaptersOf(shown.body) : []), [shown?.body]);
  const body = useRef<HTMLDivElement>(null);

  // The chapter being read: the last heading above the top quarter of the window.
  useEffect(() => {
    if (chapters.length < 3) return;
    const onScroll = () => {
      const headings = body.current?.querySelectorAll<HTMLElement>("[id^='ch-']") ?? [];
      let current: string | null = null;
      for (const h of headings) if (h.getBoundingClientRect().top < window.innerHeight / 4) current = h.id;
      setActive(current);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [chapters]);

  // A long chapter list follows the reading: the highlighted chapter stays in view
  useEffect(() => {
    if (!active) return;
    document.querySelector(`.news-toc a[href="#${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  useReadCounter(post?.id, (reads) => setPost((p) => (p ? { ...p, reads } : p)));

  useEffect(() => {
    const controller = new AbortController();
    readArticle(articleId, controller.signal).then(setPost).catch((err) => { if (!controller.signal.aborted) { setPost(null); setError(err instanceof Error ? err.message : ""); } });
    return () => controller.abort();
  }, [articleId]);


  return (
    <Frame>
      {post === undefined ? <p className="player-box match-empty">…</p>
        : !post ? <p className="player-box match-empty">{error || t("No such article.", "Такой статьи нет.")}</p>
        : (
          <div className={chapters.length >= 3 ? "news-layout" : undefined}>
            {chapters.length >= 3 && (
              <nav className="player-box news-toc" aria-label={t("Chapters", "Главы")}>
                <details open={tocOpen} onToggle={(e) => setTocOpen(e.currentTarget.open)} className="news-toc-details">
                  <summary className="player-box-title">{t("Contents", "Содержание")}</summary>
                  <Contents chapters={chapters} active={active} onPick={() => { if (window.innerWidth <= 900) setTocOpen(false); }} />
                </details>
              </nav>
            )}
            <article className="player-box news-article">
              <h1 className="news-title">{shown!.title}</h1>
              <p className="player-label news-meta">{date(post.created_at)} · {post.author} · <Reads count={post.reads} /></p>
              {post.body_html_tr != null && post.lang !== lang && (
                <p className="news-translation">
                  {original
                    ? <>{t("Original.", "Оригинал.")} <button type="button" className="news-switch" onClick={() => setOriginal(false)}>{t("Show the translation", "Показать перевод")}</button></>
                    : <>{t("Translation.", "Перевод.")} <button type="button" className="news-switch" onClick={() => setOriginal(true)}>{t("Show the original", "Показать оригинал")}</button></>}
                </p>
              )}
              <div className="news-body" ref={body} dangerouslySetInnerHTML={{ __html: shown!.body }} />
              <p className="news-foot"><Link to="/articles" className="gitv-row-link">{t("All articles", "Все статьи")}</Link></p>
              {canEdit && <TranslationForm post={post} onDone={(p) => { setPost(p); setOriginal(false); }} />}
            </article>
          </div>
        )}
    </Frame>
  );
}

// All articles, and for writers, event organizers and admins the import form: a .docx file or a Google Docs link.
export function ArticlesListPage() {
  const { user } = useAuth();
  const { t, date, lang } = useLang();
  const writer = user ? NEWS_WRITER_ROLES.includes(user.role) : false;
  const staff = user ? STAFF_ROLES.includes(user.role) : false;
  const [posts, setPosts] = useState<Article[] | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [googleUrl, setGoogleUrl] = useState("");
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const [formKey, setFormKey] = useState(0);

  const load = () => listArticles(50).then(setPosts).catch(() => setPosts([]));
  useEffect(() => { load(); }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file && !googleUrl.trim()) return setMessage({ text: t("Choose a .docx file or paste a Google Docs link.", "Выберите файл .docx или вставьте ссылку на Google Документ."), ok: false });
    if (file && googleUrl.trim()) return setMessage({ text: t("One of the two: a file or a link.", "Что-то одно: файл или ссылка."), ok: false });
    setSaving(true);
    try {
      await importArticle({ file: file ?? undefined, googleUrl: googleUrl.trim() || undefined, title: title.trim() || undefined, author: author.trim() || undefined });
      setMessage({ text: t("Published.", "Опубликовано."), ok: true });
      setFile(null);
      setGoogleUrl("");
      setTitle("");
      setAuthor("");
      setFormKey((k) => k + 1);
      load();
    } catch (err) {
      setMessage({ text: err instanceof Error ? err.message : t("Couldn't import it. Try again.", "Не удалось импортировать. Попробуйте ещё раз."), ok: false });
    } finally {
      setSaving(false);
    }
  }

  async function remove(post: Article) {
    if (!window.confirm(t(`Remove "${post.title}"?`, `Удалить «${post.title}»?`))) return;
    try {
      await deleteArticle(post.id);
      setPosts((list) => list?.filter((p) => p.id !== post.id) ?? null);
    } catch (err) {
      setMessage({ text: err instanceof Error ? err.message : t("Couldn't remove it.", "Не удалось удалить."), ok: false });
    }
  }

  return (
    <Frame>
      {writer && (
        <section className="player-box">
          <h2 className="player-box-title">{t("Add an article", "Добавить статью")}</h2>
          <form className="news-form" onSubmit={submit} key={formKey} noValidate>
            <label className="news-field">
              <span className="player-label">{t("Word document (.docx, up to 100 MB)", "Документ Word (.docx, до 100 МБ)")}</span>
              <input className="match-input" type="file" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                onChange={(e) => { setFile(e.target.files?.[0] ?? null); setMessage(null); }} />
            </label>
            <label className="news-field">
              <span className="player-label">{t("or a Google Docs link", "или ссылка на Google Документ")}</span>
              <input className="match-input" type="url" value={googleUrl} maxLength={300} placeholder="https://docs.google.com/document/d/…"
                onChange={(e) => { setGoogleUrl(e.target.value); setMessage(null); }} />
              <span className="news-hint">{t('Share it as "anyone with the link can view".', "Откройте доступ «всем, у кого есть ссылка».")}</span>
            </label>
            <label className="news-field">
              <span className="player-label">{t("Title (optional)", "Заголовок (необязательно)")}</span>
              <input className="match-input" value={title} maxLength={200} placeholder={t("Else the document's first heading", "Иначе первый заголовок документа")}
                onChange={(e) => { setTitle(e.target.value); setMessage(null); }} />
            </label>
            <label className="news-field">
              <span className="player-label">{t("Author (optional)", "Автор (необязательно)")}</span>
              <input className="match-input" value={author} maxLength={100} placeholder={t("Else you", "Иначе — вы")}
                onChange={(e) => { setAuthor(e.target.value); setMessage(null); }} />
            </label>
            <div className="news-actions">
              <button type="submit" className="suggest-button" disabled={saving}>{saving ? t("Importing…", "Импорт…") : t("Publish", "Опубликовать")}</button>
              {message && <span className={message.ok ? "suggest-ok" : "suggest-error"} role="status">{message.text}</span>}
            </div>
          </form>
        </section>
      )}
      <section className="player-box">
        <h2 className="player-box-title">{t("Articles", "Статьи")}</h2>
        {!posts ? <p className="match-empty">…</p>
          : !posts.length ? <p className="match-empty">{t("No articles yet.", "Статей пока нет.")}</p>
          : posts.map((p) => (
            <div className="news-row" key={p.id}>
              <Link to={`/articles/${p.id}`} className="gitv-row-link news-row-title">{inLang(p, lang).title}</Link>
              <p className="news-row-excerpt">{excerpt(inLang(p, lang).body)}</p>
              <span className="player-label">
                {date(p.created_at)} · {p.author} · <Reads count={p.reads} />
                {(staff || (user && p.imported_by === user.nickname)) && (
                  <> · <button type="button" className="news-remove" onClick={() => remove(p)}>{t("Remove", "Удалить")}</button></>
                )}
              </span>
            </div>
          ))}
      </section>
    </Frame>
  );
}
