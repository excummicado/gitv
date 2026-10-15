import type { Route } from "./+types/player";
import { PlayerPage } from "../player/PlayerPage";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [
    { title: t("Player Statistics · GITV", "Статистика игрока · GITV") },
    { name: "description", content: t("Player statistics and match history.", "Статистика игрока и история матчей.") },
  ];
}

export default function Player({ params }: Route.ComponentProps) {
  return <PlayerPage playerId={params.playerId} />;
}
