// Characters across all imported games (api/app/routers/characters.py).

import { getJson } from "../api";
import type { Character } from "../match/api";
import type { Scope } from "../player/api";

export type CharacterRow = {
  character: Character; picks: number; pick_rate: number | null; bans: number; ban_rate: number | null; presence: number | null;
  wins: number; losses: number; winrate: number | null; avg_constellation: number | null; avg_time: number | null; players: number;
  top_player: { id: string; name: string; picks: number; winrate: number | null } | null;
};
export type OrganizerOption = { id: string; name: string; tournaments: number; excluded: boolean };
export type CharacterTable = { games: number; teams: number; tournaments: number; prize_players: number; organizers: OrganizerOption[]; characters: CharacterRow[] };

// Prize winners: players who ever finished in a top four.
// "players": only their picks, bans and games; "versus": only games between two of them.
export type PrizeFilter = "" | "players" | "versus";

export type TableFilters = { scope: Scope; since?: string; exclude: string[]; prize?: PrizeFilter; constellations?: [number, number] };

// constellations: [lowest, highest] picks to count (bans don't have one and always count).
function filterQuery(options: TableFilters) {
  const query = new URLSearchParams({ scope: options.scope });
  if (options.constellations) {
    query.set("cons_min", String(options.constellations[0]));
    query.set("cons_max", String(options.constellations[1]));
  }
  if (options.since) query.set("since", options.since);
  for (const id of options.exclude) query.append("exclude", id);
  if (options.prize) query.set("prize", options.prize);
  return query;
}

export type CharacterPlayer = {
  player: { id: string; name: string }; picks: number; wins: number; losses: number; winrate: number | null;
  min_constellation: number; max_constellation: number; last_constellation: number; first: string; last: string;
};

// Who picked the character and when, under the same filters as the table; most picks first.
export function fetchCharacterPlayers(agentId: string, options: TableFilters, signal?: AbortSignal) {
  return getJson<CharacterPlayer[]>(`/api/v1/characters/${encodeURIComponent(agentId)}/players?${filterQuery(options)}`, { signal });
}

export type ConstellationRow = {
  constellation: number; picks: number; share: number | null; wins: number; losses: number;
  winrate: number | null; avg_time: number | null; players: number;
  // Games where a player had it at this constellation, and where the opponent banned it there
  owned_games: number; banned_games: number; ban_rate: number | null;
};

// The character's picks and winrate at each constellation, C0 to C6, under the table's filters.
export function fetchCharacterConstellations(agentId: string, options: TableFilters, signal?: AbortSignal) {
  const query = filterQuery({ ...options, constellations: undefined });
  return getJson<ConstellationRow[]>(`/api/v1/characters/${encodeURIComponent(agentId)}/constellations?${query}`, { signal });
}

export function fetchCharacterTable(options: TableFilters, signal?: AbortSignal) {
  const query = filterQuery(options);
  return getJson<CharacterTable>(`/api/v1/characters?${query}`, { signal });
}
