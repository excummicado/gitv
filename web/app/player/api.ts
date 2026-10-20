// Public player endpoints (GET /api/v1/players, /api/v1/players/{id}); shapes mirror api/app/routers/players.py.

import { getJson, type Message } from "../api";
import type { Character } from "../match/api";
import type { PlayerInfo, ProfileChange } from "../suggestions/api";

export type PlayerSummary = {
  id: string; name: string; other_names: string[]; tournaments: number; matches: number; match_wins: number; match_winrate: number | null;
  games: number; wins: number; losses: number; draws: number; winrate: number | null; avg_time: number | null; best_time: number | null;
  tech_losses: number; tech_loss_rate: number | null; avg_restarts: number | null; last_played: string | null;
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
  // "challonge": from the tournament's bracket; "estimate": worked out from matches won
  place_source: "challonge" | "estimate" | null;
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
  first_pick: Split; second_pick: Split;
  times: { average: number | null; average_win: number | null; average_loss: number | null; average_first_pick: number | null; average_second_pick: number | null; best: number | null; best_match_id: string | null; counted_games: number };
  tournament_list: PlayedTournament[];
  tournament: string | null;
  profile: PlayerInfo | null;
  profile_history: ProfileChange[];
  finishes: Finish[];
  // Major tournaments won, newest first, whatever the shown scope
  major_titles: { tournament_id: string; title: string; date: string }[];
  match_list: PlayerMatch[];
  frequent_opponents: FrequentOpponent[];
};
export type FrequentOpponent = {
  player: { id: string; name: string }; matches: number; wins: number; losses: number; winrate: number | null; last_met: string;
  // Every match between them, newest first, scored from this player's side
  meetings: { match_id: string; date: string; tournament: string; games_won: number; games_lost: number; result: "W" | "L" | "D" | "—"; source: "challonge" | "technical" | "time" | null }[];
};

// "major": only Abyss Cup qualifiers and playoffs count.
export type Scope = "all" | "major";

export function fetchPlayers(signal?: AbortSignal, scope: Scope = "all") {
  return getJson<PlayerSummary[]>(`/api/v1/players?scope=${scope}`, { signal });
}

// tournament: limit the statistics to one tournament the player played (scope and since are then ignored).
// since (YYYY-MM-DD): count only tournaments that started on or after that day.
export function fetchPlayer(id: string, signal?: AbortSignal, scope: Scope = "all", tournament?: string, since?: string) {
  const notFound: Message = tournament ? ["This player didn't play that tournament.", "Игрок не участвовал в этом турнире."]
    : since ? ["No games in tournaments since that date.", "Нет игр в турнирах с этой даты."]
    : scope === "major" ? ["No games in major tournaments (Abyss Cup qualifiers and playoffs).", "Нет игр в мейджор-турнирах (квалификации и плей-офф Abyss Cup)."]
    : ["This player hasn't played an imported match.", "У игрока нет импортированных матчей."];
  const query = new URLSearchParams({ scope });
  if (tournament) query.set("tournament", tournament);
  else if (since) query.set("since", since);
  return getJson<PlayerDetail>(`/api/v1/players/${encodeURIComponent(id)}?${query}`, { signal, notFound });
}

export type Champion = { player: { id: string; name: string }; tournament: { id: string; title: string }; date: string; final_match_id: string };

// Winners of the latest tournaments, one entry per player (older tournaments fill in repeats).
export function fetchChampions(limit = 5, signal?: AbortSignal) {
  return getJson<Champion[]>(`/api/v1/players/champions?limit=${limit}`, { signal });
}

// The player's roster in a tournament: one entry per version (several when it changed mid-tournament).
export function fetchRosters(playerId: string, tournamentId: string, signal?: AbortSignal) {
  return getJson<RosterVersion[]>(`/api/v1/players/${encodeURIComponent(playerId)}/rosters/${encodeURIComponent(tournamentId)}`,
    { signal, notFound: ["No roster for this tournament.", "Нет ростера на этом турнире."] });
}

