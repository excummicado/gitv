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
