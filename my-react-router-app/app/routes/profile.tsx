import type { Route } from "./+types/profile";
import { ProfilePage } from "../profile/ProfilePage";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [{ title: t("Your profile · GITV", "Ваш профиль · GITV") }];
}

export default function Profile() {
  return <ProfilePage />;
}
