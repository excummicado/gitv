import { redirect } from "react-router";
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

// A tournament's matches live on its page: old /matches?tournament=<id> links go there.
export function loader({ request }: Route.LoaderArgs) {
  const tournament = new URL(request.url).searchParams.get("tournament");
  if (tournament) throw redirect(`/tournament/${encodeURIComponent(tournament)}`, 301);
  return null;
}

export default function Matches() {
  return <MatchesPage />;
}
