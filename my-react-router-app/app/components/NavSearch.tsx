import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { fetchTournaments, type TournamentItem } from "../match/api";
import { fetchPlayers, type PlayerSummary } from "../player/api";
import { useLang } from "../i18n";

const LIMIT = 5;

type Result = { kind: "player" | "tournament"; id: string; label: string; alias: string | null; matches: number; to: string };

// Players and tournaments load once, on first focus; filtering then happens as you type.
let cache: Promise<[PlayerSummary[], TournamentItem[]]> | null = null;
function loadIndex() {
  cache ??= Promise.all([fetchPlayers(), fetchTournaments()]).catch((err) => {
    cache = null;
    throw err;
  });
  return cache;
}

function search(query: string, players: PlayerSummary[], tournaments: TournamentItem[]): Result[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  // Names that start with the query come before ones that only contain it.
  const rank = (text: string) => (text.toLowerCase().startsWith(q) ? 0 : 1);
  const foundPlayers = players
    .map((p) => {
      const alias = p.other_names.find((n) => n.toLowerCase().includes(q));
      return p.name.toLowerCase().includes(q) ? { p, alias: null, r: rank(p.name) } : alias ? { p, alias, r: 2 } : null;
    })
    .filter((x) => x !== null)
    .sort((a, b) => a.r - b.r || b.p.matches - a.p.matches)
    .slice(0, LIMIT)
    .map(({ p, alias }): Result => ({ kind: "player", id: p.id, label: p.name, alias, matches: p.matches, to: `/player/${p.id}` }));
  const foundTournaments = tournaments
    .filter((t) => t.title.toLowerCase().includes(q))
    .sort((a, b) => rank(a.title) - rank(b.title))
    .slice(0, LIMIT)
    .map((t): Result => ({ kind: "tournament", id: t.id, label: t.title, alias: null, matches: t.matches, to: `/matches?tournament=${t.id}` }));
  return [...foundPlayers, ...foundTournaments];
}

export function NavSearch({ className = "" }: { className?: string }) {
  const navigate = useNavigate();
  const { t, count } = useLang();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [index, setIndex] = useState<[PlayerSummary[], TournamentItem[]] | null>(null);
  const [failed, setFailed] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const results = useMemo(() => (index ? search(query, index[0], index[1]) : []), [query, index]);
  useEffect(() => setActive(0), [query]);

  function load() {
    if (index) return;
    loadIndex().then(setIndex).catch(() => setFailed(true));
  }

  function go(result: Result | undefined) {
    if (!result) return;
    navigate(result.to);
    setQuery("");
    setOpen(false);
    input.current?.blur();
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!results.length) return;
      setActive((i) => (i + (event.key === "ArrowDown" ? 1 : results.length - 1)) % results.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      go(results[active]);
    } else if (event.key === "Escape") {
      setOpen(false);
      input.current?.blur();
    }
  }

  const showList = open && query.trim() !== "";
  return (
    <div className={`gitv-search ${className}`}>
      <input
        ref={input}
        type="search"
        className="gitv-search-input"
        placeholder={t("Search...", "Поиск...")}
        aria-label={t("Search players and tournaments", "Поиск игроков и турниров")}
        role="combobox"
        aria-expanded={showList}
        aria-controls="gitv-search-results"
        aria-activedescendant={showList && results[active] ? `gitv-search-${active}` : undefined}
        autoComplete="off"
        value={query}
        onFocus={() => { load(); setOpen(true); }}
        onBlur={() => setOpen(false)}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
        onKeyDown={onKeyDown}
      />
      {showList && (
        <ul className="gitv-search-results" id="gitv-search-results" role="listbox">
          {failed ? <li className="gitv-search-empty">{t("Couldn't load the search. Try again.", "Не удалось загрузить поиск. Попробуйте ещё раз.")}</li>
            : !index ? <li className="gitv-search-empty">{t("Loading…", "Загрузка…")}</li>
            : !results.length ? <li className="gitv-search-empty">{t("Nothing found.", "Ничего не найдено.")}</li>
            : results.map((r, i) => (
                <li
                  key={`${r.kind}-${r.id}`}
                  id={`gitv-search-${i}`}
                  role="option"
                  aria-selected={i === active}
                  className={`gitv-search-result${i === active ? " is-active" : ""}`}
                  // mousedown, not click: the input's blur would close the list before a click lands.
                  onMouseDown={(e) => { e.preventDefault(); go(r); }}
                  onMouseEnter={() => setActive(i)}
                >
                  <span className="gitv-search-kind">{r.kind === "player" ? t("Player", "Игрок") : t("Tournament", "Турнир")}</span>
                  <span className="gitv-search-label">{r.label}</span>
                  <span className="gitv-search-detail">{r.alias ? `aka ${r.alias}` : count(r.matches, ["match", "matches"], ["матч", "матча", "матчей"])}</span>
                </li>
              ))}
        </ul>
      )}
    </div>
  );
}
