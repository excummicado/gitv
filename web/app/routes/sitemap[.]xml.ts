// /sitemap.xml: the main pages, then every player, tournament, article and Abyss phase (from the API).
import type { Route } from "./+types/sitemap[.]xml";
import { API, siteOrigin } from "../preview.server";

type Pages = { players: string[]; tournaments: string[]; articles: number[]; abyss: number[] };

export async function loader({ request }: Route.LoaderArgs) {
  const origin = siteOrigin(request);
  let pages: Pages = { players: [], tournaments: [], articles: [], abyss: [] };
  try {
    const response = await fetch(`${API}/api/v1/preview/pages`, { signal: AbortSignal.timeout(5000) });
    if (response.ok) pages = await response.json();
  } catch {
    // The API down: the main pages alone.
  }
  const paths = [
    "/", "/players", "/tournaments", "/matches", "/characters", "/articles", "/abyss", "/privacy",
    ...pages.players.map((id) => `/player/${encodeURIComponent(id)}`),
    ...pages.tournaments.map((id) => `/tournament/${encodeURIComponent(id)}`),
    ...pages.articles.map((id) => `/articles/${id}`),
    ...pages.abyss.map((id) => `/abyss/${id}`),
  ];
  const urls = paths.map((p) => `  <url><loc>${origin}${p.replace(/&/g, "&amp;")}</loc></url>`).join("\n");
  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`;
  return new Response(xml, { headers: { "Content-Type": "application/xml; charset=utf-8", "Cache-Control": "public, max-age=3600" } });
}
