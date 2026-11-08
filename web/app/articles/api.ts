// Articles (api/app/routers/articles.py): read by anyone, imported from a .docx file or a Google document by writers,
// event organizers and admins.

import { getJson } from "../api";
import { authRequest, PLAYER_EDITOR_ROLES, type Role } from "../auth/client";

// author: as given when importing, else who imported it (imported_by)
export type Article = {
  id: number; title: string; body_html: string; source: string; author: string; imported_by: string; created_at: string;
  // A translation into the other language, uploaded by hand: the post's language and the translated title and body
  lang: "ru" | "en" | null; title_tr: string | null; body_html_tr: string | null;
  reads: number; // readers who stayed on it at least READ_SECONDS
  approved: boolean; // false: a draft, seen only by admins and whoever imported it until an admin approves it
};

// How long the article must be open (and its tab visible) before it counts as read (as the API's READ_SECONDS).
export const READ_SECONDS = 30;

// The post in the reader's language when it's been translated into it, else as written.
export function inLang(post: Article, lang: string) {
  const translated = post.body_html_tr != null && post.lang !== lang;
  return { title: translated ? post.title_tr ?? post.title : post.title, body: translated ? post.body_html_tr! : post.body_html, translated };
}

export const NEWS_WRITER_ROLES: Role[] = ["writer", ...PLAYER_EDITOR_ROLES];

// drafts: the drafts the signed-in member may see come first (the articles page; the home page shows published only).
export function listArticles(limit = 10, signal?: AbortSignal, drafts = false) {
  return getJson<Article[]>(`/api/v1/articles?limit=${limit}${drafts ? "&drafts=true" : ""}`, { signal, failed: ["Couldn't load the articles.", "Не удалось загрузить статьи."] });
}

export function readArticle(id: string, signal?: AbortSignal) {
  return getJson<Article>(`/api/v1/articles/${encodeURIComponent(id)}`, { signal, notFound: ["No such article.", "Такой статьи нет."] });
}

// One of the two: a .docx file or a Google Docs link shared with "anyone with the link".
export function importArticle(input: { file?: File; googleUrl?: string; title?: string; author?: string }) {
  const form = new FormData();
  if (input.file) form.append("file", input.file);
  if (input.googleUrl) form.append("google_url", input.googleUrl);
  if (input.title) form.append("title", input.title);
  if (input.author) form.append("author", input.author);
  return authRequest<Article>("POST", "/articles", form);
}

// The post's translation into the other language, from a .docx file or a Google Docs link (replaces one there is).
export function setTranslation(id: number, input: { file?: File; googleUrl?: string; title?: string }) {
  const form = new FormData();
  if (input.file) form.append("file", input.file);
  if (input.googleUrl) form.append("google_url", input.googleUrl);
  if (input.title) form.append("title", input.title);
  return authRequest<Article>("PUT", `/articles/${id}/translation`, form);
}

export function deleteTranslation(id: number) {
  return authRequest<null>("DELETE", `/articles/${id}/translation`);
}

// Reports a read (no sign-in needed); the article's count after it, or null when it couldn't be reported.
export async function reportRead(id: number): Promise<number | null> {
  try {
    const r = await fetch(`/api/v1/articles/${id}/read`, { method: "POST", headers: { "X-GITV": "1" } });
    return r.ok ? ((await r.json()) as { reads: number }).reads : null;
  } catch {
    return null;
  }
}

// An admin publishes a draft (dated now).
export function approveArticle(id: number) {
  return authRequest<Article>("POST", `/articles/${id}/approve`);
}

export function deleteArticle(id: number) {
  return authRequest<null>("DELETE", `/articles/${id}`);
}

// The first words of a post, for lists.
export function excerpt(html: string, length = 160) {
  const text = html.replace(/<[^>]+>/g, " ").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/\s+/g, " ").trim();
  return text.length > length ? `${text.slice(0, length).trimEnd()}…` : text;
}
