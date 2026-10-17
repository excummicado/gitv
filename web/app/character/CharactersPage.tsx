import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { MajorToggle } from "../player/MajorToggle";
import { useLang } from "../i18n";
import { fetchCharacterConstellations, fetchCharacterPlayers, fetchCharacterTable, type CharacterPlayer, type ConstellationRow, type CharacterRow, type CharacterTable, type PrizeFilter, type TableFilters } from "./api";
import "./characters.css";

type SortKey = "name" | "presence" | "pick_rate" | "ban_rate" | "winrate" | "picks" | "bans" | "avg_constellation" | "avg_time" | "players";

// Lower is better only for time, so it starts ascending.
const COLUMNS: { key: SortKey; label: [string, string]; title: [string, string]; ascending?: boolean; className?: string }[] = [
  { key: "name", label: ["Character", "Персонаж"], title: ["", ""], ascending: true },
  { key: "presence", label: ["Presence", "В драфте"], title: ["Share of games where it was picked or banned", "Доля игр, где его пикали или банили"] },
  { key: "pick_rate", label: ["Pick rate", "Пикрейт"], title: ["Share of all teams that had it", "Доля всех составов с ним"] },
  { key: "ban_rate", label: ["Ban rate", "Банрейт"], title: ["Share of games where it was banned", "Доля игр, где его банили"] },
  { key: "winrate", label: ["Winrate", "Винрейт"], title: ["Games won when picked (decided games)", "Победы в играх с ним (с результатом)"] },
  { key: "picks", label: ["Picks", "Пики"], title: ["Teams that had it", "Составов с ним"], className: "hide-sm" },
  { key: "bans", label: ["Bans", "Баны"], title: ["Times banned", "Сколько раз банили"], className: "hide-sm" },
  { key: "avg_constellation", label: ["Avg C", "Ср. C"], title: ["Average constellation when picked", "Средняя конста в пиках"], className: "hide-xs" },
  { key: "avg_time", label: ["Avg time", "Ср. время"], title: ["Average clear time when picked", "Среднее время в играх с ним"], ascending: true, className: "hide-md" },
  { key: "players", label: ["Players", "Игроки"], title: ["Different players who picked it", "Сколько разных игроков пикали"], className: "hide-md" },
];

// Prize winners: players who finished in a tournament's top four at least once.
const PRIZE_OPTIONS: { value: PrizeFilter; label: [string, string]; title: [string, string] }[] = [
  { value: "", label: ["All players", "Все игроки"], title: ["Every game counts", "Считаются все игры"] },
  { value: "players", label: ["Prize winners", "Призёры"],
    title: ["Only prize winners' picks and bans, in every game they played (opponents included)", "Только пики и баны призёров во всех их играх, в том числе против непризёров"] },
  { value: "versus", label: ["Prize vs prize", "Призёры против призёров"],
    title: ["Only games between two prize winners; both sides count", "Только игры, где оба игрока — призёры; считаются обе стороны"] },
];

const MAX_CONSTELLATION = 6;

function clampConstellation(value: string | null, fallback: number) {
  const n = Number(value);
  return value != null && value !== "" && Number.isInteger(n) && n >= 0 && n <= MAX_CONSTELLATION ? n : fallback;
}