// Comparison (GET /api/v1/players/{a}/compare/{b}): both players' statistics and their meetings.
export type CompareSide = PlayerSummary & {
  most_picked: CharacterCount | null; most_banned_against: CharacterCount | null; highest_winrate_character: CharacterRate | null;
  highest_winstreak: number; current_winstreak: number; first_pick: Split; second_pick: Split; tech_loss_rate: number | null;
  times: PlayerDetail["times"]; last_games: LastGame[]; tournament_wins: number; finals: number; top_four: number;
  profile: PlayerInfo | null;
};
export type MeetingSide = {
  match_wins: number; match_winrate: number | null; game_wins: number; game_winrate: number | null;
  avg_time: number | null; best_time: number | null; best_match_id: string | null; tech_losses: number;
  first_pick: { wins: number; games: number }; second_pick: { wins: number; games: number };
  most_picked: CharacterCount[]; most_banned_by_opponent: CharacterCount[];
};
export type Meeting = {
  match_id: string; date: string; tournament: { id: string; title: string };
  games_won: number; games_lost: number; result: "W" | "L" | "D" | "—"; technical: boolean;
  source: "challonge" | "technical" | "time" | null;
};
export type Comparison = {
  // null: no games in the scope
  players: [CompareSide | null, CompareSide | null];
  head_to_head: {
    matches: Meeting[]; sides: [MeetingSide | null, MeetingSide | null]; draws: number; no_result: number;
    tournaments: number; streak: { player: string; matches: number } | null;
  };
};

export function fetchComparison(a: string, b: string, scope: Scope, signal?: AbortSignal) {
  return getJson<Comparison>(`/api/v1/players/${encodeURIComponent(a)}/compare/${encodeURIComponent(b)}?scope=${scope}`, {
    signal, notFound: ["One of the players hasn't played an imported match.", "Один из игроков не играл импортированных матчей."],
  });
}

// The home page rivalry: among the pairs who met most, the one closest to 50-50.
export type ElClasico = {
  players: [{ id: string; name: string }, { id: string; name: string }];
  meetings: number; match_wins: [number, number]; game_wins: [number, number]; draws: number; tournaments: number;
  last_met: string | null; recent: Meeting[]; streak: { player: string; matches: number } | null; candidates: number;
};

export function fetchElClasico(signal?: AbortSignal) {
  return getJson<ElClasico | null>("/api/v1/players/el-clasico", { signal });
}

// Every character ever in the player's roster (or one tournament's roster), with stats and constellation changes.
export type OwnedCharacter = {
  character: Character; constellation: number; level: number | null; previous_constellation: number | null;
  history: { constellation: number; date: string; tournament: { id: string; title: string } }[];
  tournaments: number; first_seen: string | null; picks: number; pick_rate: number | null; wins: number; losses: number;
  winrate: number | null; avg_time: number | null; best_time: number | null; banned_against: number; last_picked: string | null;
  // Every game it was picked in, newest first
  games: { match_id: string; game_no: number; date: string; tournament: string; opponent: { id: string; name: string };
    result: "W" | "L" | "D" | "—"; clear_time: number | null; technical: boolean; constellation: number | null }[];
};
export type CharacterRoster = {
  tournaments: { id: string; title: string; date: string; versions: number }[];
  tournament: string | null; games: number; characters: OwnedCharacter[];
};

export function fetchCharacterRoster(playerId: string, tournament?: string, signal?: AbortSignal) {
  const query = tournament ? `?tournament=${encodeURIComponent(tournament)}` : "";
  return getJson<CharacterRoster>(`/api/v1/players/${encodeURIComponent(playerId)}/characters${query}`, {
    signal, notFound: ["No roster for this tournament.", "Нет ростера на этом турнире."],
  });
}
