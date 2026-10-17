import type { Route } from "./+types/home";
import { Welcome } from "../home/welcome";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [
    { title: t("GITV Main page", "GITV Главная") },
    { name: "description", content: t("GITV: Abyss tournaments, matches and players.", "GITV: турниры, матчи и игроки Abyss.") },
  ];
}

export default function Home() {
  return <Welcome />;
}
