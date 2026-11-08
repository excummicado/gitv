// Short news of the home page's column (api/app/routers/news.py): read by anyone, written there by writers, event
// organizers and admins, or added by themselves from Abyss Cup's and House of the Hearth's registration posts
// (author_id null, author the channel's name); edited or removed by their author or an admin. Articles are ../articles.
import { getJson } from "../api";
import { authRequest } from "../auth/client";

export type NewsItem = {
  id: number; text: string; author: string; author_id: string | null; source_url: string | null; created_at: string;
};

export const NEWS_MAX = 500;

export function listNewsItems(limit: number, before?: number, signal?: AbortSignal) {
  const query = new URLSearchParams({ limit: String(limit) });
  if (before != null) query.set("before", String(before));
  return getJson<NewsItem[]>(`/api/v1/news?${query}`, { signal, failed: ["Couldn't load the news.", "Не удалось загрузить новости."] });
}

export function addNewsItem(text: string) {
  return authRequest<NewsItem>("POST", "/news", { text });
}

// Its author or an admin changes the text; it keeps its place and date.
export function editNewsItem(id: number, text: string) {
  return authRequest<NewsItem>("PATCH", `/news/${id}`, { text });
}

export function deleteNewsItem(id: number) {
  return authRequest<null>("DELETE", `/news/${id}`);
}
