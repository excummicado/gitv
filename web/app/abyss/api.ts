// Spiral Abyss phases, floor 12 (api/app/routers/abyss.py); data from alioth.wiki, icons © HoYoverse.

import { getJson } from "../api";

export type Text = { en: string; ru: string | null };
export type Resistance = { elements: string[]; value: string };
// An elemental shield (strength in units), one broken by a number of hits, or one with its own HP.
export type Shield = { element: string | null; units: string | null; hits: number | null; hp: number | null };
export type AbyssMonster = {
  id: number; name: string; element: string | null; icon: string | null; hp: number; count: number;
  resistances: Resistance[]; shields: Shield[];
};
export type Wave = { label: string; monsters: AbyssMonster[] };
export type Chamber = { index: number; half: number; level: number | null; hp: number; waves: Wave[] };
export type Guide = { monster: string; icon: string | null; mechanics: { title: Text; lines: Text[] }[] };
export type PhaseSummary = {
  id: number; version: string; starts_on: string; ends_on: string; current: boolean; upcoming: boolean; hp_ratio: number | null;
  total_hp: number | null; blessings: string[]; bosses: AbyssMonster[]; matches: number; tournaments: number;
};
export type PhaseDetail = PhaseSummary & {
  blessing_list: { name: string; desc: Text }[]; disorder: Text[]; chambers: Chamber[]; guides: Guide[];
  tournament_list: { id: string; title: string; matches: number; estimated: boolean }[];
  median_time: number | null; games: number;
};
// A phase a tournament's matches were played on (part of the tournament page's data).
export type TournamentAbyss = {
  id: number; version: string; starts_on: string; ends_on: string; matches: number; hp_ratio: number | null;
  total_hp: number | null; blessings: string[]; disorder: Text[]; bosses: AbyssMonster[]; estimated: boolean;
};

export function fetchPhases(signal?: AbortSignal) {
  return getJson<PhaseSummary[]>("/api/v1/abyss", { signal });
}

export function fetchPhase(id: string, signal?: AbortSignal) {
  return getJson<PhaseDetail>(id === "current" ? "/api/v1/abyss/current" : `/api/v1/abyss/${encodeURIComponent(id)}`, {
    signal, notFound: ["This Abyss phase isn't in the archive.", "Такого сезона Бездны нет в архиве."],
  });
}
