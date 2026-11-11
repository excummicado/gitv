// Bundle statistics (GET /api/v1/admin/bundles), for the super admin: computed offline by tools/bundle-stats.

import { authRequest } from "../auth/client";

export type AgentInfo = { name_en: string | null; name_ru: string | null; icon: string | null; rarity: number | null };
// 7×7 cells, row = the first character's constellation, column = the second's: games, players, the whole effect
// (both characters at those constellations plus the pair) and the pair's own part of it.
export type Grid = { n: number[]; p: number[]; t: (number | null)[]; s: (number | null)[] };
export type Pair = {
  a: string; b: string; n: number; p: number; e: number; lo: number; hi: number; reliable: boolean; robust: boolean;
  wo3: number | null; top3: number | null; cost: number | null; tier: number | null; grid: Grid;
};
export type Level = { n: number; p: number; e: number | null; lo: number | null; hi: number | null; cost: number | null } | null;
export type Team = {
  agents: string[]; n: number; p: number; top3: number | null; e: number; lo: number; hi: number;
  resid: number | null; cost: number | null; spp: number | null;
};
export type Bundle = {
  agents: (string | null)[]; names: string; cond_en: string; cond_ru: string; cost: number | null; n: number; p: number;
  e: number | null; lo: number | null; hi: number | null; status: string;
};
export type Inseparable = {
  a: string; b: string; kind: string; n: number; p: number; half: number; draft: number;
  e: number | null; lo: number | null; hi: number | null; cost: number | null;
};
export type BundleStats = {
  meta: {
    generated: string; from: string; to: string; games: number; players: number; pairs: number; robust: number;
    weight_cap: number; cells: { measured: number; thin: number; extrapolated: number }; stability: number;
  };
  agents: Record<string, AgentInfo>;
  pairs: Pair[]; levels: Record<string, Level[]>; teams: Team[]; bundles: Bundle[]; inseparable: Inseparable[];
};

export function fetchBundleStats() {
  return authRequest<BundleStats>("GET", "/admin/bundles");
}

// How much data stands behind a number: the page colors everything by this, not by the effect.
export type Volume = "high" | "mid" | "low" | "none";

/** A pair, a team or a constellation level: plenty of games by many players, a fair amount, or little. */
export function rowVolume(games: number, players: number): Volume {
  if (games === 0) return "none";
  if (games >= 100 && players >= 30) return "high";
  return games >= 30 && players >= 15 ? "mid" : "low";
}

/** One cell of a pair's constellation grid, where games are far fewer; no games at all is the model's guess. */
export function cellVolume(games: number, players: number): Volume {
  if (games === 0) return "none";
  if (games >= 50 && players >= 15) return "high";
  return games >= 20 && players >= 5 ? "mid" : "low";
}
