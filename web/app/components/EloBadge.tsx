import { useLang } from "../i18n";
import "./elo.css";

// A player's Elo in a frame, wherever it's shown, coloured by its tier from the API (stats/elo.py): the top three
// active players gold, silver and bronze, the rest of the top ten red and down to the thirtieth FACEIT orange,
// whoever is level with a tier's last place included;
// an inactive player's (no match in six months) is muted.
// dormant: an inactive player ranked with everyone (the players list's "inactive players too"): coloured by
// that rank, with a dashed frame.
export function EloBadge({ rating, rank, tier, active = true, dormant = false, className = "" }: { rating: number; rank?: number | null; tier?: string | null; active?: boolean; dormant?: boolean; className?: string }) {
  const { t } = useLang();
  const medal = active ? tier : null;
  const title = !active ? t("Elo · inactive: no match in six months", "Эло · неактивен: нет матчей полгода")
    : rank != null ? t(`Elo · #${rank} among active players`, `Эло · #${rank} среди активных`) : t("Elo", "Эло");
  return <span className={`gitv-elo${medal ? ` is-${medal}` : ""}${active ? "" : " is-inactive"}${dormant ? " is-dormant" : ""} ${className}`} title={dormant ? t("Elo · inactive: no match in six months", "Эло · неактивен: нет матчей полгода") : title}>{rating}</span>;
}
