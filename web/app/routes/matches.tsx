import type { Route } from "./+types/matches";
import { MatchesPage } from "../match/MatchesPage";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [
    { title: t("Matches · GITV", "Матчи · GITV") },
    { name: "description", content: t("Imported tournament matches.", "Матчи турниров.") },
  ];
}

export default function Matches() {
  return <MatchesPage />;
}
