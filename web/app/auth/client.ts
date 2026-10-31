// The Discord sign-in: the API keeps the token in an httpOnly cookie (scripts never see it); the browser keeps
// only the signed-in user, to show them before /users/me answers. Requests that change something carry
// AUTH_HEADER, which the API asks of cookie sign-ins against cross-site requests.

import { ApiError, errorFrom, tr, UNREACHABLE, type Message } from "../api";

export type User = { id: string; nickname: string; discord_username: string | null; role: Role };
export type Role = "user" | "writer" | "event_organizer" | "admin" | "super_admin";
export const ROLE_LABELS: Record<Role, string> = { user: "Member", writer: "Writer", event_organizer: "Event organizer", admin: "Admin", super_admin: "Super admin" };
export const ROLE_LABELS_RU: Record<Role, string> = { user: "Участник", writer: "Автор", event_organizer: "Организатор", admin: "Админ", super_admin: "Супер-админ" };
export const STAFF_ROLES: Role[] = ["admin", "super_admin"];
// May schedule the matches of the day.
export const PLAYER_EDITOR_ROLES: Role[] = ["event_organizer", "admin", "super_admin"];
type Session = { user: User };
const AUTH_HEADER = { "X-GITV": "1" };

export { ApiError } from "../api";

const API = "/api/v1";
// Same rule as the API: 3–32 letters, digits, underscores or periods.
export const NICKNAME_PATTERN = /^[A-Za-z0-9_.]{3,32}$/;
export const NICKNAME_HINT = "3–32 letters, numbers, underscores or periods.";
export const NICKNAME_HINT_RU = "3–32 латинские буквы, цифры, подчёркивания или точки.";
const STORAGE_KEY = "gitv-auth";
const listeners = new Set<() => void>();

function readStored(): Session | null {
  if (typeof window === "undefined") return null;
  try {
    // localStorage keeps members signed in across browser restarts; the API decides how long the token lasts.
    const raw = localStorage.getItem(STORAGE_KEY);
    const stored = raw ? (JSON.parse(raw) as Session & { access_token?: string }) : null;
    // A session saved before the cookie (with its token in storage) is dropped: sign in again.
    if (stored?.access_token) {
      localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return stored;
  } catch {
    return null;
  }
}

function notify() {
  listeners.forEach((listener) => listener());
}

function forget() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage can be unavailable (private mode); nothing to clear then.
  }
  notify();
}

function remember(user: User) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ user }));
  } catch {
    // Storage unavailable (private mode): the cookie still signs requests in.
  }
  notify();
}

// Signing out: the API drops the cookie, the browser forgets the user.
export function clearSession() {
  fetch(`${API}/auth/discord/logout`, { method: "POST", headers: AUTH_HEADER }).catch(() => {});
  forget();
}

export function getCurrentUser(): User | null {
  return readStored()?.user ?? null;
}

export function onAuthChange(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

async function fetchMe(): Promise<User> {
  let response: Response;
  try {
    response = await fetch(`${API}/users/me`);
  } catch {
    throw new ApiError(tr(UNREACHABLE));
  }
  if (!response.ok) throw await errorFrom(response, NOT_SIGNED_IN);
  return response.json();
}

// Discord sign-in: after the OAuth2 redirect the API has set the cookie; this fetches who signed in.
export async function finishSignIn() {
  const user = await fetchMe();
  remember(user);
  return user;
}

const NOT_SIGNED_IN: Message = ["Not signed in.", "Вы не вошли."];

// Staff tools, by nickname: roles (super admins) and bans (admins and super admins).
async function adminRequest(method: "POST" | "PUT" | "DELETE", path: string, body?: unknown): Promise<User> {
  if (!readStored()) throw new ApiError(tr(NOT_SIGNED_IN), 401);
  let response: Response;
  try {
    response = await fetch(`${API}/admin${path}`, {
      method,
      headers: { "Content-Type": "application/json", ...AUTH_HEADER },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(tr(UNREACHABLE));
  }
  if (!response.ok) {
    if (response.status === 401) forget();
    throw await errorFrom(response, ["Couldn't save the change. Try again.", "Не удалось сохранить изменение. Попробуйте ещё раз."]);
  }
  const data = await response.json().catch(() => null);
  return data as User;
}

// A request as the signed-in member: JSON or FormData body, the API's error message on failure,
// and a local sign-out when the sign-in is no longer accepted. Returns null for an empty (204) response.
export async function authRequest<T>(method: "GET" | "POST" | "PUT" | "DELETE", path: string, body?: unknown): Promise<T> {
  if (!readStored()) throw new ApiError(tr(["Sign in first.", "Сначала войдите."]), 401);
  const headers: Record<string, string> = { ...AUTH_HEADER };
  if (body !== undefined && !(body instanceof FormData)) headers["Content-Type"] = "application/json";
  let response: Response;
  try {
    response = await fetch(`${API}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(tr(UNREACHABLE));
  }
  if (!response.ok) {
    if (response.status === 401) forget();
    throw await errorFrom(response, ["Something went wrong. Try again.", "Что-то пошло не так. Попробуйте ещё раз."]);
  }
  const data = response.status === 204 ? null : await response.json().catch(() => null);
  return data as T;
}

// Super admin can't be set from the site.
export type AssignableRole = Exclude<Role, "super_admin">;

export function setRole(nickname: string, role: AssignableRole) {
  return adminRequest("PUT", `/users/${encodeURIComponent(nickname)}/role`, { role });
}

export function banUser(nickname: string) {
  return adminRequest("POST", "/bans", { nickname });
}

export function unbanUser(nickname: string) {
  return adminRequest("DELETE", `/bans/${encodeURIComponent(nickname)}`);
}

// Changes the signed-in user's displayed nickname; the navbar updates through the auth listeners.
export async function updateNickname(nickname: string) {
  if (!readStored()) throw new ApiError("Not signed in.", 401);
  let response: Response;
  try {
    response = await fetch(`${API}/users/me`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...AUTH_HEADER },
      body: JSON.stringify({ nickname }),
    });
  } catch {
    throw new ApiError("Can't reach the server. Check that the API is running.");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401) forget();
    const detail = typeof data?.detail === "string" ? data.detail : NICKNAME_HINT;
    throw new ApiError(detail, response.status);
  }
  remember(data as User);
  return data as User;
}

// First Discord sign-in: create the account with the chosen nickname, then sign in.
export async function completeDiscordSignup(signupToken: string, nickname: string) {
  let response: Response;
  try {
    response = await fetch(`${API}/auth/discord/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ signup_token: signupToken, nickname }),
    });
  } catch {
    throw new ApiError("Can't reach the server. Check that the API is running.");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : "Choose a different nickname.";
    throw new ApiError(detail, response.status);
  }
  remember(data as User);
  return data as User;
}

// Confirms the sign-in is still accepted and refreshes the saved user from the API
// (nickname, Discord username, role); signs out locally once it has expired.
export async function verifySession() {
  const session = readStored();
  if (!session) return;
  try {
    const user = await fetchMe();
    if (JSON.stringify(user) !== JSON.stringify(session.user)) remember(user);
  } catch (err) {
    if (err instanceof ApiError && (err.status === 401 || err.status === 403)) forget();
  }
}
