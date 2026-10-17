import type { Route } from "./+types/match";
import { MatchPage } from "../match/MatchPage";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [
    { title: t("Match · GITV", "Матч · GITV") },
    { name: "description", content: t("Match results, teams and draft.", "Результаты матча, составы и драфт.") },
  ];
}

export default function Match({ params }: Route.ComponentProps) {
  return <MatchPage matchId={params.matchId} />;
}
