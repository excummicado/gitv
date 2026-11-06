import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { EloBadge } from "../components/EloBadge";
import { MajorToggle } from "./MajorToggle";
import { distinctNames, fetchPlayers, type PlayerSummary } from "./api";
import "./player-page.css";
import "./players-page.css";
import { useLang } from "../i18n";
import { useCached } from "../cached";
import { Nick } from "../components/PlayerNick";

type SortKey = "name" | "elo" | "tournaments" | "matches" | "match_winrate" | "games" | "winrate" | "avg_time" | "best_time" | "avg_restarts" | "tech_losses" | "tech_loss_rate" | "last_played";

// Lower is better for times, so they sort ascending first; everything else starts with the highest.
const COLUMNS: { key: SortKey; label: [string, string]; ascending?: boolean; className?: string }[] = [
  { key: "name", label: ["Player", "Игрок"], ascending: true },
  { key: "elo", label: ["Elo", "Эло"] },
  { key: "tournaments", label: ["Tourn.", "Турн."], className: "hide-sm" },
  { key: "matches", label: ["Matches", "Матчи"] },
  { key: "match_winrate", label: ["Match WR", "ВР матчей"] },
  { key: "games", label: ["Games", "Игры"], className: "hide-sm" },
  { key: "winrate", label: ["Game WR", "ВР игр"], className: "hide-xs" },
  { key: "avg_time", label: ["Avg time", "Ср. время"], ascending: true, className: "hide-xs" },
  { key: "best_time", label: ["Best", "Лучшее"], ascending: true, className: "hide-sm" },
  { key: "avg_restarts", label: ["Avg retries", "Ср. ретраи"], ascending: true, className: "hide-sm" },
  { key: "tech_losses", label: ["Tech L", "Тех. пор."], className: "hide-sm" },
  { key: "tech_loss_rate", label: ["Tech L %", "Тех. %"], className: "hide-sm" },
  { key: "last_played", label: ["Last played", "Последняя игра"], className: "hide-md" },
];

// Number filters, kept in the URL: each is a "min_"/"max_" bound on one field of the player.
const FILTERS: { param: string; label: [string, string]; field: keyof PlayerSummary; bound: "min" | "max"; suffix?: string }[] = [
  { param: "min_matches", label: ["Min matches", "Мин. матчей"], field: "matches", bound: "min" },
  { param: "min_tournaments", label: ["Min tournaments", "Мин. турниров"], field: "tournaments", bound: "min" },
  { param: "min_games", label: ["Min games", "Мин. игр"], field: "games", bound: "min" },
  { param: "min_match_wr", label: ["Min match WR", "Мин. ВР матчей"], field: "match_winrate", bound: "min", suffix: "%" },
  { param: "min_game_wr", label: ["Min game WR", "Мин. ВР игр"], field: "winrate", bound: "min", suffix: "%" },
  { param: "max_tech", label: ["Max tech losses", "Макс. тех. поражений"], field: "tech_losses", bound: "max" },
];

const ACTIVITY: { value: string; label: [string, string] }[] = [
  { value: "", label: ["Any time", "Когда угодно"] },
  { value: "30", label: ["Last 30 days", "Последние 30 дней"] },
  { value: "90", label: ["Last 3 months", "Последние 3 месяца"] },
  { value: "180", label: ["Last 6 months", "Последние 6 месяцев"] },
  { value: "365", label: ["Last year", "Последний год"] },
];

// withInactive: inactive players are ranked with everyone instead of after all active ones
function value(player: PlayerSummary, key: SortKey, withInactive = false) {
  if (key === "name") return player.name.toLowerCase();
  // Inactive players keep their rating but rank after everyone active, as in chess
  // (equal rounded ratings keep the order of the ranks, which come from the exact ones)
  if (key === "elo") {
    if (!player.elo) return null;
    if (withInactive) return player.elo.rating - player.elo.rank_all / 100000;
    return player.elo.rating - (player.elo.active ? (player.elo.rank ?? 0) / 100000 : 100000);
  }
  return player[key];
}

function percent(value: number | null) {
  return value == null ? "—" : `${value}%`;
}

