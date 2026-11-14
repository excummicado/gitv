// Matches of the day (api/app/routers/schedule.py): read by anyone, added by event organizers and admins.

import { getJson } from "../api";
import { authRequest } from "../auth/client";

// elo: their Elo when they're a player of the site; elo_active: played in the last six months
export type ScheduledPlayer = {
  id: string | null; name: string; elo?: number | null; elo_active?: boolean; elo_rank?: number | null; elo_tier?: string | null;
  // A team event's team: its players, from the stream's post
  members?: ScheduledPlayer[];
};
// How the bets on a match stand (api/app/services/bets.py): open: bets are taken; no_elo: never were; started: waits
// for its result; settled; void: bets returned. Everyone sees the odds; bet testers bet.
export type BetState = "open" | "no_elo" | "started" | "settled" | "void" | "none";
// The odds on the two players; null when no bets are taken on the match
export type Odds = [number, number] | null;
export type ScheduledMatch = {
  id: number; tournament_id: string | null; tournament_title: string;
  player1: ScheduledPlayer; player2: ScheduledPlayer; starts_at: string; added_by: string;
  odds?: Odds; bets?: BetState;
};
export type ScheduledInput = {
  tournament_id: string | null; tournament_title: string; player1: ScheduledPlayer; player2: ScheduledPlayer; starts_at: string;
};

// Matches starting in [from, to): pass the viewer's local day (or days) as dates.
export function listScheduled(from: Date, to: Date, signal?: AbortSignal) {
  const query = new URLSearchParams({ from: from.toISOString(), to: to.toISOString() });
  return getJson<ScheduledMatch[]>(`/api/v1/schedule?${query}`, {
    signal, failed: ["Couldn't load the matches of the day.", "Не удалось загрузить матчи дня."],
  });
}

// Each stream's matches of a day (Abyss Cup, House of the Hearth), from its Telegram channel, and whether it's on
// (api/app/services/stream.py).
export type StreamMatch = {
  // stage: in the tournament's bracket, as api/app/services/stream.py bracket_stage codes it ("final", "lower:2", ...)
  // id: its room's key (/room/<id>)
  id: string; odds?: Odds; bets?: BetState;
  tournament_title: string; stage: string | null; player1: ScheduledPlayer; player2: ScheduledPlayer;
  announced_at: string; starts_at: string | null; live_at: string | null; casters: string | null; finished_at: string | null; winner: 0 | 1 | null; live: boolean; post_url: string;
};
export type StreamDay = {
  name: string; url: string; live: boolean; title: string | null; viewers: number | null; started_at: string | null; casters: string | null;
  matches: StreamMatch[];
};

// A stream on air now, by Twitch (GET /api/v1/schedule/live-streams); name is its tournaments' organizer
export type LiveStream = { name: string; channel: string; title: string | null; viewers: number | null; started_at: string | null };

export function fetchLiveStreams(signal?: AbortSignal) {
  return getJson<LiveStream[]>("/api/v1/schedule/live-streams", { signal });
}

export function streamMatches(from: Date, to: Date, signal?: AbortSignal) {
  const query = new URLSearchParams({ from: from.toISOString(), to: to.toISOString() });
  return getJson<StreamDay[]>(`/api/v1/schedule/stream?${query}`, {
    signal, failed: ["Couldn't load the stream.", "Не удалось загрузить стрим."],
  });
}

export function scheduleTournaments() {
  return authRequest<{ id: string; title: string }[]>("GET", "/schedule/tournaments");
}

export function addScheduled(input: ScheduledInput) {
  return authRequest<ScheduledMatch>("POST", "/schedule", input);
}

export function deleteScheduled(id: number) {
  return authRequest<null>("DELETE", `/schedule/${id}`);
}

// The local day containing `date`, as [start, next day's start).
export function localDay(date = new Date()): [Date, Date] {
  const start = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  return [start, new Date(start.getFullYear(), start.getMonth(), start.getDate() + 1)];
}

// A match of the day's room (GET /api/v1/schedule/rooms/{key}): an announced match's key is its number, a stream
// match's its id, an unfinished tournament match's "live-<id>". roster: the tournament whose roster of the player to show (this match's, else their latest).
export type RoomPlayer = ScheduledPlayer & { odds: number | null; stake: number; roster: { id: string; title: string } | null };
export type Room = {
  id: string; kind: "scheduled" | "stream" | "live"; tournament_id: string | null; tournament_title: string; stage: string | null;
  starts_at: string | null; announced_at: string | null; live_at: string | null; finished_at: string | null; live: boolean;
  winner: 0 | 1 | null; casters: string | null; stream_name: string | null; stream_url: string | null; post_url: string | null;
  players: [RoomPlayer, RoomPlayer]; bets: BetState;
  // A live match's games, with the links to watch their drafts
  games: { game_no: number; status: string; url: string | null }[];
};

export function fetchRoom(key: string, signal?: AbortSignal) {
  return getJson<Room>(`/api/v1/schedule/rooms/${encodeURIComponent(key)}`, {
    signal, notFound: ["There's no such match of the day.", "Такого матча дня нет."], failed: ["Couldn't load the match.", "Не удалось загрузить матч."],
  });
}

export function roomPath(key: string | number) {
  return `/room/${encodeURIComponent(String(key))}`;
}

// An unfinished match of a running tournament (match/api.ts LiveMatch) has a room too, without bets (key "live-<id>").
export function liveRoomPath(matchId: string) {
  return roomPath(`live-${matchId}`);
}

// A stream match's stage from its bracket code (api/app/services/stream.py bracket_stage).
const STAGES: Record<string, [string, string]> = {
  final: ["Final", "Финал"], semifinal: ["Semifinal", "Полуфинал"], quarterfinal: ["Quarterfinal", "Четвертьфинал"],
  grand_final: ["Grand final", "Гранд-финал"], upper_final: ["Upper final", "Финал верхней сетки"],
  upper_semifinal: ["Upper semifinal", "Полуфинал верхней сетки"], lower_final: ["Lower final", "Финал нижней сетки"],
  third_place: ["Third place match", "Матч за 3-е место"],
};

export function stageLabel(code: string, t: (en: string, ru: string) => string) {
  if (STAGES[code]) return t(...STAGES[code]);
  const [kind, value] = code.split(":");
  switch (kind) {
    case "of": return t(`Round of ${Number(value) * 2}`, `1/${value} финала`);
    case "upper": return t(`Upper bracket, round ${value}`, `Верхняя сетка, раунд ${value}`);
    case "lower": return t(`Lower bracket, round ${value}`, `Нижняя сетка, раунд ${value}`);
    case "group": return value ? t(`Group ${value}`, `Группа ${value}`) : t("Groups", "Группы");
    case "round": return t(`Round ${value}`, `Раунд ${value}`);
    default: return code;
  }
}
