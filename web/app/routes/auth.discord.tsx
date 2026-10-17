import type { Route } from "./+types/auth.discord";
import { DiscordCallback } from "../auth/DiscordCallback";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [{ title: t("GITV · Discord sign-in", "GITV · Вход через Discord") }];
}

export default function DiscordCallbackPage() {
  return <DiscordCallback />;
}
