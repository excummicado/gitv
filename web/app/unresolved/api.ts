// Matches without a result in the tournaments the signed-in organizer or admin runs (GET /api/v1/matches/unresolved).

import { authRequest } from "../auth/client";

// bracket: a running tournament waits for its Challonge bracket; tournament_end: one without a bracket holds a
// technical defeat until it ends; both_technical, no_time, unclear: only a winner set by hand settles it.
export type UnresolvedReason = "bracket" | "tournament_end" | "both_technical" | "no_time" | "unclear";
export type UnresolvedMatch = {
  id: string; tournament_id: string; tournament: string; created_at: string; sides: string[];
  reason: UnresolvedReason; waiting: boolean;
};

// Kept for a minute, so the menu's counter doesn't ask again on every page.
let kept: { at: number; rows: Promise<UnresolvedMatch[]> } | null = null;

export function fetchUnresolved(fresh = false): Promise<UnresolvedMatch[]> {
  if (fresh || !kept || Date.now() - kept.at > 60_000) {
    const rows = authRequest<UnresolvedMatch[]>("GET", "/matches/unresolved");
    kept = { at: Date.now(), rows };
    rows.catch(() => { kept = null; });
  }
  return kept.rows;
}

// Streams' nicknames no player is found for, with suggested players (admins only; GET /api/v1/schedule/stream-names).
export type NameCandidate = { id: string; name: string; likeness: number; matches: number; last_played: string | null; rating: number | null };
export type StreamName = {
  name: string; matches: number; last_seen: string;
  appearances: { tournament: string; opponent: string; date: string }[];
  candidates: NameCandidate[];
};

let keptNames: { at: number; rows: Promise<StreamName[]> } | null = null;

export function fetchStreamNames(fresh = false): Promise<StreamName[]> {
  if (fresh || !keptNames || Date.now() - keptNames.at > 60_000) {
    const rows = authRequest<StreamName[]>("GET", "/schedule/stream-names");
    keptNames = { at: Date.now(), rows };
    rows.catch(() => { keptNames = null; });
  }
  return keptNames.rows;
}

// player: an id, or a nickname the player is known under
export function tieStreamName(name: string, player: string) {
  return authRequest<null>("POST", "/schedule/stream-names/tie", { name, player });
}

// playerId "" hides the name: a team, or nobody on the site
export function rejectStreamName(name: string, playerId = "") {
  return authRequest<null>("POST", "/schedule/stream-names/reject", { name, player_id: playerId });
}
