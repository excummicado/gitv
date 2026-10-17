// Site language: English or Russian, chosen in the navbar and kept in a cookie so the server renders
// the right one straight away. Strings sit where they're used as t("English", "Русский") pairs.

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { useRevalidator } from "react-router";

export type Lang = "en" | "ru";
export const LANGS: Lang[] = ["en", "ru"];
const COOKIE = "gitv-lang";

export function langFromCookie(cookieHeader: string | null | undefined): Lang {
  const match = /(?:^|;\s*)gitv-lang=(en|ru)\b/.exec(cookieHeader ?? "");
  return (match?.[1] as Lang) ?? "en";
}

type LangState = { lang: Lang; setLang: (lang: Lang) => void };
const LangContext = createContext<LangState>({ lang: "en", setLang: () => {} });

export function LangProvider({ initial, children }: { initial: Lang; children: ReactNode }) {
  const [lang, setState] = useState<Lang>(initial);
  const setLang = useCallback((next: Lang) => {
    document.cookie = `${COOKIE}=${next}; path=/; max-age=31536000; samesite=lax`;
    document.documentElement.lang = next;
    setState(next);
  }, []);
  const value = useMemo(() => ({ lang, setLang }), [lang, setLang]);
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

// Russian plural forms: one (1, 21), few (2-4, 22-24), many (0, 5-20, 25-30).
function ruForm(n: number) {
  const mod10 = n % 10, mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return 0;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 1;
  return 2;
}

export function useLang() {
  const { lang, setLang } = useContext(LangContext);
  return useMemo(() => {
    const ru = lang === "ru";
    return {
      lang,
      setLang,
      locale: ru ? "ru-RU" : "en-GB",
      t: (en: string, russian: string) => (ru ? russian : en),
      // "3 matches" / "3 матча": English one/other, Russian one/few/many.
      count: (n: number, en: [string, string], russian: [string, string, string]) =>
        `${n} ${ru ? russian[ruForm(n)] : en[n === 1 ? 0 : 1]}`,
      date: (value: string | null | undefined) =>
        value ? new Date(value).toLocaleDateString(ru ? "ru-RU" : "en-GB", { day: "2-digit", month: "2-digit", year: "numeric" }) : "—",
      // Characters and weapons carry both names; the API's `name` is English.
      name: (item: { name: string; name_ru?: string | null }) => (ru && item.name_ru ? item.name_ru : item.name),
    };
  }, [lang, setLang]);
}

export function LangSwitch() {
  const { lang, setLang, t } = useLang();
  // Re-running the root loader picks up the new cookie, so tab titles (route meta) switch too.
  const revalidator = useRevalidator();
  return (
    <span className="gitv-lang" role="group" aria-label={t("Language", "Язык")}>
      {LANGS.map((l) => (
        <button type="button" key={l} className={`gitv-lang-option${lang === l ? " is-active" : ""}`} aria-pressed={lang === l} onClick={() => { setLang(l); revalidator.revalidate(); }}>
          {l.toUpperCase()}
        </button>
      ))}
    </span>
  );
}

// For route meta(): the language from the root loader, since hooks aren't available there.
export function metaLang(matches: readonly ({ id: string; loaderData?: unknown } | undefined)[]): Lang {
  const root = matches.find((m) => m?.id === "root")?.loaderData as { lang?: Lang } | undefined;
  return root?.lang ?? "en";
}
