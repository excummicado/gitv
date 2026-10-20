import type { Route } from "./+types/site-stats";
import { SiteStatsPage } from "../site-stats/SiteStatsPage";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [{ title: t("Analytics · GITV", "Аналитика · GITV") }, { name: "robots", content: "noindex" }];
}

export default function SiteStats() {
  return <SiteStatsPage />;
}
