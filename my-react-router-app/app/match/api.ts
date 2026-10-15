// The public match endpoint (GET /api/v1/matches/{id}); shapes mirror api/app/routers/matches.py.

import { ApiError } from "../auth/client";

export type Character = { id: string; name: string; name_ru?: string | null; icon: string | null; rarity: number | null };
export type TeamMember = { character: Character; level: number | null; constellation: number; weapon: Character | null; weapon_level: number | null; refinement: number | null };
export type Result = "W" | "L" | "D" | "—";
export type GamePlayer = { slot: number; name: string; user_id: string | null; clear_time: number; adjusted_time: number; restarts: number; rooms: number[] | null; result: Result; team: TeamMember[] };
export type DraftMove = { seq: number; slot: number | null; type: string; character: Character | null; at: string | null; pick_s_left: number | null; reserve_s_left: number | null };
export type Game = {
  id: string; game_no: number; status: string; first_pick_slot: number | null; started_at: string | null; finished_at: string | null; url: string | null;
  technical: boolean; technical_reasons: string[]; winner_slot: number | null; players: GamePlayer[]; moves: DraftMove[];
};
export type Organizer = { id: string; name: string; played: boolean };
export type MatchSide = { name: string; user_id: string | null; games_won: number; total_time: number | null };
export type MatchDetail = {
  id: string; tournament_id: string; tournament: string; organizer: Organizer | null; created_at: string; system: string | null; mode: string | null; is_official: boolean;
  free_restarts: number | null; paid_restarts: number[]; sides: MatchSide[]; winner: number | null; technical: boolean; games: Game[];
};

export async function fetchMatch(id: string, signal?: AbortSignal): Promise<MatchDetail> {
  let response: Response;
  try {
    response = await fetch(`/api/v1/matches/${encodeURIComponent(id)}`, { signal });
  } catch (err) {
    if (signal?.aborted) throw err;
    throw new ApiError("Can't reach the server. Check that the API is running.");
  }
  if (response.status === 404) throw new ApiError("This match doesn't exist or hasn't been imported yet.", 404);
  if (!response.ok) throw new ApiError("Couldn't load the match. Try again.", response.status);
  return response.json();
}

export type MatchSummary = { id: string; tournament_id: string; tournament: string; created_at: string; sides: MatchSide[]; winner: number | null; technical: boolean; games: number };
export type MatchList = { items: MatchSummary[]; total: number };
export type TournamentItem = { id: string; title: string; organizer?: Organizer | null; matches: number; last_match: string | null };

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { signal });
  } catch (err) {
    if (signal?.aborted) throw err;
    throw new ApiError("Can't reach the server. Check that the API is running.");
  }
  if (!response.ok) throw new ApiError("Couldn't load the matches. Try again.", response.status);
  return response.json();
}

export function fetchMatches(params: { q?: string; tournament?: string; limit: number; offset: number }, signal?: AbortSignal) {
  const query = new URLSearchParams({ limit: String(params.limit), offset: String(params.offset) });
  if (params.q) query.set("q", params.q);
  if (params.tournament) query.set("tournament", params.tournament);
  return getJson<MatchList>(`/api/v1/matches?${query}`, signal);
}

export type Place = { place: number; player: Organizer };
export type TournamentGroup = { tournament: TournamentItem; places: Place[]; items: MatchSummary[] };
export type GroupedMatches = { groups: TournamentGroup[]; total: number; matches: number };

// Matches grouped by tournament, paged by tournament (limit = tournaments per page).
export function fetchMatchesByTournament(params: { q?: string; tournament?: string; limit: number; offset: number }, signal?: AbortSignal) {
  const query = new URLSearchParams({ limit: String(params.limit), offset: String(params.offset) });
  if (params.q) query.set("q", params.q);
  if (params.tournament) query.set("tournament", params.tournament);
  return getJson<GroupedMatches>(`/api/v1/matches/by-tournament?${query}`, signal);
}

export function fetchTournaments(signal?: AbortSignal) {
  return getJson<TournamentItem[]>("/api/v1/matches/tournaments", signal);
}

export type TopPick = {
  tournament: { id: string; title: string }; date: string;
  character: Character & { splash: string | null; card: string | null };
  picks: number; games: number; pick_rate: number | null; wins: number; winrate: number | null;
};

// The most picked character of the latest tournament (home page promo); null when there's no data.
export function fetchTopPick(signal?: AbortSignal) {
  return getJson<TopPick | null>("/api/v1/matches/top-pick", signal);
}

export type LiveTournament = { id: string; title: string; system: string | null; started_at: string | null; image: string | null; imported_matches: number };

// Tournaments running on the site now (refreshed by the API at most once a minute).
export function fetchLiveTournaments(signal?: AbortSignal) {
  return getJson<LiveTournament[]>("/api/v1/matches/live-tournaments", signal);
}
