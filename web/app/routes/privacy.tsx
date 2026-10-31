import type { Route } from "./+types/privacy";
import { PrivacyPage } from "../privacy/PrivacyPage";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [
    { title: t("Privacy · GITV", "Конфиденциальность · GITV") },
    { name: "description", content: t("What GITV keeps about visitors and members.", "Что GITV хранит о посетителях и участниках.") },
  ];
}

export default function Privacy() {
  return <PrivacyPage />;
}