// Two handles on one track, C0 to C6. Dragging takes the handle nearest the pointer; when the two sit on
// the same constellation, the direction of the drag decides which one moves, so they can always be pulled
// apart. Each handle also works with the arrow keys. Moves show at once; the table reloads once they stop.
function ConstellationRange({ value, onChange }: { value: [number, number]; onChange: (range: [number, number]) => void }) {
  const { t } = useLang();
  const [range, setRange] = useState(value);
  const track = useRef<HTMLDivElement>(null);
  // The handle being dragged; "either" until a tie is broken by the first move.
  const drag = useRef<"lo" | "hi" | "either" | null>(null);
  useEffect(() => setRange(value), [value[0], value[1]]);
  useEffect(() => {
    if (range[0] === value[0] && range[1] === value[1]) return;
    const timer = setTimeout(() => onChange(range), 250);
    return () => clearTimeout(timer);
  }, [range[0], range[1]]);
  const [lo, hi] = range;

  function at(clientX: number) {
    const box = track.current!.getBoundingClientRect();
    return Math.round(Math.min(1, Math.max(0, (clientX - box.left) / box.width)) * MAX_CONSTELLATION);
  }

  function move(handle: "lo" | "hi", v: number) {
    setRange(([a, b]) => (handle === "lo" ? [Math.min(v, b), b] : [a, Math.max(v, a)]));
  }

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    e.preventDefault();
    track.current!.setPointerCapture(e.pointerId);
    const v = at(e.clientX);
    if (lo === hi) {
      // Tied: wait for the drag's direction, unless the press itself is to one side.
      drag.current = v < lo ? "lo" : v > hi ? "hi" : "either";
    } else {
      drag.current = v <= lo || (v < hi && v - lo <= hi - v) ? "lo" : "hi";
    }
    if (drag.current !== "either") move(drag.current, v);
    (e.currentTarget.querySelector(`[data-handle="${drag.current === "hi" ? "hi" : "lo"}"]`) as HTMLElement | null)?.focus();
  }

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (!drag.current) return;
    const v = at(e.clientX);
    if (drag.current === "either") {
      if (v === lo) return;
      drag.current = v < lo ? "lo" : "hi";
    }
    move(drag.current, v);
  }

  function onKeyDown(handle: "lo" | "hi", e: React.KeyboardEvent) {
    const current = handle === "lo" ? lo : hi;
    const keys: Record<string, number> = { ArrowLeft: current - 1, ArrowDown: current - 1, ArrowRight: current + 1, ArrowUp: current + 1, Home: 0, End: MAX_CONSTELLATION };
    if (!(e.key in keys)) return;
    e.preventDefault();
    move(handle, Math.min(MAX_CONSTELLATION, Math.max(0, keys[e.key])));
  }

  const left = (lo / MAX_CONSTELLATION) * 100, right = (hi / MAX_CONSTELLATION) * 100;
  const all = lo === 0 && hi === MAX_CONSTELLATION;
  const handle = (which: "lo" | "hi", v: number, label: string) => (
    <span role="slider" tabIndex={0} data-handle={which} className="chars-cons-thumb" style={{ left: `${(v / MAX_CONSTELLATION) * 100}%` }}
      aria-label={label} aria-valuemin={0} aria-valuemax={MAX_CONSTELLATION} aria-valuenow={v} aria-valuetext={`C${v}`}
      onKeyDown={(e) => onKeyDown(which, e)} />
  );
  return (
    <div className={`chars-cons-range${all ? "" : " active"}`}>
      <span className="player-label">
        {t("Constellations", "Созвездия")}: <b>{lo === hi ? `C${lo}` : `C${lo}–C${hi}`}</b>
        {!all && <button type="button" className="chars-cons-reset" onClick={() => setRange([0, MAX_CONSTELLATION])}>{t("all", "все")}</button>}
      </span>
      <div className="chars-cons-track" ref={track} onPointerDown={onPointerDown} onPointerMove={onPointerMove}
        onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
        <span className="chars-cons-fill" style={{ left: `${left}%`, width: `${right - left}%` }} />
        {handle("lo", lo, t("Lowest constellation", "Наименьшее созвездие"))}
        {handle("hi", hi, t("Highest constellation", "Наибольшее созвездие"))}
      </div>
      <div className="chars-cons-ticks" aria-hidden>
        {Array.from({ length: MAX_CONSTELLATION + 1 }, (_, c) => (
          <span key={c} className={c >= lo && c <= hi ? "in" : ""}>C{c}</span>
        ))}
      </div>
    </div>
  );
}

