import type { Route } from "./+types/characters";
import { CharactersPage } from "../character/CharactersPage";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [
    { title: t("Characters · GITV", "Персонажи · GITV") },
    { name: "description", content: t("Pick, ban and win rates of every character.", "Пикрейт, банрейт и винрейт всех персонажей.") },
  ];
}

export default function Characters() {
  return <CharactersPage />;
}
