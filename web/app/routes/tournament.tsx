import type { Route } from "./+types/tournament";
import { TournamentPage } from "../tournament/TournamentPage";
import { metaLang } from "../i18n";
import { noPreview, previewMeta } from "../preview";
import { previewFor } from "../preview.server";

export async function loader({ params, request }: Route.LoaderArgs) {
  return previewFor("tournament", params.tournamentId, request);
}

export const clientLoader = noPreview;

export function meta({ matches, loaderData }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return previewMeta(loaderData, t("Tournament · GITV", "Турнир · GITV"), t("Tournament standings, bracket, matches and stats.", "Таблица, сетка, матчи и статистика турнира."));
}

export default function Tournament({ params }: Route.ComponentProps) {
  return <TournamentPage tournamentId={params.tournamentId} />;
}
