import type { Route } from "./+types/news.post";
import { NewsPostPage } from "../news/NewsPage";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [{ title: t("News · GITV", "Новости · GITV") }];
}

export default function NewsPost() {
  return <NewsPostPage />;
}
