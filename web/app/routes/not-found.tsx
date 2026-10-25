import { data } from "react-router";
import type { Route } from "./+types/not-found";
import { NotFoundPage } from "../not-found/NotFoundPage";
import { metaLang } from "../i18n";

// Any address no other route matches: the 404 page, with a real 404 status for browsers and search engines.
export function loader() {
  return data(null, { status: 404 });
}

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [{ title: t("Page not found · GITV", "Страница не найдена · GITV") }, { name: "robots", content: "noindex" }];
}

export default function NotFound() {
  return <NotFoundPage />;
}