// A players count; hovering (or focusing) it loads and lists who picked the character and when, under the given
// filters. The table uses the page's filters; a constellation's row narrows them to that one constellation.
function PlayersPopover({ character, count, filters, label, className = "" }: {
  character: CharacterRow["character"]; count: number; filters: TableFilters; label?: string; className?: string;
}) {
  const { t, date, name } = useLang();
  const [list, setList] = useState<CharacterPlayer[] | null>(null);
  const [failed, setFailed] = useState(false);
  const key = JSON.stringify(filters);
  const loaded = useRef("");
  // New filters: the old list no longer matches.
  useEffect(() => { setList(null); setFailed(false); loaded.current = ""; }, [key]);

  function load() {
    if (loaded.current === key) return;
    loaded.current = key;
    fetchCharacterPlayers(character.id, filters).then(setList).catch(() => setFailed(true));
  }

  if (!count) return <span className={className}>{count === 0 ? "—" : count}</span>;
  const cons = (p: CharacterPlayer) => (p.min_constellation === p.max_constellation ? `C${p.min_constellation}`
    : `C${p.min_constellation}–C${p.max_constellation}`);
  const title = label ? `${name(character)} · ${label}` : name(character);
  return (
    <span className={`${className} chars-players`} tabIndex={0} onMouseEnter={load} onFocus={load}
      aria-label={t(`${count} players picked ${title}`, `${title}: пикали ${count} игроков`)}>
      <span className="chars-players-count">{count}</span>
      <div className="chars-players-pop" role="tooltip">
        <div className="chars-games-head">
          <b>{title}</b>
          <span className="player-label">{t(`${count} players`, `игроков: ${count}`)}</span>
        </div>
        <div className="chars-players-head player-label">
          <span>{t("Player", "Игрок")}</span><span>{t("Picks", "Пики")}</span><span>{t("WR", "ВР")}</span>
          <span>{t("Const.", "Конста")}</span><span>{t("When", "Когда")}</span>
        </div>
        <div className="chars-games-list">
          {failed ? <p className="player-message">{t("Couldn't load the players.", "Не удалось загрузить игроков.")}</p>
            : !list ? <p className="player-message">{t("Loading…", "Загрузка…")}</p>
            : list.map((p) => (
              <Link key={p.player.id} to={`/player/${p.player.id}?tab=characters`} className="chars-players-row"
                title={t(`${p.wins} won, ${p.losses} lost; latest at C${p.last_constellation}`, `${p.wins} побед, ${p.losses} поражений; последний раз на C${p.last_constellation}`)}>
                <b className="player-ellipsis">{p.player.name}</b>
                <span>{p.picks}</span>
                <span className={p.winrate == null ? "" : p.winrate >= 52 ? "is-good" : p.winrate <= 48 ? "is-bad" : ""}>{p.winrate == null ? "—" : `${p.winrate}%`}</span>
                <span>{cons(p)}</span>
                <small>{p.first.slice(0, 10) === p.last.slice(0, 10) ? date(p.last) : `${date(p.first)} – ${date(p.last)}`}</small>
              </Link>
            ))}
        </div>
      </div>
    </span>
  );
}

function PlayersCell({ row, filters }: { row: CharacterRow; filters: TableFilters }) {
  return <PlayersPopover character={row.character} count={row.players} filters={filters} className="hide-md" />;
}

// Opened under a character's row: its picks and winrate at each constellation.
function ConstellationPanel({ row, filters }: { row: CharacterRow; filters: TableFilters }) {
  const { t, name } = useLang();
  const [rows, setRows] = useState<ConstellationRow[] | null>(null);
  const [error, setError] = useState("");
  const key = JSON.stringify({ ...filters, constellations: undefined });
  useEffect(() => {
    const controller = new AbortController();
    setRows(null);
    setError("");
    fetchCharacterConstellations(row.character.id, filters, controller.signal)
      .then(setRows)
      .catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t("Couldn't load.", "Не удалось загрузить.")); });
    return () => controller.abort();
  }, [row.character.id, key]);
  const most = rows ? Math.max(1, ...rows.map((r) => r.picks)) : 1;
  return (
    <div className="chars-cons-panel">
      <div className="chars-cons-panel-head">
        <b>{name(row.character)}</b>
        <span className="player-label">{t("by constellation", "по созвездиям")}{filters.constellations ? ` · ${t("all constellations, whatever the slider", "все консты, независимо от слайдера")}` : ""}</span>
      </div>
      {error ? <p className="player-message">{error}</p>
        : !rows ? <p className="player-message">{t("Loading…", "Загрузка…")}</p>
        : (
          <div className="chars-cons-grid">
            <span className="player-label" /><span className="player-label">{t("Picks", "Пики")}</span>
            <span className="player-label">{t("Share", "Доля")}</span><span className="player-label">{t("Winrate", "Винрейт")}</span>
            <span className="player-label" title={t("Of the games where a player had it at this constellation, how often the opponent banned it",
              "Из игр, где у игрока он был на этой консте, как часто соперник его банил")}>{t("Ban rate", "Банрейт")}</span>
            <span className="player-label">{t("W–L", "П–П")}</span><span className="player-label">{t("Avg time", "Ср. время")}</span>
            <span className="player-label">{t("Players", "Игроки")}</span>
            {rows.map((r) => (
              <div className={`chars-cons-line${r.picks ? "" : " is-empty"}`} key={r.constellation}>
                <b className={`chars-cons-c c${r.constellation}`}>C{r.constellation}</b>
                <span className="chars-cons-picks">
                  <span className="chars-cons-bar" aria-hidden><span style={{ width: `${(r.picks / most) * 100}%` }} /></span>
                  {r.picks}
                </span>
                <span>{r.share == null || !r.picks ? "—" : `${r.share}%`}</span>
                <span className={r.winrate == null ? "" : r.winrate >= 52 ? "is-good" : r.winrate <= 48 ? "is-bad" : ""}>{r.winrate == null ? "—" : `${r.winrate}%`}</span>
                <span title={r.owned_games ? t(`Banned in ${r.banned_games} of ${r.owned_games} games where a player had it at C${r.constellation}`,
                  `Забанен в ${r.banned_games} из ${r.owned_games} игр, где у игрока он был на C${r.constellation}`) : undefined}>
                  {r.ban_rate == null ? "—" : `${r.ban_rate}%`}
                </span>
                <span>{r.wins + r.losses ? `${r.wins}–${r.losses}` : "—"}</span>
                <span>{r.avg_time == null ? "—" : `${r.avg_time}s`}</span>
                <PlayersPopover character={row.character} count={r.players} label={`C${r.constellation}`}
                  filters={{ ...filters, constellations: [r.constellation, r.constellation] }} />
              </div>
            ))}
          </div>
        )}
    </div>
  );
}

