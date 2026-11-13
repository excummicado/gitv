import type { Route } from "./+types/bets";
import { BetsPage } from "../bets/BetsPage";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [{ title: t("Bets · GITV", "Ставки · GITV") }, { name: "robots", content: "noindex" }];
}

export default function Bets() {
  return <BetsPage />;
}
