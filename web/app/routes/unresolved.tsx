import type { Route } from "./+types/unresolved";
import { UnresolvedPage } from "../unresolved/UnresolvedPage";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [{ title: t("Matches without a result · GITV", "Матчи без результата · GITV") }, { name: "robots", content: "noindex" }];
}

export default function Unresolved() {
  return <UnresolvedPage />;
}