function value(row: CharacterRow, key: SortKey, name: (c: CharacterRow["character"]) => string) {
  return key === "name" ? name(row.character).toLowerCase() : row[key];
}

export function CharactersPage() {
  const [params, setParams] = useSearchParams();
  const { t, name } = useLang();
  const sort = (params.get("sort") as SortKey | null) ?? "presence";
  const ascending = params.get("dir") === "asc";
  const major = params.get("major") === "1";
  const prizeParam = params.get("prize");
  const prize: PrizeFilter = prizeParam === "versus" ? "versus" : prizeParam === "players" || prizeParam === "1" ? "players" : "";
  const sinceParam = params.get("since") ?? "";
  const since = /^\d{4}-\d{2}-\d{2}$/.test(sinceParam) ? sinceParam : "";
  const exclude = useMemo(() => (params.get("exclude") ?? "").split(",").filter(Boolean), [params]);
  const rarity = params.get("rarity") ?? "";
  const minPicks = Number(params.get("min") ?? "") || 0;
  const consMin = clampConstellation(params.get("cmin"), 0);
  const consMax = Math.max(consMin, clampConstellation(params.get("cmax"), MAX_CONSTELLATION));
  const consFiltered = consMin !== 0 || consMax !== MAX_CONSTELLATION;
  const tableFilters: TableFilters = useMemo(() => ({
    scope: major ? "major" : "all", since: since || undefined, exclude, prize,
    constellations: consFiltered ? [consMin, consMax] : undefined,
  }), [major, since, exclude.join(","), prize, consMin, consMax]);
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [data, setData] = useState<CharacterTable | null>(null);
  const [error, setError] = useState("");
  const [organizersOpen, setOrganizersOpen] = useState(exclude.length > 0);
  // The character whose constellation split is open (one at a time).
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    fetchCharacterTable(tableFilters, controller.signal)
      .then(setData)
      .catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t("Couldn't load the characters.", "Не удалось загрузить персонажей.")); });
    return () => controller.abort();
  }, [major, since, prize, consMin, consMax, exclude.join(",")]);

  // Applied to the live URL: React Router hands the function the params of the last render.
  function update(changes: Record<string, string>) {
    setParams(() => {
      const next = new URLSearchParams(window.location.search);
      for (const [key, v] of Object.entries(changes)) {
        if (v) next.set(key, v);
        else next.delete(key);
      }
      return next;
    }, { replace: true });
  }

  function toggleOrganizer(id: string) {
    const next = exclude.includes(id) ? exclude.filter((x) => x !== id) : [...exclude, id];
    update({ exclude: next.join(",") });
  }

  function sortBy(key: SortKey) {
    const column = COLUMNS.find((c) => c.key === key)!;
    update({ sort: key, dir: (key === sort ? !ascending : Boolean(column.ascending)) ? "asc" : "desc" });
  }

  const rows = useMemo(() => {
    if (!data) return [];
    const needle = search.trim().toLowerCase();
    const filtered = data.characters.filter((c) =>
      (!needle || c.character.name.toLowerCase().includes(needle) || (c.character.name_ru ?? "").toLowerCase().includes(needle))
      && (!rarity || String(c.character.rarity) === rarity) && c.picks >= minPicks);
    // Rows without the value (never picked: no winrate) always go last.
    return [...filtered].sort((a, b) => {
      const x = value(a, sort, name), y = value(b, sort, name);
      if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
      const order = x < y ? -1 : x > y ? 1 : 0;
      return ascending ? order : -order;
    });
  }, [data, search, rarity, minPicks, sort, ascending, name]);

  const pct = (v: number | null) => (v == null ? "—" : `${v}%`);
  const excludedNames = data?.organizers.filter((o) => o.excluded).map((o) => o.name) ?? [];

  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="player-content match-content">
            <div className="player-box chars-filters">
              <div className="chars-filter-row">
                <input className="match-input chars-filter-search" type="search" value={search} placeholder={t("Character", "Персонаж")}
                  aria-label={t("Find a character", "Найти персонажа")} onChange={(e) => { setSearch(e.target.value); update({ q: e.target.value.trim() }); }} />
                <select className="match-input" value={rarity} aria-label={t("Rarity", "Редкость")} onChange={(e) => update({ rarity: e.target.value })}>
                  <option value="">{t("Any rarity", "Любая редкость")}</option>
                  <option value="5">5★</option>
                  <option value="4">4★</option>
                </select>
                <label className="chars-filter-label">
                  <span className="player-label">{t("Min picks", "Мин. пиков")}</span>
                  <input className="match-input chars-filter-number" type="number" min={0} inputMode="numeric" value={params.get("min") ?? ""}
                    placeholder="0" onChange={(e) => update({ min: e.target.value })} />
                </label>
                <label className="chars-filter-label">
                  <span className="player-label">{t("Count from", "Считать с")}</span>
                  <input className="match-input" type="date" value={since} max={new Date().toISOString().slice(0, 10)}
                    title={t("Only tournaments that started on or after this day", "Только турниры, начавшиеся с этого дня")} onChange={(e) => update({ since: e.target.value })} />
                </label>
                <MajorToggle on={major} onChange={(on) => update({ major: on ? "1" : "" })} />
                <span className="player-segment chars-prize" role="group" aria-label={t("Whose games count", "Чьи игры считать")}>
                  {PRIZE_OPTIONS.map((o) => (
                    <button type="button" key={o.value} className={`player-control${prize === o.value ? " active" : ""}`} aria-pressed={prize === o.value}
                      title={t(...o.title)} onClick={() => update({ prize: o.value })}>
                      {t(...o.label)}{o.value && data ? ` · ${data.prize_players}` : ""}
                    </button>
                  ))}
                </span>
                <button type="button" className={`player-control${organizersOpen || exclude.length ? " active" : ""}`} aria-expanded={organizersOpen}
                  onClick={() => setOrganizersOpen(!organizersOpen)}>
                  {t("Organizers", "Организаторы")}{exclude.length ? ` · −${exclude.length}` : ""}
                </button>
              </div>
              <ConstellationRange value={[consMin, consMax]}
                onChange={([lo, hi]) => update({ cmin: lo ? String(lo) : "", cmax: hi !== MAX_CONSTELLATION ? String(hi) : "" })} />
              {organizersOpen && data && (
                <div className="chars-organizers">
                  <span className="player-label">{t("Count tournaments by:", "Учитывать турниры организаторов:")}</span>
                  {data.organizers.map((o) => (
                    <label key={o.id} className={`chars-organizer${o.excluded ? " is-excluded" : ""}`}>
                      <input type="checkbox" checked={!o.excluded} onChange={() => toggleOrganizer(o.id)} />
                      {o.id === "unknown" ? t("Unknown organizer", "Неизвестный организатор") : o.name}
                      <small>{o.tournaments}</small>
                    </label>
                  ))}
                  {exclude.length > 0 && <button type="button" className="player-control" onClick={() => update({ exclude: "" })}>{t("Count everyone", "Учитывать всех")}</button>}
                </div>
              )}
            </div>

            {error ? <div className="player-box player-message">{error}</div>
              : !data ? <div className="player-box player-message">{t("Loading characters…", "Загрузка персонажей…")}</div>
              : (
                <section className="player-box">
                  <h2 className="player-box-title chars-summary">
                    <span>{t("Characters", "Персонажи")} · {rows.length}</span>
                    <small className="player-label">
                      {t(`${data.games} games · ${data.tournaments} tournaments`, `${data.games} игр · ${data.tournaments} турниров`)}
                      {consFiltered && ` · ${t("picks at", "пики на")} ${consMin === consMax ? `C${consMin}` : `C${consMin}–C${consMax}`} (${t("bans: all", "баны: все")})`}
                      {prize === "players" && ` · ${t("prize winners only", "только призёры")}`}
                      {prize === "versus" && ` · ${t("prize winners against prize winners", "призёры против призёров")}`}
                      {excludedNames.length > 0 && ` · ${t("without", "без")} ${excludedNames.join(", ")}`}
                    </small>
                  </h2>
                  <div className="chars-table-row chars-table-head">
                    <span />
                    {COLUMNS.map((c) => (
                      <button type="button" key={c.key} className={`players-sort${sort === c.key ? " is-sorted" : ""} ${c.className ?? ""}`}
                        title={t(...c.title) || undefined} onClick={() => sortBy(c.key)}>
                        {t(...c.label)}{sort === c.key ? (ascending ? " ↑" : " ↓") : ""}
                      </button>
                    ))}
                    <span className="players-sort hide-md">{t("Top player", "Чаще всех")}</span>
                  </div>
                  {rows.map((c) => (
                    <div key={c.character.id} className="chars-table-item">
                    <div className={`chars-table-row is-clickable${openId === c.character.id ? " is-open" : ""}`} role="button" tabIndex={0}
                      aria-expanded={openId === c.character.id}
                      title={t("Show constellations", "Показать по констам")}
                      onClick={(e) => { if (!(e.target as HTMLElement).closest("a, .chars-players")) setOpenId(openId === c.character.id ? null : c.character.id); }}
                      onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && e.target === e.currentTarget) { e.preventDefault(); setOpenId(openId === c.character.id ? null : c.character.id); } }}>
                      {c.character.icon ? <img src={c.character.icon} alt="" width={30} height={30} loading="lazy" className={`chars-table-icon rarity-${c.character.rarity ?? 4}`} /> : <span className="chars-table-icon" />}
                      <b className="player-ellipsis">{name(c.character)}</b>
                      <span className="chars-presence">
                        <span>{pct(c.presence)}</span>
                        <span className="chars-presence-bar" aria-hidden><span style={{ width: `${c.presence ?? 0}%` }} /></span>
                      </span>
                      <span>{pct(c.pick_rate)}</span>
                      <span>{pct(c.ban_rate)}</span>
                      <span className={c.winrate == null ? "" : c.winrate >= 52 ? "is-good" : c.winrate <= 48 ? "is-bad" : ""}
                        title={t(`${c.wins} won, ${c.losses} lost`, `${c.wins} побед, ${c.losses} поражений`)}>
                        {pct(c.winrate)}
                      </span>
                      <span className="hide-sm">{c.picks}</span>
                      <span className="hide-sm">{c.bans}</span>
                      <span className="hide-xs">{c.avg_constellation == null ? "—" : `C${c.avg_constellation.toFixed(1)}`}</span>
                      <span className="hide-md">{c.avg_time == null ? "—" : `${c.avg_time}s`}</span>
                      <PlayersCell row={c} filters={tableFilters} />
                      <span className="hide-md chars-top">
                        {c.top_player ? <Link className="player-match-link player-ellipsis" to={`/player/${c.top_player.id}?tab=characters`}
                          title={t(`${c.top_player.picks} picks · ${c.top_player.winrate ?? "—"}% winrate`, `${c.top_player.picks} пиков · винрейт ${c.top_player.winrate ?? "—"}%`)}>
                          {c.top_player.name}<small className="player-label"> ×{c.top_player.picks}</small></Link> : "—"}
                      </span>
                    </div>
                    {openId === c.character.id && <ConstellationPanel row={c} filters={tableFilters} />}
                    </div>
                  ))}
                  {rows.length === 0 && <p className="player-message">{t("No characters match the filters.", "Нет персонажей под эти фильтры.")}</p>}
                </section>
              )}
          </div>
        </div>
      </div>
    </main>
  );
}
