import type { Route } from "./+types/schedule";
import { SchedulePage } from "../schedule/SchedulePage";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [{ title: t("Schedule · GITV", "Расписание · GITV") }];
}

export default function Schedule() {
  return <SchedulePage />;
}
