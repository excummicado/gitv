import type { ReactNode } from "react";
import type { useLang } from "../i18n";

// What the player page and its tabs share: the stat boxes and a few formatters.

export const GAMES: [[string, string], [string, string, string]] = [["game", "games"], ["игра", "игры", "игр"]];
export const PLACE_LABELS: [string, string][] = [["1st", "1-е"], ["2nd", "2-е"], ["3rd", "3-е"], ["4th", "4-е"]];

export type L = ReturnType<typeof useLang>;

export function StatRow({ label, value }: { label: string; value: ReactNode }) {
  return <div className="player-stat-row"><span className="player-label">{label}</span><strong className="player-value">{value}</strong></div>;
}

export function StatBox({ title, children }: { title: string; children: ReactNode }) {
  return <section className="player-box"><h2 className="player-box-title">{title}</h2>{children}</section>;
}

export function StatRows({ rows }: { rows: [string, ReactNode][] }) {
  return <div className="player-box-body">{rows.map(([label, value]) => <StatRow key={label} label={label} value={value} />)}</div>;
}

export function seconds(l: L, value: number | null) {
  return value == null ? "—" : `${value}${l.t("s", "с")}`;
}

export function resultLetter(l: L, result: string) {
  return result === "W" ? l.t("W", "В") : result === "L" ? l.t("L", "П") : result === "D" ? l.t("D", "Н") : "–";
}
