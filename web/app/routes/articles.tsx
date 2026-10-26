import type { Route } from "./+types/news";
import { NewsListPage } from "../news/NewsPage";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [{ title: t("News · GITV", "Новости · GITV") }];
}

export default function News() {
  return <NewsListPage />;
}
