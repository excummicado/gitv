import type { Route } from "./+types/abyss";
import { AbyssPage } from "../abyss/AbyssPages";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [
    { title: t("Spiral Abyss · GITV", "Витая Бездна · GITV") },
    { name: "description", content: t("The Spiral Abyss floor 12 now and in every phase: enemies, HP, moon blessings and the tournaments played on it.", "12 этаж Витой Бездны сейчас и во всех сезонах: враги, HP, благословения луны и турниры на нём.") },
  ];
}

export default function Abyss() {
  return <AbyssPage />;
}
