import type { Route } from "./+types/articles.post";
import { ArticlePage } from "../articles/ArticlesPage";
import { metaLang } from "../i18n";
import { noPreview, previewMeta } from "../preview";
import { previewFor } from "../preview.server";

export async function loader({ params, request }: Route.LoaderArgs) {
  return previewFor("article", params.articleId, request);
}

export const clientLoader = noPreview;

export function meta({ matches, loaderData }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return previewMeta(loaderData, t("Article · GITV", "Статья · GITV"), t("A GITV article.", "Статья GITV."));
}

export default function Article() {
  return <ArticlePage />;
}