export function PlayersPage() {
  const [params, setParams] = useSearchParams();
  const sort = (params.get("sort") as SortKey | null) ?? "matches";
  const ascending = params.get("dir") === "asc";
  const [search, setSearch] = useState(params.get("q") ?? "");
  const active = params.get("active") ?? "";
  const major = params.get("major") === "1";
  const withInactive = params.get("inactive") === "1";
  const bounds = FILTERS.map((f) => ({ ...f, value: params.get(f.param) ?? "" }));
  const filtersOn = Boolean(active) || bounds.some((b) => b.value !== "");
  const { t, date } = useLang();
  const scope = major ? "major" : "all";
  const { data: players, error } = useCached(`players?${scope}`, (signal) => fetchPlayers(signal, scope), t("Couldn't load the players.", "Не удалось загрузить игроков."));

  // Applied to the live URL, not the one from this render, so quick successive changes all stick.
  function update(changes: Record<string, string>) {
    // React Router hands the function the params of the last render, so read the live URL instead.
    setParams(() => {
      const next = new URLSearchParams(window.location.search);
      for (const [key, v] of Object.entries(changes)) {
        if (v) next.set(key, v);
        else next.delete(key);
      }
      return next;
    }, { replace: true });
  }

  function sortBy(key: SortKey) {
    const column = COLUMNS.find((c) => c.key === key)!;
    const nextAscending = key === sort ? !ascending : Boolean(column.ascending);
    update({ sort: key, dir: nextAscending ? "asc" : "desc" });
  }

  function resetFilters() {
    update({ active: "", q: "", ...Object.fromEntries(FILTERS.map((f) => [f.param, ""])) });
    setSearch("");
  }

  const shown = useMemo(() => {
    if (!players) return [];
    const needle = search.trim().toLowerCase();
    const since = active ? Date.now() - Number(active) * 86400000 : null;
    const limits = bounds.filter((b) => b.value !== "").map((b) => ({ ...b, number: Number(b.value) }));
    const filtered = players.filter((p) => {
      if (needle && !p.name.toLowerCase().includes(needle) && !p.other_names.some((n) => n.toLowerCase().includes(needle))) return false;
      if (since && (!p.last_played || new Date(p.last_played).getTime() < since)) return false;
      // A player without the value (no decided games for a winrate) doesn't pass a minimum.
      return limits.every(({ field, bound, number }) => {
        const v = p[field] as number | null;
        if (v == null) return bound === "max";
        return bound === "min" ? v >= number : v <= number;
      });
    });
    // Players without a value (no timed games) always go last.
    return [...filtered].sort((a, b) => {
      const x = value(a, sort, withInactive), y = value(b, sort, withInactive);
      if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
      const order = x < y ? -1 : x > y ? 1 : 0;
      return ascending ? order : -order;
    });
  }, [players, search, sort, ascending, active, withInactive, ...bounds.map((b) => b.value)]);

  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="player-content match-content">
            <div className="player-box players-filters">
              <input className="match-input players-search" type="search" placeholder={t("Player, including old nicknames", "Игрок, в том числе по старым никам")} aria-label={t("Search players", "Поиск игроков")} value={search}
                onChange={(e) => { setSearch(e.target.value); update({ q: e.target.value.trim() }); }} />
              <div className="players-filter-grid">
                {bounds.map((b) => (
                  <label className="players-filter" key={b.param}>
                    <span className="player-label">{t(...b.label)}{b.suffix ? ` (${b.suffix})` : ""}</span>
                    <input className="match-input" type="number" inputMode="numeric" min={0} max={b.suffix === "%" ? 100 : undefined} placeholder={t("Any", "Любое")} aria-label={t(...b.label)}
                      value={b.value} onChange={(e) => update({ [b.param]: e.target.value })} />
                  </label>
                ))}
                <label className="players-filter">
                  <span className="player-label">{t("Played", "Играл")}</span>
                  <select className="match-input" aria-label={t("Played", "Играл")} value={active} onChange={(e) => update({ active: e.target.value })}>
                    {ACTIVITY.map((a) => <option value={a.value} key={a.value}>{t(...a.label)}</option>)}
                  </select>
                </label>
              </div>
              <div className="players-actions">
                <MajorToggle on={major} onChange={(on) => update({ major: on ? "1" : "" })} />
                <button type="button" className={`player-major${withInactive ? " active" : ""}`} aria-pressed={withInactive} onClick={() => update({ inactive: withInactive ? "" : "1" })}
                  title={t("Rank players who haven't played for six months by Elo with everyone else", "Ставить в рейтинг Эло и тех, кто не играл полгода")}>
                  {withInactive ? t("Inactive players included", "Неактивные в рейтинге") : t("Include inactive players", "Включить неактивных")}
                </button>
                {(filtersOn || search) && <button type="button" className="match-input players-reset" onClick={resetFilters}>{t("Reset filters", "Сбросить фильтры")}</button>}
              </div>
            </div>

            <section className="player-box">
              <h2 className="player-box-title match-game-title">
                <span>{t("Players", "Игроки")}</span>
                {players && <span className="match-game-meta">{shown.length === players.length ? players.length : `${shown.length} ${t("of", "из")} ${players.length}`}</span>}
              </h2>
              {error ? <p className="match-empty">{error}</p>
                : !players ? <p className="match-empty">{t("Loading players…", "Загрузка игроков…")}</p>
                : !shown.length ? <p className="match-empty">{t("No players found.", "Игроки не найдены.")}</p>
                : (
                  <div className="players-table" role="table" aria-label={t("Players", "Игроки")}>
                    <div className="players-row players-head" role="row">
                      {COLUMNS.map((c) => (
                        <button type="button" role="columnheader" key={c.key} className={`players-sort ${c.className ?? ""}${sort === c.key ? " is-sorted" : ""}`}
                          aria-sort={sort === c.key ? (ascending ? "ascending" : "descending") : "none"} onClick={() => sortBy(c.key)}>
                          {t(...c.label)}{sort === c.key && <span aria-hidden="true">{ascending ? " ↑" : " ↓"}</span>}
                        </button>
                      ))}
                    </div>
                    {shown.map((p) => (
                      <Link className="players-row" role="row" to={`/player/${p.id}${major ? "?major=1" : ""}`} key={p.id}>
                        <span className="players-name">
                          <Nick id={p.id} name={p.name} />
                          {distinctNames(p.name, p.other_names).length > 0 && <span className="players-aka player-label">aka {distinctNames(p.name, p.other_names).slice(0, 2).join(", ")}</span>}
                        </span>
                        {p.elo ? (
                          <span className="players-elo">
                            {withInactive
                              ? <EloBadge rating={p.elo.rating} rank={p.elo.rank_all} tier={p.elo.tier_all} dormant={!p.elo.active} />
                              : <EloBadge rating={p.elo.rating} rank={p.elo.rank} tier={p.elo.tier} active={p.elo.active} />}
                            {sort === "elo" && (withInactive ? p.elo.rank_all : p.elo.rank) && <span className="players-elo-rank player-label">#{withInactive ? p.elo.rank_all : p.elo.rank}</span>}
                          </span>
                        ) : <span>—</span>}
                        <span className="hide-sm">{p.tournaments}</span>
                        <span>{p.matches}</span>
                        <span>{percent(p.match_winrate)}</span>
                        <span className="hide-sm">{p.games}</span>
                        <span className="hide-xs">{percent(p.winrate)}</span>
                        <span className="hide-xs">{p.avg_time != null ? `${p.avg_time}${t("s", "с")}` : "—"}</span>
                        <span className="hide-sm">{p.best_time != null ? `${p.best_time}${t("s", "с")}` : "—"}</span>
                        <span className="hide-sm">{p.avg_restarts ?? "—"}</span>
                        <span className="hide-sm">{p.tech_losses || "—"}</span>
                        <span className="hide-sm">{p.tech_loss_rate ? `${p.tech_loss_rate}%` : "—"}</span>
                        <span className="hide-md gitv-date">{date(p.last_played)}</span>
                      </Link>
                    ))}
                  </div>
                )}
            </section>
          </div>
        </div>
      </div>
    </main>
  );
}
