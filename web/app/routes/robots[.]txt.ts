// /robots.txt: everything but the account pages, and where the sitemap is.
import type { Route } from "./+types/robots[.]txt";
import { siteOrigin } from "../preview.server";

export function loader({ request }: Route.LoaderArgs) {
  const lines = [
    "User-agent: *",
    "Disallow: /profile",
    "Disallow: /login",
    "Disallow: /auth/",
    "Disallow: /analytics",
    "Disallow: /api/",
    `Sitemap: ${siteOrigin(request)}/sitemap.xml`,
  ];
  return new Response(lines.join("\n") + "\n", { headers: { "Content-Type": "text/plain; charset=utf-8" } });
}
