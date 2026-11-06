// Lists worth keeping between visits: what was fetched before shows at once, and the fresh copy replaces it as soon as
// it arrives. Kept in memory for moving around the site and in the browser's storage for coming back to it.

import { useEffect, useState } from "react";

// Raise when a kept list's shape changes: copies from before would break the page until the fresh one came.
const STORAGE = "gitv-cache:1:";
const INDEX = "gitv-cache-index";
const MAX_STORED = 10;
const MAX_IN_MEMORY = 30;

const memory = new Map<string, unknown>();

function readStored<T>(key: string): T | undefined {
  try {
    const raw = localStorage.getItem(STORAGE + key);
    return raw == null ? undefined : (JSON.parse(raw) as T);
  } catch {
    return undefined;
  }
}

function keep(key: string, data: unknown) {
  memory.delete(key);
  memory.set(key, data);
  if (memory.size > MAX_IN_MEMORY) memory.delete(memory.keys().next().value!);
  try {
    const known: string[] = JSON.parse(localStorage.getItem(INDEX) ?? "[]");
    const index = [key, ...known.filter((k) => k !== key)].slice(0, MAX_STORED);
    // Whatever fell off the index, or was kept by an older version of the site, makes room first.
    const wanted = new Set(index.map((k) => STORAGE + k));
    for (const name of Object.keys(localStorage)) {
      if (name.startsWith("gitv-cache:") && !wanted.has(name)) localStorage.removeItem(name);
    }
    localStorage.setItem(STORAGE + key, JSON.stringify(data));
    localStorage.setItem(INDEX, JSON.stringify(index));
  } catch {
    // Storage full or blocked: memory alone will do
  }
}

// key names the list and its filters (null: nothing to load yet). The list on screen stays until the next one is there.
// A failed refresh only counts as an error when there's nothing kept to show.
export function useCached<T>(key: string | null, load: (signal: AbortSignal) => Promise<T>, failed: string) {
  // Memory only: the first render has to match the server's, and the storage waits for the effect below
  const [data, setData] = useState<T | null>(() => (key != null && memory.has(key) ? (memory.get(key) as T) : null));
  const [error, setError] = useState("");
  useEffect(() => {
    if (key == null) return;
    const controller = new AbortController();
    const known = memory.has(key) ? (memory.get(key) as T) : readStored<T>(key);
    setError("");
    if (known !== undefined) setData(known);
    load(controller.signal)
      .then((fresh) => { keep(key, fresh); setData(fresh); })
      .catch((err) => {
        if (controller.signal.aborted || known !== undefined) return;
        setError(err instanceof Error ? err.message : failed);
      });
    return () => controller.abort();
  }, [key]);
  return { data, error };
}
