import type { Route } from "./+types/tournaments";
import { TournamentsPage } from "../tournament/TournamentsPage";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [
    { title: t("Tournaments · GITV", "Турниры · GITV") },
    { name: "description", content: t("Every imported tournament with its winner and places.", "Все турниры с победителями и местами.") },
  ];
}

export default function Tournaments() {
  return <TournamentsPage />;
}
