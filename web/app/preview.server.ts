// Link previews (Discord, Telegram, search engines) for pages that load their data in the browser: the page's
// server loader asks the API for its title and description (api/app/routers/preview.py). Server only.
import { langFromCookie } from "./i18n";
import type { PageInfo } from "./preview";

// Where the web server reaches the API: the same machine by default (see the README's deployment notes).
export const API = process.env.API_URL ?? "http://127.0.0.1:8000";

// The site's own address as the visitor sees it (behind a proxy: its forwarded scheme and host).
export function siteOrigin(request: Request) {
  const url = new URL(request.url);
  const scheme = request.headers.get("x-forwarded-proto") ?? url.protocol.replace(":", "");
  return `${scheme}://${request.headers.get("x-forwarded-host") ?? url.host}`;
}

export async function previewFor(kind: string, id: string | undefined, request: Request): Promise<PageInfo> {
  const url = new URL(request.url);
  const origin = siteOrigin(request);
  const page = { url: `${origin}${url.pathname}`, image: `${origin}/apple-touch-icon.png` };
  if (!id) return { ...page, title: null, description: null };
  try {
    const query = new URLSearchParams({ kind, id, lang: langFromCookie(request.headers.get("Cookie")) });
    const response = await fetch(`${API}/api/v1/preview?${query}`, { signal: AbortSignal.timeout(2000) });
    const data = response.ok ? ((await response.json()) as { title: string; description: string } | null) : null;
    return { ...page, title: data?.title ?? null, description: data?.description ?? null };
  } catch {
    // The API slow or down: the page still renders, with its generic title.
    return { ...page, title: null, description: null };
  }
}
