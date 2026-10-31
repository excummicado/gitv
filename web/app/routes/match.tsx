import type { Route } from "./+types/match";
import { MatchPage } from "../match/MatchPage";
import { metaLang } from "../i18n";
import { noPreview, previewMeta } from "../preview";
import { previewFor } from "../preview.server";

export async function loader({ params, request }: Route.LoaderArgs) {
  return previewFor("match", params.matchId, request);
}

export const clientLoader = noPreview;

export function meta({ matches, loaderData }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return previewMeta(loaderData, t("Match · GITV", "Матч · GITV"), t("Match results, teams and draft.", "Результаты матча, составы и драфт."));
}

export default function Match({ params }: Route.ComponentProps) {
  return <MatchPage matchId={params.matchId} />;
}
