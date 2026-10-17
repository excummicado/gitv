import type { Route } from "./+types/compare";
import { ComparePage } from "../player/ComparePage";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [
    { title: t("Compare players · GITV", "Сравнение игроков · GITV") },
    { name: "description", content: t("Two players' statistics side by side and their head-to-head record.", "Статистика двух игроков рядом и их личные встречи.") },
  ];
}

export default function Compare({ params }: Route.ComponentProps) {
  return <ComparePage playerId={params.playerId} otherId={params.otherId} />;
}
