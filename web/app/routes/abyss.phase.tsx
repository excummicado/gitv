import type { Route } from "./+types/abyss.phase";
import { AbyssPhasePage } from "../abyss/AbyssPages";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [{ title: t("Spiral Abyss phase · GITV", "Сезон Бездны · GITV") }];
}

export default function AbyssPhase({ params }: Route.ComponentProps) {
  return <AbyssPhasePage phaseId={params.phaseId} />;
}
