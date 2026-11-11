// Bundle statistics (GET /api/v1/admin/bundles), for the super admin: computed offline by tools/bundle-stats.
// Whatever has too little data behind it is left out when the file is built (site_export.py), so everything here
// has at least "some" data.

import { authRequest } from "../auth/client";

export type AgentInfo = { name_en: string | null; name_ru: string | null; icon: string | null; rarity: number | null };
/** How much data stands behind a number: plenty, or enough to show. */
export type Volume = "high" | "mid";
/** One cell of a pair's constellation grid: its place (row * 7 + column; the row is the first character's
 * constellation), games, players, the whole effect, the pair's own part of it, and how much data it has. */
export type GridCell = [cell: number, games: number, players: number, whole: number, pair: number, volume: Volume];
export type Pair = {
  a: string; b: string; n: number; p: number; v: Volume; e: number; lo: number; hi: number; reliable: boolean;
  robust: boolean; wo3: number | null; cost: number | null; tier: number | null; grid: GridCell[];
};
/** A constellation level against the character's lowest level with enough games (its `e` is 0). */
export type Level = { n: number; p: number; v: Volume; e: number; cost: number | null } | null;
export type Team = {
  agents: string[]; n: number; p: number; v: Volume; e: number; lo: number; hi: number; cost: number | null; gain: number | null;
};
export type Bundle = {
  agents: (string | null)[]; names: string; cond_en: string; cond_ru: string; cost: number | null; n: number; p: number;
  v: Volume; e: number; lo: number; hi: number; reliable: boolean;
};
export type Inseparable = {
  a: string; b: string; kind: string; n: number; p: number; v: Volume; half: number; draft: number;
  e: number | null; lo: number | null; hi: number | null; cost: number | null;
};
export type BundleStats = {
  meta: {
    generated: string; from: string; to: string; games: number; players: number; pairs: number; robust: number;
    weight_cap: number; stability: number; hidden: { pairs: number; teams: number; bundles: number };
  };
  agents: Record<string, AgentInfo>;
  pairs: Pair[]; levels: Record<string, Level[]>; teams: Team[]; bundles: Bundle[]; inseparable: Inseparable[];
};

export function fetchBundleStats() {
  return authRequest<BundleStats>("GET", "/admin/bundles");
}
