import type { Route } from "./+types/articles";
import { ArticlesListPage } from "../articles/ArticlesPage";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [
    { title: t("Articles · GITV", "Статьи · GITV") },
    { name: "description", content: t("Guides and research about the Abyss.", "Гайды и исследования по Бездне.") },
  ];
}

export default function Articles() {
  return <ArticlesListPage />;
}
