import type { Route } from "./+types/player";
import { PlayerPage } from "../player/PlayerPage";
import { metaLang } from "../i18n";
import { noPreview, previewMeta } from "../preview";
import { previewFor } from "../preview.server";

export async function loader({ params, request }: Route.LoaderArgs) {
  return previewFor("player", params.playerId, request);
}

export const clientLoader = noPreview;

export function meta({ matches, loaderData }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return previewMeta(loaderData, t("Player Statistics · GITV", "Статистика игрока · GITV"), t("Player statistics and match history.", "Статистика игрока и история матчей."));
}

export default function Player({ params }: Route.ComponentProps) {
  return <PlayerPage playerId={params.playerId} />;
}
