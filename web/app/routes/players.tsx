import type { Route } from "./+types/players";
import { PlayersPage } from "../player/PlayersPage";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [
    { title: t("Players · GITV", "Игроки · GITV") },
    { name: "description", content: t("Everyone who played an imported tournament match.", "Все, кто играл в матчах турниров.") },
  ];
}

export default function Players() {
  return <PlayersPage />;
}
