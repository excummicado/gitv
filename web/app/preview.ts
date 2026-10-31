// A page's meta tags with its link preview (preview.server.ts), falling back to the route's generic ones. After
// the first page, navigating in the site skips the server (each route's clientLoader), so titles stay generic then.
import type { MetaDescriptor } from "react-router";

export type PageInfo = { url: string; image: string; title: string | null; description: string | null };

export function previewMeta(info: PageInfo | null | undefined, title: string, description: string): MetaDescriptor[] {
  const shown = info?.title ? `${info.title} · GITV` : title;
  const about = info?.description ?? description;
  const tags: MetaDescriptor[] = [
    { title: shown },
    { name: "description", content: about },
    { property: "og:site_name", content: "GITV" },
    { property: "og:type", content: "website" },
    { property: "og:title", content: info?.title ?? title },
    { property: "og:description", content: about },
    { name: "twitter:card", content: "summary" },
  ];
  if (info) tags.push({ property: "og:url", content: info.url }, { property: "og:image", content: info.image });
  return tags;
}

// Navigating inside the site: no preview needed, so no trip to the server.
export async function noPreview() {
  return null;
}
