// Suggestions for a tournament player's real name, birthday and avatar (api/app/routers/suggestions.py).

import { authRequest } from "../auth/client";

export type PlayerInfo = { real_name: string | null; birth_date: string | null; age: number | null; avatar_url: string | null };
export type SuggestionStatus = "pending" | "accepted" | "rejected";
export type Suggestion = {
  id: number; player: { id: string; name: string }; author: string;
  real_name: string | null; birth_date: string | null; age: number | null; avatar_url: string | null;
  status: SuggestionStatus; created_at: string; current: PlayerInfo | null;
};
export type ProfileChange = {
  field: "real_name" | "birth_date" | "avatar"; old_value: string | null; new_value: string | null;
  changed_by: string; suggested_by: string | null; created_at: string;
};
export type MySuggestions = { banned: boolean; pending: number; max_pending: number };

export function mySuggestions() {
  return authRequest<MySuggestions>("GET", "/suggestions/me");
}

export function suggest(playerId: string, form: FormData) {
  return authRequest<{ id: number }>("POST", `/players/${encodeURIComponent(playerId)}/suggestions`, form);
}

// Event organizers and admins write directly; only the fields passed change, null clears one.
export function editProfile(playerId: string, changes: { real_name?: string | null; birth_date?: string | null }) {
  return authRequest<PlayerInfo>("PUT", `/players/${encodeURIComponent(playerId)}/profile`, changes);
}

export function listSuggestions(status: SuggestionStatus = "pending") {
  return authRequest<Suggestion[]>("GET", `/admin/suggestions?status=${status}`);
}

export function acceptSuggestion(id: number) {
  return authRequest<PlayerInfo>("POST", `/admin/suggestions/${id}/accept`);
}

export function rejectSuggestion(id: number) {
  return authRequest<null>("POST", `/admin/suggestions/${id}/reject`);
}

export function listSuggestionBans() {
  return authRequest<string[]>("GET", "/admin/suggestion-bans");
}

export function banSuggestions(nickname: string) {
  return authRequest<{ nickname: string; banned: boolean }>("POST", "/admin/suggestion-bans", { nickname });
}

export function unbanSuggestions(nickname: string) {
  return authRequest<{ nickname: string; banned: boolean }>("DELETE", `/admin/suggestion-bans/${encodeURIComponent(nickname)}`);
}
