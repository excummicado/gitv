// Public player endpoints (GET /api/v1/players, /api/v1/players/{id}); shapes mirror api/app/routers/players.py.

import { ApiError } from "../auth/client";
import type { Character } from "../match/api";
import type { PlayerInfo, ProfileChange } from "../suggestions/api";

export type PlayerSummary = {
  id: string; name: string; other_names: string[]; tournaments: number; matches: number; match_wins: number; match_winrate: number | null;
  games: number; wins: number; losses: number; draws: number; winrate: number | null; avg_time: number | null; best_time: number | null;
  tech_losses: number; last_played: string | null;
};
export type CharacterCount = { character: Character; games: number };
export type CharacterRate = { character: Character; winrate: number | null; games: number };
export type Split = { wins: number; losses: number; winrate: number | null };
export type PlayerMatch = {
  match_id: string; date: string; tournament: string; opponent: { id: string; name: string } | null;
  games_won: number; games_lost: number; result: "W" | "L" | "D" | "—"; technical: boolean; avg_time: number | null;
};
export type LastGame = { result: "W" | "L" | "D"; match_id: string; game_no: number; date: string };
export type Finish = { tournament: { id: string; title: string }; date: string; place: number };
export type PlayedTournament = {
  id: string; title: string; date: string; matches: number; place: number | null;
  // Brackets: the place, or the tier shared with players who won as many matches, e.g. [5, 8]
  place_range: [number, number] | null;
  kind: "bracket" | "groups" | "qualifier"; wins: number; losses: number;
  qualification: "passed" | "failed" | "pending" | null; rosters: number;
};
export type RosterVersion = {
  version: number; games: number; first_seen: string; last_seen: string;
  // Sorted most expensive first by the tournament's draft system; cost is null when it doesn't list the item.
  characters: { character: Character; level: number | null; constellation: number; cost: number | null }[];
  weapons: { weapon: Character; level: number | null; refinement: number | null; count: number; cost: number | null }[];
};
export type PlayerDetail = PlayerSummary & {
  most_picked: CharacterCount | null; most_banned_against: CharacterCount | null;
  highest_winrate_character: CharacterRate | null; lowest_winrate_character: CharacterRate | null;
  highest_winstreak: number; current_winstreak: number; last_games: LastGame[];
  first_pick: Split; second_pick: Split; tech_loss_rate: number | null;
  times: { average: number | null; average_win: number | null; average_loss: number | null; average_first_pick: number | null; average_second_pick: number | null; best: number | null; best_match_id: string | null; counted_games: number };
  tournament_list: PlayedTournament[];
  tournament: string | null;
  profile: PlayerInfo | null;
  profile_history: ProfileChange[];
  finishes: Finish[];
  match_list: PlayerMatch[];
};

async function getJson<T>(path: string, notFound: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { signal });
  } catch (err) {
    if (signal?.aborted) throw err;
    throw new ApiError("Can't reach the server. Check that the API is running.");
  }
  if (response.status === 404) throw new ApiError(notFound, 404);
  if (!response.ok) throw new ApiError("Couldn't load the data. Try again.", response.status);
  return response.json();
}

// "major": only Abyss Cup qualifiers and playoffs count.
export type Scope = "all" | "major";

export function fetchPlayers(signal?: AbortSignal, scope: Scope = "all") {
  return getJson<PlayerSummary[]>(`/api/v1/players?scope=${scope}`, "No players found.", signal);
}

// tournament: limit the statistics to one tournament the player played (scope is then ignored).
export function fetchPlayer(id: string, signal?: AbortSignal, scope: Scope = "all", tournament?: string) {
  const notFound = tournament ? "This player didn't play that tournament."
    : scope === "major" ? "No games in major tournaments (Abyss Cup qualifiers and playoffs)." : "This player hasn't played an imported match.";
  const query = new URLSearchParams({ scope });
  if (tournament) query.set("tournament", tournament);
  return getJson<PlayerDetail>(`/api/v1/players/${encodeURIComponent(id)}?${query}`, notFound, signal);
}

export type Champion = { player: { id: string; name: string }; tournament: { id: string; title: string }; date: string; final_match_id: string };

// Winners of the latest tournaments, one entry per player (older tournaments fill in repeats).
export function fetchChampions(limit = 5, signal?: AbortSignal) {
  return getJson<Champion[]>(`/api/v1/players/champions?limit=${limit}`, "No champions yet.", signal);
}

// The player's roster in a tournament: one entry per version (several when it changed mid-tournament).
export function fetchRosters(playerId: string, tournamentId: string, signal?: AbortSignal) {
  return getJson<RosterVersion[]>(`/api/v1/players/${encodeURIComponent(playerId)}/rosters/${encodeURIComponent(tournamentId)}`,
    "No roster for this tournament.", signal);
}
