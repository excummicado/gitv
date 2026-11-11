import type { Route } from "./+types/bundles";
import { BundlesPage } from "../bundles/BundlesPage";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [{ title: t("Bundles · GITV", "Связки · GITV") }, { name: "robots", content: "noindex" }];
}

export default function Bundles() {
  return <BundlesPage />;
}
