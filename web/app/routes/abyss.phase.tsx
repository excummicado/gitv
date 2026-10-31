import type { Route } from "./+types/abyss.phase";
import { AbyssPhasePage } from "../abyss/AbyssPages";
import { metaLang } from "../i18n";
import { noPreview, previewMeta } from "../preview";
import { previewFor } from "../preview.server";

export async function loader({ params, request }: Route.LoaderArgs) {
  return previewFor("abyss", params.phaseId, request);
}

export const clientLoader = noPreview;

export function meta({ matches, loaderData }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return previewMeta(loaderData, t("Spiral Abyss phase · GITV", "Сезон Бездны · GITV"), t("Spiral Abyss floor 12: enemies, HP, blessing.", "Витая Бездна, 12 этаж: враги, HP, благословение."));
}

export default function AbyssPhase({ params }: Route.ComponentProps) {
  return <AbyssPhasePage phaseId={params.phaseId} />;
}
