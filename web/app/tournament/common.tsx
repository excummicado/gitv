import { useLang } from "../i18n";
import type { TournamentKind } from "./api";

export const KIND_LABELS: Record<TournamentKind, [string, string]> = {
  bracket: ["Bracket", "Сетка"], groups: ["Groups", "Группы"], qualifier: ["Qualifier", "Квалификация"], team: ["2x2", "2x2"],
};

export function Prize({ prize, currency }: { prize: number | null; currency: string | null }) {
  const { locale } = useLang();
  if (!prize) return null;
  return <>{prize.toLocaleString(locale)}{currency ? ` ${currency}` : ""}</>;
}

// "05/10/2026" or "03/10/2026 – 05/10/2026".
export function DateRange({ first, last }: { first: string | null; last: string | null }) {
  const { date } = useLang();
  if (!first || !last) return <>—</>;
  return <>{date(first)}{first.slice(0, 10) !== last.slice(0, 10) ? ` – ${date(last)}` : ""}</>;
}
