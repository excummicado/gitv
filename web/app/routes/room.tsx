import type { Route } from "./+types/room";
import { RoomPage } from "../room/RoomPage";
import { metaLang } from "../i18n";

export function meta({ matches }: Route.MetaArgs) {
  const t = (en: string, ru: string) => (metaLang(matches) === "ru" ? ru : en);
  return [{ title: t("Match of the day · GITV", "Матч дня · GITV") }, { name: "robots", content: "noindex" }];
}

export default function RoomRoute({ params }: Route.ComponentProps) {
  return <RoomPage roomId={params.roomId} />;
}
