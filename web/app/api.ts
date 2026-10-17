// Shared by every API client: the error type, public GET requests, and messages in the site's language.
// Errors the API sends come translated already (api/app/messages.py reads the same gitv-lang cookie);
// the messages written here are for when the API can't answer at all.

export class ApiError extends Error {
  constructor(message: string, public status = 0) {
    super(message);
  }
}

export type Message = [en: string, ru: string];

// The site language outside React (API helpers run in effects, after the cookie is set).
export function tr([en, ru]: Message): string {
  if (typeof document === "undefined") return en;
  return /(?:^|;\s*)gitv-lang=ru\b/.test(document.cookie) ? ru : en;
}

export const UNREACHABLE: Message = ["Can't reach the server. Check that the API is running.", "Сервер недоступен. Проверьте, что API запущен."];
const FAILED: Message = ["Couldn't load the data. Try again.", "Не удалось загрузить данные. Попробуйте ещё раз."];

// The API's own message (translated there) when it sent one, else the fallback.
export async function errorFrom(response: Response, fallback: Message): Promise<ApiError> {
  const data = await response.json().catch(() => null);
  return new ApiError(typeof data?.detail === "string" ? data.detail : tr(fallback), response.status);
}

// A public GET. notFound replaces the API's 404 message where the page knows better what's missing.
export async function getJson<T>(path: string, options: { signal?: AbortSignal; notFound?: Message; failed?: Message } = {}): Promise<T> {
  const { signal, notFound, failed = FAILED } = options;
  let response: Response;
  try {
    response = await fetch(path, { signal });
  } catch (err) {
    if (signal?.aborted) throw err;
    throw new ApiError(tr(UNREACHABLE));
  }
  if (response.status === 404 && notFound) throw new ApiError(tr(notFound), 404);
  if (!response.ok) throw await errorFrom(response, failed);
  return response.json();
}
