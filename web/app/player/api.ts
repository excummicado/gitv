// Public player endpoints (GET /api/v1/players, /api/v1/players/{id}); shapes mirror api/app/routers/players.py.

import { getJson, type Message } from "../api";
import type { Character } from "../match/api";

export type PlayerSummary = {
  id: string; name: string; other_names: string[]; tournaments: number; matches: number; match_wins: number; match_winrate: number | null;
  games: number; wins: number; losses: number; draws: number; winrate: number | null; avg_time: number | null; best_time: number | null;
  tech_losses: number; tech_loss_rate: number | null; avg_restarts: number | null; last_played: string | null;
  // From all tournaments; inactive (no match in six months) players keep it but have no rank
  elo: { rating: number; peak: number; peak_at: string; active: boolean; rank: number | null; rank_all: number; tier: string | null; tier_all: string | null } | null;
};
export type CharacterCount = { character: Character; games: number };
export type CharacterRate = { character: Character; winrate: number | null; games: number };
export type Split = { wins: number; losses: number; winrate: number | null };
export type PlayerMatch = {
  match_id: string; date: string; tournament: string; opponent: { id: string; name: string } | null;
  games_won: number; games_lost: number; result: "W" | "L" | "D" | "—"; technical: boolean; avg_time: number | null;
  // What the match did to the player's Elo and why (api/app/services/stats/elo.py); null when it isn't rated
  elo: EloChange | null;
};
export type EloChange = {
  change: number; before: number; after: number; opponent_before: number;
  score: number; expected: number; k: number; weight: number; kind: "major" | "series" | "fast" | "other";
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

// "major": only Abyss Cup qualifiers and playoffs and House of the Hearth's Abyss Fight Club count.
export type Scope = "all" | "major";

export function fetchPlayers(signal?: AbortSignal, scope: Scope = "all") {
  return getJson<PlayerSummary[]>(`/api/v1/players?scope=${scope}`, { signal });
}

// tournament: limit the statistics to one tournament the player played (scope and since are then ignored).
// since (YYYY-MM-DD): count only tournaments that started on or after that day.
export function fetchPlayer(id: string, signal?: AbortSignal, scope: Scope = "all", tournament?: string, since?: string) {
  const notFound: Message = tournament ? ["This player didn't play that tournament.", "Игрок не участвовал в этом турнире."]
    : since ? ["No games in tournaments since that date.", "Нет игр в турнирах с этой даты."]
    : scope === "major" ? ["No games in major tournaments (Abyss Cup qualifiers and playoffs, Abyss Fight Club).", "Нет игр в мейджор-турнирах (квалификации и плей-офф Abyss Cup, Abyss Fight Club)."]
    : ["This player hasn't played an imported match.", "У игрока нет импортированных матчей."];
  const query = new URLSearchParams({ scope });
  if (tournament) query.set("tournament", tournament);
  else if (since) query.set("since", since);
  return getJson<PlayerDetail>(`/api/v1/players/${encodeURIComponent(id)}?${query}`, { signal, notFound });
}

export type Champion = { player: { id: string; name: string }; tournament: { id: string; title: string }; date: string; final_match_id: string; elo: PlayerSummary["elo"] };

// Winners of the latest tournaments, one entry per player (older tournaments fill in repeats).
export function fetchChampions(limit = 5, signal?: AbortSignal) {
  return getJson<Champion[]>(`/api/v1/players/champions?limit=${limit}`, { signal });
}

// The player's roster in a tournament: one entry per version (several when it changed mid-tournament).
export function fetchRosters(playerId: string, tournamentId: string, signal?: AbortSignal) {
  return getJson<RosterVersion[]>(`/api/v1/players/${encodeURIComponent(playerId)}/rosters/${encodeURIComponent(tournamentId)}`,
    { signal, notFound: ["No roster for this tournament.", "Нет ростера на этом турнире."] });
}

// A player's Elo after each rated match (GET /api/v1/players/{id}/elo), for the chart on their page.
export type EloPoint = {
  date: string; elo: number; change: number; result: number; opponent: { id: string; name: string }; tournament: string; match_id: string | null;
};
export type EloHistory = { elo: NonNullable<PlayerSummary["elo"]>; points: EloPoint[] };

export function fetchEloHistory(playerId: string, signal?: AbortSignal) {
  return getJson<EloHistory>(`/api/v1/players/${encodeURIComponent(playerId)}/elo`, { signal, notFound: ["No rated matches.", "Нет рейтинговых матчей."] });
}

// Comparison (GET /api/v1/players/{a}/compare/{b}): both players' statistics and their meetings.
export type CompareSide = PlayerSummary & {
  most_picked: CharacterCount | null; most_banned_against: CharacterCount | null; highest_winrate_character: CharacterRate | null;
  highest_winstreak: number; current_winstreak: number; first_pick: Split; second_pick: Split; tech_loss_rate: number | null;
  times: PlayerDetail["times"]; last_games: LastGame[]; tournament_wins: number; finals: number; top_four: number;
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

// A nickname reduced to compare spellings: lower case, letters and digits only, trailing digits dropped
// ("Rpyt02", "rpyt" and "R_pyt" all become "rpyt"; a nick of digits only keeps them).
function nickKey(name: string) {
  const plain = name.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
  return plain.replace(/\d+$/, "") || plain;
}

function editDistance(a: string, b: string) {
  let row = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const next = [i];
    for (let j = 1; j <= b.length; j++) next[j] = Math.min(row[j] + 1, next[j - 1] + 1, row[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    row = next;
  }
  return row[b.length];
}

// Other nicknames worth showing next to the name: spellings of the same nick (case, digits, decorations, a letter
// or two, a longer or shorter form) are left out, as are spellings of a nick already seen.
export function distinctNames(name: string, others: string[]) {
  const seen = [nickKey(name)];
  const shown: string[] = [];
  for (const other of others) {
    const a = nickKey(other);
    const similar = !a || seen.some((b) => {
      if (a === b) return true;
      const [short, long] = a.length <= b.length ? [a, b] : [b, a];
      if (short.length >= 4 && long.includes(short)) return true;
      return editDistance(a, b) <= (short.length >= 8 ? 2 : short.length >= 4 ? 1 : 0);
    });
    if (!similar) shown.push(other);
    seen.push(a);
  }
  return shown;
}
