import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { STAFF_ROLES } from "../auth/client";
import { useCurrentUser } from "../auth/useCurrentUser";
import { NEWS_WRITER_ROLES } from "../articles/api";
import { useLang } from "../i18n";
import { addNewsItem, deleteNewsItem, listNewsItems, NEWS_MAX, type NewsItem } from "./api";
import "./news-column.css";

const PAGE = 5;
const LINK = /(https?:\/\/[^\s<]+[^\s<.,;:!?)\]'"])/g;
// The lines a registration item ends with (api/app/services/registrations.py): shown as buttons, not text
const ACTION = /^(Заявка|Подробнее):\s*(https?:\/\/\S+)$/;

// A link's label in a narrow column: no scheme, at most 24 characters ("forms.gle/Zw5Z8BUTYW7uU…").
function short(url: string) {
  const bare = url.replace(/^https?:\/\/(www\.)?/, "");
  return bare.length > 24 ? `${bare.slice(0, 23)}…` : bare;
}

// The text with its web addresses as links (the text itself is plain: React escapes it).
function withLinks(text: string): ReactNode[] {
  return text.split(LINK).map((part, i) =>
    i % 2 ? <a key={i} href={part} target="_blank" rel="noopener noreferrer nofollow" className="news-inline-link" title={part}>{short(part)}</a> : part);
}

// An item as title, details and actions: its first line is the title, "Заявка: …" / "Подробнее: …" lines are
// buttons, everything else is detail.
function parts(text: string) {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  const actions: { kind: string; url: string }[] = [];
  const rest: string[] = [];
  for (const line of lines) {
    const m = ACTION.exec(line);
    if (m) actions.push({ kind: m[1], url: m[2] });
    else rest.push(line);
  }
  return { title: rest[0] ?? "", details: rest.slice(1), actions };
}

function useAgo() {
  const { lang, t } = useLang();
  const locale = lang === "ru" ? "ru-RU" : "en-GB";
  return (iso: string) => {
    const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    const rel = new Intl.RelativeTimeFormat(locale, { numeric: "auto", style: "short" });
    if (minutes < 1) return t("just now", "только что");
    if (minutes < 60) return rel.format(-minutes, "minute");
    if (minutes < 24 * 60) return rel.format(-Math.round(minutes / 60), "hour");
    if (minutes < 7 * 24 * 60) return rel.format(-Math.round(minutes / 1440), "day");
    return new Date(iso).toLocaleDateString(locale, { day: "numeric", month: "short" });
  };
}

function Item({ item, canRemove, onRemove }: { item: NewsItem; canRemove: boolean; onRemove: () => void }) {
  const { t, lang } = useLang();
  const ago = useAgo();
  const { title, details, actions } = parts(item.text);
  const full = new Date(item.created_at).toLocaleString(lang === "ru" ? "ru-RU" : "en-GB", { dateStyle: "medium", timeStyle: "short" });
  return (
    <article className={`news-item${item.source_url ? " is-channel" : ""}`}>
      <header className="news-item-head">
        <span className="news-item-source">
          <span className="news-item-dot" aria-hidden />
          {item.author}
        </span>
        <time dateTime={item.created_at} title={full}>{ago(item.created_at)}</time>
        {canRemove && (
          <button type="button" className="news-item-remove" onClick={onRemove} aria-label={t("Remove", "Удалить")} title={t("Remove", "Удалить")}>×</button>
        )}
      </header>
      <p className="news-item-title">{withLinks(title)}</p>
      {details.length > 0 && <ul className="news-item-details">{details.map((d, i) => <li key={i}>{withLinks(d)}</li>)}</ul>}
      {actions.length > 0 && (
        <div className="news-item-actions">
          {actions.map((a) => (
            <a key={a.url} href={a.url} target="_blank" rel="noopener noreferrer nofollow" title={a.url}
              className={`news-item-action${a.kind === "Заявка" ? " is-primary" : ""}`}>
              {a.kind === "Заявка" ? t("Sign up", "Подать заявку") : t("Post", "Пост")} <span aria-hidden>↗</span>
            </a>
          ))}
        </div>
      )}
    </article>
  );
}

