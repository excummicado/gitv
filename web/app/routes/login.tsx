import type { Route } from "./+types/login";
import { Login } from "../login/login";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [
    { title: t("GITV · Sign In", "GITV · Вход") },
    { name: "description", content: t("Sign in to your GITV account.", "Вход в аккаунт GITV.") },
  ];
}

export default function LoginPage() {
  return <Login />;
}
