// Keeps the Discord sign-in session in browser storage and talks to the API's /users/me.

export type User = { id: string; email: string; nickname: string; discord_username: string | null; role: Role };
export type Role = "user" | "writer" | "event_organizer" | "admin" | "super_admin";
export const ROLE_LABELS: Record<Role, string> = { user: "Member", writer: "Writer", event_organizer: "Event organizer", admin: "Admin", super_admin: "Super admin" };
export const ROLE_LABELS_RU: Record<Role, string> = { user: "Участник", writer: "Автор", event_organizer: "Организатор", admin: "Админ", super_admin: "Супер-админ" };
export const STAFF_ROLES: Role[] = ["admin", "super_admin"];
// May write a tournament player's real name and birthday directly; everyone else suggests.
export const PLAYER_EDITOR_ROLES: Role[] = ["event_organizer", "admin", "super_admin"];
type Session = { access_token: string; user: User };

export class ApiError extends Error {
  constructor(message: string, public status = 0) {
    super(message);
  }
}

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
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

function notify() {
  listeners.forEach((listener) => listener());
}

export function clearSession() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage can be unavailable (private mode); nothing to clear then.
  }
  notify();
}

export function getCurrentUser(): User | null {
  return readStored()?.user ?? null;
}

export function onAuthChange(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

async function fetchMe(accessToken: string): Promise<User> {
  let response: Response;
  try {
    response = await fetch(`${API}/users/me`, { headers: { Authorization: `Bearer ${accessToken}` } });
  } catch {
    throw new ApiError("Can't reach the server. Check that the API is running.");
  }
  if (!response.ok) throw new ApiError("Not signed in.", response.status);
  return response.json();
}

// Discord sign-in: the API hands back a GITV token after the OAuth2 redirect.
export async function loginWithToken(accessToken: string) {
  const user = await fetchMe(accessToken);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ access_token: accessToken, user }));
  } catch {
    // Storage unavailable (private mode): the sign-in can't be kept.
  }
  notify();
  return user;
}

// Staff tools, by nickname: roles (super admins) and bans (admins and super admins).
async function adminRequest(method: "POST" | "PUT" | "DELETE", path: string, body?: unknown): Promise<User> {
  const session = readStored();
  if (!session) throw new ApiError("Not signed in.", 401);
  let response: Response;
  try {
    response = await fetch(`${API}/admin${path}`, {
      method,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${session.access_token}` },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Can't reach the server. Check that the API is running.");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401) clearSession();
    throw new ApiError(typeof data?.detail === "string" ? data.detail : "Couldn't save the change. Try again.", response.status);
  }
  return data as User;
}

// A request as the signed-in member: JSON or FormData body, the API's error message on failure,
// and a local sign-out when the token is no longer accepted. Returns null for an empty (204) response.
export async function authRequest<T>(method: "GET" | "POST" | "PUT" | "DELETE", path: string, body?: unknown): Promise<T> {
  const session = readStored();
  if (!session) throw new ApiError("Sign in first.", 401);
  const headers: Record<string, string> = { Authorization: `Bearer ${session.access_token}` };
  if (body !== undefined && !(body instanceof FormData)) headers["Content-Type"] = "application/json";
  let response: Response;
  try {
    response = await fetch(`${API}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Can't reach the server. Check that the API is running.");
  }
  const data = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401) clearSession();
    throw new ApiError(typeof data?.detail === "string" ? data.detail : "Something went wrong. Try again.", response.status);
  }
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
  const session = readStored();
  if (!session) throw new ApiError("Not signed in.", 401);
  let response: Response;
  try {
    response = await fetch(`${API}/users/me`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${session.access_token}` },
      body: JSON.stringify({ nickname }),
    });
  } catch {
    throw new ApiError("Can't reach the server. Check that the API is running.");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401) clearSession();
    const detail = typeof data?.detail === "string" ? data.detail : NICKNAME_HINT;
    throw new ApiError(detail, response.status);
  }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...session, user: data }));
  } catch {
    // Storage unavailable: the new nickname still shows after the next sign-in.
  }
  notify();
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
  return loginWithToken(data.access_token);
}

// Confirms the stored token is still accepted and refreshes the saved user from the API
// (nickname, Discord username, role); signs out locally once the token has expired.
export async function verifySession() {
  const session = readStored();
  if (!session) return;
  try {
    const user = await fetchMe(session.access_token);
    if (JSON.stringify(user) !== JSON.stringify(session.user)) {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...session, user }));
      } catch {
        // Storage unavailable: the fresh details show after the next sign-in.
      }
      notify();
    }
  } catch (err) {
    if (err instanceof ApiError && (err.status === 401 || err.status === 403)) clearSession();
  }
}
