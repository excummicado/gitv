import type { Route } from "./+types/home";
import { Welcome } from "../home/welcome";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [
    { title: t("GITV · Layout & Font Comparison", "GITV") },
    { name: "description", content: t("A static GITV sports portal layout and serif font comparison.", "GITV: турниры, матчи и игроки Abyss.") },
  ];
}

export default function Home() {
  return <Welcome />;
}
