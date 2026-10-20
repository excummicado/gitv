// Tournaments (api/app/routers/tournaments.py); shapes mirror the API's.

import { getJson } from "../api";
import type { Character, Organizer } from "../match/api";

export type TournamentKind = "bracket" | "groups" | "qualifier" | "team";
export type PlayerRef = { id: string; name: string };
export type TournamentRow = {
  id: string; title: string; kind: TournamentKind; major: boolean; organizer: Organizer | null;
  system: string | null; prize: number | null; currency: string | null; challonge_url: string | null;
  first_match: string | null; last_match: string | null; matches: number; players: number;
  winner: PlayerRef | null; places_source: "challonge" | "matches" | null;
  // Played only on Challonge (matches and places, no games or drafts); its date is then usually an estimate
  challonge_only: boolean; date_estimated: boolean;
  // The event this tournament is a stage of (Abyss Fight Club 4, an Abyss Cup season)
  event: EventRef | null;
};
export type EventRef = { id: string; title: string; stage: string; position: number; stages: number };
export type StageRef = { id: string; title: string; kind: TournamentKind; first_match: string | null; last_match: string | null };
export type TableRow = {
  // id null: a Challonge name not matched to anyone on the site
  player: { id: string | null; name: string }; place: [number, number] | null; place_source: "challonge" | "estimate" | null;
  match_wins: number; match_losses: number; match_draws: number; games_won: number; games_lost: number;
  tech_losses: number; avg_time: number | null; best_time: number | null; qualification: "passed" | "failed" | "pending" | null;
};
export type TournamentStats = {
  games: number; decided_games: number; technical_games: number; avg_time: number | null;
  fastest: { player: PlayerRef; time: number; match_id: string } | null;
  picks: { character: Character; picks: number; pick_rate: number | null; winrate: number | null }[];
  bans: { character: Character; bans: number; ban_rate: number | null }[];
};
export type BracketSide = { name: string; id: string | null; challonge_name: string };
export type BracketMatch = { player1: BracketSide | null; player2: BracketSide | null; scores: number[]; winner: 1 | 2 | null };
// round: 1, 2, ... main bracket; negative: losers' bracket; 0: third-place match
export type BracketRound = { round: number; matches: BracketMatch[] };
export type TournamentDetail = TournamentRow & { stages: StageRef[]; table: TableRow[]; stats: TournamentStats; bracket: BracketRound[] | null; unmatched: string[] };

export function fetchTournamentList(signal?: AbortSignal) {
  return getJson<TournamentRow[]>("/api/v1/tournaments", { signal });
}

export function fetchTournament(id: string, signal?: AbortSignal) {
  return getJson<TournamentDetail>(`/api/v1/tournaments/${encodeURIComponent(id)}`, {
    signal, notFound: ["This tournament doesn't exist or hasn't been imported yet.", "Такого турнира нет или он ещё не импортирован."],
  });
}

// The home page banner: the newest running tournament, else the latest finished one.
export type FeaturedTournament = {
  id: string; title: string; image: string | null; live: boolean; imported: boolean; date: string | null;
  matches: number; players: number; winner: PlayerRef | null; organizer: Organizer | null;
};

export function fetchFeaturedTournament(signal?: AbortSignal) {
  return getJson<FeaturedTournament | null>("/api/v1/tournaments/featured", { signal });
}
