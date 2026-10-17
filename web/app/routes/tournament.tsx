import type { Route } from "./+types/tournament";
import { TournamentPage } from "../tournament/TournamentPage";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [
    { title: t("Tournament · GITV", "Турнир · GITV") },
    { name: "description", content: t("Tournament standings, bracket, matches and stats.", "Таблица, сетка, матчи и статистика турнира.") },
  ];
}

export default function Tournament({ params }: Route.ComponentProps) {
  return <TournamentPage tournamentId={params.tournamentId} />;
}
