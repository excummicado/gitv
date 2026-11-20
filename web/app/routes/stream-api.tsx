import type { Route } from "./+types/stream-api";
import { StreamApiDocs } from "../stream-api/StreamApiDocs";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [
    { title: t("Stream API · GITV", "API для стримов · GITV") },
    { name: "description", content: t("Players' Elo, statistics and head-to-heads from GITV for stream overlays.", "Эло, статистика и личные встречи игроков с GITV для оверлеев на стримах.") },
  ];
}

export default function StreamApi() {
  return <StreamApiDocs />;
}
