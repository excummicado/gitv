// The public match endpoint (GET /api/v1/matches/{id}); shapes mirror api/app/routers/matches.py.

import { getJson } from "../api";

export type Character = { id: string; name: string; name_ru?: string | null; icon: string | null; rarity: number | null };
export type TeamMember = { character: Character; level: number | null; constellation: number | null; weapon: Character | null; weapon_level: number | null; refinement: number | null };
export type Result = "W" | "L" | "D" | "—";
export type GamePlayer = { slot: number; name: string; user_id: string | null; clear_time: number; adjusted_time: number; restarts: number; rooms: number[] | null; result: Result; team: TeamMember[] };
export type DraftMove = { seq: number; slot: number | null; type: string; character: Character | null; at: string | null; pick_s_left: number | null; reserve_s_left: number | null };
export type Game = {
  id: string; game_no: number; status: string; first_pick_slot: number | null; started_at: string | null; finished_at: string | null; url: string | null;
  technical: boolean; technical_reasons: string[]; winner_slot: number | null; players: GamePlayer[]; moves: DraftMove[];
};
export type ResultSource = "challonge" | "technical" | "time" | null;
export type Organizer = { id: string; name: string; played: boolean };
export type MatchSide = { name: string; user_id: string | null; games_won: number; total_time: number | null };
export type MatchDetail = {
  id: string; tournament_id: string; tournament: string; organizer: Organizer | null; created_at: string; system: string | null; mode: string | null; is_official: boolean;
  free_restarts: number | null; paid_restarts: number[]; sides: MatchSide[]; winner: number | null; technical: boolean;
  // How the winner is known: the tournament's Challonge bracket, a technical defeat or the total time
  result_source: ResultSource; games: Game[];
  // A match of a tournament played only on Challonge: the result, no games
  challonge_only: boolean;
  // That bracket on Challonge; null for one entered by hand
  challonge_url: string | null;
  // The Abyss phase running on the match's day
  abyss_phase: number | null;
};

export function fetchMatch(id: string, signal?: AbortSignal) {
  return getJson<MatchDetail>(`/api/v1/matches/${encodeURIComponent(id)}`, {
    signal,
    notFound: ["This match doesn't exist or hasn't been imported yet.", "Такого матча нет или он ещё не импортирован."],
    failed: ["Couldn't load the match. Try again.", "Не удалось загрузить матч. Попробуйте ещё раз."],
  });
}

export type MatchSummary = { id: string; tournament_id: string; tournament: string; created_at: string; sides: MatchSide[]; winner: number | null; technical: boolean; result_source: ResultSource; games: number };
export type MatchList = { items: MatchSummary[]; total: number };
export type TournamentItem = { id: string; title: string; organizer?: Organizer | null; matches: number; last_match: string | null };

export function fetchMatches(params: { q?: string; tournament?: string; limit: number; offset: number }, signal?: AbortSignal) {
  const query = new URLSearchParams({ limit: String(params.limit), offset: String(params.offset) });
  if (params.q) query.set("q", params.q);
  if (params.tournament) query.set("tournament", params.tournament);
  return getJson<MatchList>(`/api/v1/matches?${query}`, { signal });
}

export type Place = { place: number; player: Organizer };
export type TournamentGroup = { tournament: TournamentItem; places: Place[]; items: MatchSummary[] };
export type GroupedMatches = { groups: TournamentGroup[]; total: number; matches: number };

// Matches grouped by tournament, paged by tournament (limit = tournaments per page).
export function fetchMatchesByTournament(params: { q?: string; tournament?: string; limit: number; offset: number }, signal?: AbortSignal) {
  const query = new URLSearchParams({ limit: String(params.limit), offset: String(params.offset) });
  if (params.q) query.set("q", params.q);
  if (params.tournament) query.set("tournament", params.tournament);
  return getJson<GroupedMatches>(`/api/v1/matches/by-tournament?${query}`, { signal });
}

export function fetchTournaments(signal?: AbortSignal) {
  return getJson<TournamentItem[]>("/api/v1/matches/tournaments", { signal });
}

export type TopPick = {
  tournament: { id: string; title: string }; date: string;
  character: Character & { splash: string | null; card: string | null };
  picks: number; games: number; pick_rate: number | null; wins: number; winrate: number | null;
};

export type PopularCharacters = {
  // null: over all tournaments
  tournament: { id: string; title: string } | null; tournaments: number; date: string; games: number;
  // The Abyss phase counted; current false: the one before, until a tournament has been played on the current one
  abyss: { id: number; version: string; starts_on: string; current: boolean } | null;
  // score = picks + bans; presence = % of games where it was picked or banned
  characters: { character: Character & { splash: string | null; card: string | null }; picks: number; bans: number; score: number; presence: number | null; pick_winrate: number | null; avg_constellation: number | null }[];
};

// The most popular characters of the current Abyss (picks and bans both count; see the API for when it's the one
// before); null without data.
export function fetchPopularCharacters(limit = 5, signal?: AbortSignal) {
  return getJson<PopularCharacters | null>(`/api/v1/matches/popular-characters?limit=${limit}&abyss=true`, { signal });
}

// The most picked character of the latest tournament (home page promo); null when there's no data.
export function fetchTopPick(signal?: AbortSignal) {
  return getJson<TopPick | null>("/api/v1/matches/top-pick", { signal });
}

export type LiveTournament = { id: string; title: string; system: string | null; started_at: string | null; image: string | null; imported_matches: number; discord: string | null };

// Tournaments running on the site now (the API asks the site for them at most once an hour).
export function fetchLiveTournaments(signal?: AbortSignal) {
  return getJson<LiveTournament[]>("/api/v1/matches/live-tournaments", { signal });
}

// A game's status is the site's: NOT_STARTED, FINISHED, or the draft or game under way; url opens its draft there.
export type LiveGame = { game_no: number; status: string; url: string | null };
export type LiveMatch = {
  id: string; tournament_id: string; tournament: string; created_at: string;
  players: { id: string | null; name: string }[]; games: LiveGame[];
  // One of its games is being drafted or played now
  started: boolean;
};

// Unfinished matches of the running tournaments (at most five minutes old), the ones being played first.
export function fetchLiveMatches(tournament?: string, signal?: AbortSignal) {
  const query = tournament ? `?tournament=${encodeURIComponent(tournament)}` : "";
  return getJson<LiveMatch[]>(`/api/v1/matches/live-matches${query}`, { signal });
}
