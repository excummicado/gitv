// The articles were once at /news: old links (shared in Discord, Telegram) go on to /articles.
import { redirect } from "react-router";
import type { Route } from "./+types/news.redirect";

export function loader({ params }: Route.LoaderArgs) {
  return redirect(params.articleId ? `/articles/${encodeURIComponent(params.articleId)}` : "/articles", 301);
}