// The home page's news column: short items, newest first, more on request. Writers, event organizers and admins
// write one in place (the form opens from the header); its author or an admin removes it.
export function NewsColumn() {
  const { t } = useLang();
  const user = useCurrentUser();
  const writer = user ? NEWS_WRITER_ROLES.includes(user.role) : false;
  const [items, setItems] = useState<NewsItem[] | null>(null);
  const [more, setMore] = useState(false);
  const [writing, setWriting] = useState(false);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    listNewsItems(PAGE, undefined, controller.signal)
      .then((rows) => { setItems(rows); setMore(rows.length === PAGE); })
      .catch(() => { if (!controller.signal.aborted) setItems([]); });
    return () => controller.abort();
  }, []);

  useEffect(() => { if (writing) box.current?.focus(); }, [writing]);

  async function loadMore() {
    const last = items?.[items.length - 1];
    if (!last) return;
    const rows = await listNewsItems(PAGE, last.id).catch(() => []);
    setItems((current) => [...(current ?? []), ...rows]);
    setMore(rows.length === PAGE);
  }

  async function publish(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!text.trim()) return;
    setSaving(true);
    setError("");
    try {
      const item = await addNewsItem(text.trim());
      setItems((current) => [item, ...(current ?? [])]);
      setText("");
      setWriting(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Couldn't publish.", "Не удалось опубликовать."));
    } finally {
      setSaving(false);
    }
  }

  async function remove(item: NewsItem) {
    if (!window.confirm(t("Remove this news?", "Удалить эту новость?"))) return;
    try {
      await deleteNewsItem(item.id);
      setItems((current) => (current ?? []).filter((i) => i.id !== item.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Couldn't remove it.", "Не удалось удалить."));
    }
  }

  return (
    <section className="gitv-card news-column">
      <div className="gitv-card-title tinted news-column-title">
        <span>{t("News", "Новости")}</span>
        {writer && !writing && (
          <button type="button" className="news-column-write" onClick={() => setWriting(true)}>+ {t("Write", "Написать")}</button>
        )}
      </div>
      {writing && (
        <form className="news-column-form" onSubmit={publish}>
          <textarea ref={box} value={text} onChange={(e) => setText(e.target.value)} maxLength={NEWS_MAX} rows={4}
            placeholder={t("First line is the title…", "Первая строка — заголовок…")} aria-label={t("News text", "Текст новости")}
            onKeyDown={(e) => { if (e.key === "Escape") setWriting(false); }} />
          <div className="news-column-actions">
            <small className={text.length > NEWS_MAX - 50 ? "is-near" : undefined}>{text.length}/{NEWS_MAX}</small>
            <button type="button" className="news-column-cancel" onClick={() => { setWriting(false); setError(""); }}>{t("Cancel", "Отмена")}</button>
            <button type="submit" className="suggest-button" disabled={saving || !text.trim()}>
              {saving ? t("Publishing…", "Публикую…") : t("Publish", "Опубликовать")}
            </button>
          </div>
          {error && <p className="suggest-error" role="alert">{error}</p>}
        </form>
      )}
      {!items ? <div className="news-column-empty">…</div>
        : !items.length ? <div className="news-column-empty">{t("No news yet.", "Новостей пока нет.")}</div>
        : items.map((item) => (
            <Item key={item.id} item={item} onRemove={() => remove(item)}
              canRemove={Boolean(user && (item.author_id === user.id || STAFF_ROLES.includes(user.role)))} />
          ))}
      {more && (
        <button type="button" className="news-column-more" onClick={loadMore}>{t("Show more", "Показать ещё")}</button>
      )}
    </section>
  );
}
