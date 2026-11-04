// Matches of the day (api/app/routers/schedule.py): read by anyone, added by event organizers and admins.

import { getJson } from "../api";
import { authRequest } from "../auth/client";

// elo: their Elo when they're a player of the site; elo_active: played in the last six months
export type ScheduledPlayer = {
  id: string | null; name: string; elo?: number | null; elo_active?: boolean; elo_rank?: number | null; elo_tier?: string | null;
  // A team event's team: its players, from the stream's post
  members?: ScheduledPlayer[];
};
export type ScheduledMatch = {
  id: number; tournament_id: string | null; tournament_title: string;
  player1: ScheduledPlayer; player2: ScheduledPlayer; starts_at: string; added_by: string;
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
