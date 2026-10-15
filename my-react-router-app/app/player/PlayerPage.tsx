import { useEffect, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { MajorToggle } from "./MajorToggle";
import { SuggestBox } from "../suggestions/SuggestBox";
import { useLang } from "../i18n";
import { fetchPlayer, fetchRosters, type CharacterCount, type CharacterRate, type Finish, type PlayedTournament, type PlayerDetail, type PlayerMatch, type RosterVersion, type Split } from "./api";
import "./player-page.css";
import "../match/match-page.css";
import "../home/gitv-preview.css";

const tabs = ["stats", "matches", "tournaments"] as const;
type Tab = (typeof tabs)[number];
const TAB_LABELS: Record<Tab, [string, string]> = { stats: ["Stats", "Статистика"], matches: ["Matches", "Матчи"], tournaments: ["Tournaments", "Турниры"] };

const GAMES: [[string, string], [string, string, string]] = [["game", "games"], ["игра", "игры", "игр"]];
const TOURNAMENTS: [[string, string], [string, string, string]] = [["tournament", "tournaments"], ["турнир", "турнира", "турниров"]];
const PLACE_LABELS: [string, string][] = [["1st", "1-е"], ["2nd", "2-е"], ["3rd", "3-е"], ["4th", "4-е"]];

type L = ReturnType<typeof useLang>;

function StatRow({ label, value }: { label: string; value: ReactNode }) {
  return <div className="player-stat-row"><span className="player-label">{label}</span><strong className="player-value">{value}</strong></div>;
}

function StatBox({ title, children }: { title: string; children: ReactNode }) {
  return <section className="player-box"><h2 className="player-box-title">{title}</h2>{children}</section>;
}

function StatRows({ rows }: { rows: [string, ReactNode][] }) {
  return <div className="player-box-body">{rows.map(([label, value]) => <StatRow key={label} label={label} value={value} />)}</div>;
}

function seconds(l: L, value: number | null) {
  return value == null ? "—" : `${value}${l.t("s", "с")}`;
}

function characterCount(l: L, item: CharacterCount | null) {
  return item ? `${l.name(item.character)} · ${l.count(item.games, ...GAMES)}` : "—";
}

function characterRate(l: L, item: CharacterRate | null) {
  return item ? `${l.name(item.character)} · ${item.winrate}% · ${l.count(item.games, ...GAMES)}` : "—";
}

// W / L in English, В (выигрыш) / П (поражение) in Russian.
function wl(l: L, wins: number, losses: number) {
  return l.t(`${wins}W / ${losses}L`, `${wins}В / ${losses}П`);
}

function split(l: L, s: Split) {
  return s.winrate == null ? "—" : `${s.winrate}% · ${wl(l, s.wins, s.losses)}`;
}

// Top-4 places, newest first: gold, silver, bronze, grey.
function Placements({ finishes }: { finishes: Finish[] }) {
  const l = useLang();
  return (
    <StatBox title={l.t("Placements", "Призовые места")}>
      {finishes.length ? (
        <div className="player-places">
          {finishes.map((f) => (
            <Link className="player-place" to={`/matches?tournament=${f.tournament.id}`} key={f.tournament.id}
              title={`${l.t(...PLACE_LABELS[f.place - 1])} ${l.t("place", "место")} · ${l.date(f.date)}`}>
              <span className={`player-place-badge place-${f.place}`}>{f.place}</span>
              <span className="player-ellipsis">{f.tournament.title}</span>
            </Link>
          ))}
        </div>
      ) : <div className="player-box-body player-label">{l.t("No top-4 places yet.", "Мест в топ-4 пока нет.")}</div>}
    </StatBox>
  );
}

// How many 1st/2nd/3rd/4th places, each count inside a badge of its medal colour. Hovering (or focusing)
// a badge lists the tournaments finished in that place.
function TopFour({ player }: { player: PlayerDetail }) {
  const l = useLang();
  return (
    <span className="player-top4">
      {PLACE_LABELS.map((pair, i) => {
        const label = `${l.t(...pair)} ${l.t("place", "место")}`;
        const finishes = player.finishes.filter((f) => f.place === i + 1);
        const badge = <span className={`player-place-badge place-${i + 1}${finishes.length ? "" : " is-zero"}`}>{finishes.length}</span>;
        if (!finishes.length) return <span key={pair[0]} title={`${label} × 0`} aria-label={`${label}: 0`}>{badge}</span>;
        return (
          <span className="player-top4-item" key={pair[0]}>
            <button type="button" className="player-top4-button" aria-label={`${label}: ${finishes.length}. ${l.t("Show tournaments", "Показать турниры")}`}>{badge}</button>
            <span className="player-top4-popover" role="tooltip">
              <span className="player-top4-heading">{label} · {l.count(finishes.length, ...TOURNAMENTS)}</span>
              {finishes.map((f) => (
                <Link className="player-top4-row" to={`/matches?tournament=${f.tournament.id}`} key={f.tournament.id}>
                  <span className="player-ellipsis">{f.tournament.title}</span>
                  <span className="gitv-date">{l.date(f.date)}</span>
                </Link>
              ))}
            </span>
          </span>
        );
      })}
    </span>
  );
}

// Pick one tournament the player played to see only its statistics; places show next to the titles.
function TournamentPicker({ tournaments, value, onChange }: { tournaments: PlayedTournament[]; value: string; onChange: (id: string) => void }) {
  const l = useLang();
  const { t } = l;
  return (
    <select className="player-major player-tournament-pick" aria-label={t("Tournament", "Турнир")} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{t("All tournaments", "Все турниры")}</option>
      {tournaments.map((item) => (
        <option value={item.id} key={item.id}>
          {item.title} · {l.date(item.date)}{item.place ? ` · ${t(...PLACE_LABELS[item.place - 1])} ${t("place", "место")}` : ""}
        </option>
      ))}
    </select>
  );
}

// Records strip under the nickname.
function Records({ player }: { player: PlayerDetail }) {
  const l = useLang();
  const times = player.times;
  const items: [string, ReactNode][] = [
    [l.t("Best time", "Лучшее время"), times.best_match_id ? <Link className="player-match-link" to={`/match/${times.best_match_id}`}>{seconds(l, times.best)}</Link> : "—"],
    [l.t("Tournament wins", "Победы в турнирах"), player.finishes.filter((f) => f.place === 1).length],
    [l.t("Top 4 finishes", "Места в топ-4"), <TopFour player={player} />],
    [l.t("Tournaments", "Турниры"), player.tournaments],
  ];
  return (
    <div className="player-records">
      {items.map(([label, value]) => (
        <div className="player-record" key={label}>
          <span className="player-label">{label}</span>
          <strong className="player-value">{value}</strong>
        </div>
      ))}
    </div>
  );
}

function resultLetter(l: L, result: string) {
  return result === "W" ? l.t("W", "В") : result === "L" ? l.t("L", "П") : result === "D" ? l.t("D", "Н") : "–";
}

function GameChip({ result }: { result: string }) {
  const l = useLang();
  const kind = result === "W" ? "win" : result === "L" ? "loss" : "";
  return <span className={`player-game ${kind}`}>{resultLetter(l, result)}</span>;
}

type Sort = "new" | "old" | "fast" | "slow";
type ResultFilter = "" | "W" | "L";
type ListOptions = { sort: Sort; result: ResultFilter; complete: boolean };

const SORTS: { value: Sort; label: [string, string] }[] = [
  { value: "new", label: ["Newest first", "Сначала новые"] },
  { value: "old", label: ["Oldest first", "Сначала старые"] },
  { value: "fast", label: ["Fastest time", "Быстрее всего"] },
  { value: "slow", label: ["Slowest time", "Медленнее всего"] },
];

// Matches tab: sort by date or average clear time, wins or losses only, hide incomplete matches.
function filterAndSort<T extends { date: string; result: string; technical: boolean }>(items: T[], time: (item: T) => number | null, o: ListOptions) {
  const shown = items.filter((item) => (!o.result || item.result === o.result) && (!o.complete || (!item.technical && time(item) != null)));
  return shown.sort((a, b) => {
    if (o.sort === "new" || o.sort === "old") {
      const order = a.date < b.date ? -1 : a.date > b.date ? 1 : 0;
      return o.sort === "old" ? order : -order;
    }
    // Rows without a time always go last.
    const x = time(a), y = time(b);
    if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
    return o.sort === "fast" ? x - y : y - x;
  });
}

function ListControls({ options, onChange, total, shown }: { options: ListOptions; onChange: (changes: Record<string, string>) => void; total: number; shown: number }) {
  const { t } = useLang();
  const results: [ResultFilter, string][] = [["", t("All", "Все")], ["W", t("Wins", "Победы")], ["L", t("Losses", "Поражения")]];
  return (
    <div className="player-controls">
      <select className="player-control" aria-label={t("Sort", "Сортировка")} value={options.sort} onChange={(e) => onChange({ sort: e.target.value === "new" ? "" : e.target.value })}>
        {SORTS.map((s) => <option value={s.value} key={s.value}>{t(...s.label)}</option>)}
      </select>
      <div className="player-segment" role="group" aria-label={t("Result", "Результат")}>
        {results.map(([value, label]) => (
          <button type="button" key={value || "all"} className={`player-control${options.result === value ? " active" : ""}`} aria-pressed={options.result === value} onClick={() => onChange({ result: value })}>{label}</button>
        ))}
      </div>
      <label className="player-check">
        <input type="checkbox" checked={options.complete} onChange={(e) => onChange({ complete: e.target.checked ? "1" : "" })} />
        {t("Hide incomplete", "Скрыть неполные")}
      </label>
      <span className="player-label player-controls-count">{shown === total ? total : `${shown} ${t("of", "из")} ${total}`}</span>
    </div>
  );
}

function MatchList({ player, options, onChange }: { player: PlayerDetail; options: ListOptions; onChange: (changes: Record<string, string>) => void }) {
  const l = useLang();
  const { t } = l;
  const matches = filterAndSort<PlayerMatch>([...player.match_list], (m) => m.avg_time, options);
  return (
    <StatBox title={t("Matches", "Матчи")}>
      <ListControls options={options} onChange={onChange} total={player.match_list.length} shown={matches.length} />
      <div className="player-match player-match-head">
        <span>{t("Date", "Дата")}</span><span>{t("Opponent", "Соперник")}</span><span>{t("Tournament", "Турнир")}</span>
        <span>{t("Score", "Счёт")}</span><span>{t("Avg time", "Ср. время")}</span><span>{t("Result", "Итог")}</span>
      </div>
      {matches.map((m) => (
        <div className="player-match" key={m.match_id}>
          <Link className="gitv-date player-match-link" to={`/match/${m.match_id}`}>{l.date(m.date)}</Link>
          <span className="player-ellipsis">{m.opponent ? <Link className="player-match-link" to={`/player/${m.opponent.id}`}>{m.opponent.name}</Link> : "—"}</span>
          <Link className="player-label player-ellipsis player-match-link" to={`/match/${m.match_id}`}>{m.tournament}{m.technical ? t(" · incomplete", " · неполный") : ""}</Link>
          <span>{m.games_won} – {m.games_lost}</span>
          <span>{seconds(l, m.avg_time)}</span>
          <GameChip result={m.result} />
        </div>
      ))}
      {!matches.length && <div className="player-box-body player-label">{t("No matches match these filters.", "Под эти фильтры матчей нет.")}</div>}
    </StatBox>
  );
}

// A yes/no choice kept in the browser (a roster view preference); false when storage is unavailable.
function useStoredFlag(key: string): [boolean, () => void] {
  const [on, setOn] = useState(() => {
    try { return localStorage.getItem(key) === "1"; } catch { return false; }
  });
  function toggle() {
    const next = !on;
    setOn(next);
    try { localStorage.setItem(key, next ? "1" : ""); } catch { /* storage unavailable: just this view */ }
  }
  return [on, toggle];
}

function FreeToggle({ hidden, count, onToggle }: { hidden: boolean; count: number; onToggle: () => void }) {
  const { t } = useLang();
  return (
    <button type="button" className={`player-control${hidden ? " active" : ""}`} aria-pressed={hidden} onClick={onToggle}>
      {hidden ? t(`Show 0-cost (${count})`, `Показать с костом 0 (${count})`) : t(`Hide 0-cost (${count})`, `Скрыть с костом 0 (${count})`)}
    </button>
  );
}

// A tournament's roster under its row: characters strongest first, then weapons; a version switch when it
// changed mid-tournament.
function RosterPanel({ playerId, tournamentId }: { playerId: string; tournamentId: string }) {
  const l = useLang();
  const { t } = l;
  const [versions, setVersions] = useState<RosterVersion[] | null>(null);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState(0);
  // Characters and weapons that cost 0 in the tournament's system can be hidden, each on its own switch;
  // the choices stick across rosters.
  const [hideFree, toggleFree] = useStoredFlag("gitv-roster-hide-free");
  const [hideFreeWeapons, toggleFreeWeapons] = useStoredFlag("gitv-roster-hide-free-weapons");

  useEffect(() => {
    const controller = new AbortController();
    fetchRosters(playerId, tournamentId, controller.signal)
      .then((list) => { setVersions(list); setPicked(list.length - 1); })
      .catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t("Couldn't load the roster.", "Не удалось загрузить ростер.")); });
    return () => controller.abort();
  }, [playerId, tournamentId]);

  if (error) return <div className="roster-panel player-label">{error}</div>;
  if (!versions) return <div className="roster-panel player-label">{t("Loading roster…", "Загрузка ростера…")}</div>;
  const v = versions[picked];
  const free = v.characters.filter((c) => c.cost === 0).length;
  const shown = hideFree ? v.characters.filter((c) => c.cost !== 0) : v.characters;
  const freeWeapons = v.weapons.filter((w) => w.cost === 0).reduce((n, w) => n + w.count, 0);
  const shownWeapons = hideFreeWeapons ? v.weapons.filter((w) => w.cost !== 0) : v.weapons;
  const allWeapons = v.weapons.reduce((n, w) => n + w.count, 0);
  const weaponCount = shownWeapons.reduce((n, w) => n + w.count, 0);
  return (
    <div className="roster-panel">
      {versions.length > 1 && (
        <div className="roster-versions" role="group" aria-label={t("Roster version", "Версия ростера")}>
          <span className="player-label">{t("Changed during the tournament:", "Менялся по ходу турнира:")}</span>
          {versions.map((item, i) => (
            <button type="button" key={item.version} className={`player-control${i === picked ? " active" : ""}`} aria-pressed={i === picked} onClick={() => setPicked(i)}>
              {t(`Version ${item.version}`, `Версия ${item.version}`)} · {l.count(item.games, ...GAMES)}
            </button>
          ))}
        </div>
      )}
      <div className="roster-heading roster-heading--row">
        <span className="player-label">{t("Characters by cost", "Персонажи по косту")} · {shown.length === v.characters.length ? v.characters.length : `${shown.length} ${t("of", "из")} ${v.characters.length}`}</span>
        {free > 0 && <FreeToggle hidden={hideFree} count={free} onToggle={toggleFree} />}
      </div>
      <div className="roster-grid">
        {shown.map((c) => (
          <span className="roster-item" key={c.character.id} title={`${l.name(c.character)} · C${c.constellation}${c.level ? ` · Lv ${c.level}` : ""}${c.cost != null ? ` · ${t("cost", "кост")} ${c.cost}` : ""}`}>
            <span className="match-member-art">
              {c.character.icon ? <img className={`match-portrait rarity-${c.character.rarity ?? 4}`} src={c.character.icon} alt="" width={40} height={40} loading="lazy" /> : <span className="match-portrait" />}
              <span className="match-badge">C{c.constellation}</span>
            </span>
            <span className="roster-name">{l.name(c.character)}</span>
            <span className="roster-cost">{c.cost ?? "—"}</span>
          </span>
        ))}
      </div>
      <div className="roster-heading roster-heading--row">
        <span className="player-label">{t("Weapons by cost", "Оружие по косту")} · {weaponCount === allWeapons ? allWeapons : `${weaponCount} ${t("of", "из")} ${allWeapons}`}</span>
        {freeWeapons > 0 && <FreeToggle hidden={hideFreeWeapons} count={freeWeapons} onToggle={toggleFreeWeapons} />}
      </div>
      <div className="roster-grid roster-grid--weapons">
        {shownWeapons.map((w) => (
          <span className="roster-item" key={`${w.weapon.id}-${w.refinement}-${w.level}`} title={`${l.name(w.weapon)} · R${w.refinement ?? "?"}${w.count > 1 ? ` × ${w.count}` : ""}${w.cost != null ? ` · ${t("cost", "кост")} ${w.cost}` : ""}`}>
            <span className="match-member-art">
              {w.weapon.icon ? <img className={`match-portrait rarity-${w.weapon.rarity ?? 4}`} src={w.weapon.icon} alt="" width={34} height={34} loading="lazy" /> : <span className="match-portrait" />}
              <span className="match-badge">R{w.refinement ?? "?"}{w.count > 1 ? `×${w.count}` : ""}</span>
            </span>
            <span className="roster-cost">{w.cost ?? "—"}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// Brackets show the place (a medal for the top four, a tier like 5-8 below); group stages show the match score.
function PlaceOrScore({ item }: { item: PlayedTournament }) {
  const { t } = useLang();
  if (item.kind === "bracket" && item.place_range) {
    const [low, high] = item.place_range;
    if (low === high && low <= 4) {
      return <span className="player-tourney-place"><span className={`player-place-badge place-${low}`}>{low}</span>{t(...PLACE_LABELS[low - 1])} {t("place", "место")}</span>;
    }
    return <span>{low === high ? low : `${low}–${high}`} {t("place", "место")}</span>;
  }
  return <span>{item.wins} – {item.losses}</span>;
}

// Third tab: every tournament the player played, the place (or group score), qualifiers passed or not, roster.
function TournamentList({ player, playerId }: { player: PlayerDetail; playerId: string }) {
  const l = useLang();
  const { t } = l;
  const [open, setOpen] = useState<string | null>(null);
  const QUAL: Record<string, [string, string]> = { passed: ["Qualified", "Прошёл"], failed: ["Eliminated", "Не прошёл"], pending: ["Pending", "Ожидается"] };
  return (
    <StatBox title={`${t("Tournaments", "Турниры")} · ${player.tournament_list.length}`}>
      <div className="player-tourney player-match-head">
        <span>{t("Date", "Дата")}</span><span>{t("Tournament", "Турнир")}</span><span>{t("Place / score", "Место / счёт")}</span>
        <span>{t("Qualifiers", "Квалы")}</span><span />
      </div>
      {player.tournament_list.map((item) => (
        <div key={item.id}>
          <div className="player-tourney">
            <span className="gitv-date">{l.date(item.date)}</span>
            <Link className="player-ellipsis player-match-link" to={`/matches?tournament=${item.id}`}>{item.title}</Link>
            <PlaceOrScore item={item} />
            <span>{item.qualification ? <span className={`player-qual ${item.qualification}`}>{t(...QUAL[item.qualification])}</span> : null}</span>
            <span className="player-tourney-roster">
              {item.rosters > 0 && (
                <button type="button" className={`player-control${open === item.id ? " active" : ""}`} aria-expanded={open === item.id}
                  onClick={() => setOpen(open === item.id ? null : item.id)}>
                  {t("Roster", "Ростер")}{item.rosters > 1 ? ` · ${item.rosters}` : ""}
                </button>
              )}
            </span>
          </div>
          {open === item.id && <RosterPanel playerId={playerId} tournamentId={item.id} />}
        </div>
      ))}
    </StatBox>
  );
}

function Stats({ player }: { player: PlayerDetail }) {
  const l = useLang();
  const { t } = l;
  const times = player.times;
  return (
    <div className="player-columns">
      <aside className="player-column">
        <StatBox title={t("Streaks", "Серии")}>
          <StatRows rows={[[t("Highest winstreak", "Лучшая серия побед"), player.highest_winstreak], [t("Current winstreak", "Текущая серия побед"), player.current_winstreak]]} />
        </StatBox>
        <StatBox title={t("Last 10 games", "Последние 10 игр")}>
          {player.last_games.length
            ? (
              <div className="player-games player-games-line">
                {player.last_games.map((game, index) => (
                  <Link className={`player-game ${game.result === "W" ? "win" : game.result === "L" ? "loss" : ""}`} to={`/match/${game.match_id}`} key={index}
                    title={`${l.date(game.date)} · ${t("game", "игра")} ${game.game_no}`}
                    aria-label={`${game.result === "W" ? t("Win", "Победа") : game.result === "L" ? t("Loss", "Поражение") : t("Draw", "Ничья")}, ${t("game", "игра")} ${game.game_no}, ${t("open match", "открыть матч")}`}>
                    {resultLetter(l, game.result)}
                  </Link>
                ))}
              </div>
            )
            : <div className="player-box-body player-label">{t("No decided games yet.", "Сыгранных игр с результатом пока нет.")}</div>}
        </StatBox>
        <Placements finishes={player.finishes} />
      </aside>
      <div className="player-column">
        <StatBox title={t("Characters", "Персонажи")}>
          <StatRows rows={[
            [t("Highest winrate character", "Лучший винрейт"), characterRate(l, player.highest_winrate_character)],
            [t("Lowest winrate character", "Худший винрейт"), characterRate(l, player.lowest_winrate_character)],
          ]} />
        </StatBox>
        <StatBox title={t("Results", "Результаты")}>
          <StatRows rows={[
            [t("Matches", "Матчи"), `${player.matches} · ${player.match_winrate ?? "—"}% ${t("won", "побед")}`],
            [t("Winrate", "Винрейт"), player.winrate == null ? "—" : `${player.winrate}% · ${wl(l, player.wins, player.losses)}`],
            [t("First pick winrate", "Винрейт на первом пике"), split(l, player.first_pick)],
            [t("Second pick winrate", "Винрейт на втором пике"), split(l, player.second_pick)],
            [t("Technical lose rate", "Доля тех. поражений"), `${player.tech_loss_rate ?? 0}% · ${player.tech_losses} ${t("of", "из")} ${l.count(player.games, ...GAMES)}`],
          ]} />
        </StatBox>
      </div>
      <aside className="player-column">
        <StatBox title={t("Times", "Время")}>
          <div className="player-box-body">
            <StatRow label={t("Average time", "Среднее время")} value={seconds(l, times.average)} />
            <StatRow label={t("Average win time", "Среднее в победах")} value={seconds(l, times.average_win)} />
            <StatRow label={t("Average loss time", "Среднее в поражениях")} value={seconds(l, times.average_loss)} />
            <div className="player-row-gap" />
            <StatRow label={t("Average first pick time", "Среднее на первом пике")} value={seconds(l, times.average_first_pick)} />
            <StatRow label={t("Average second pick time", "Среднее на втором пике")} value={seconds(l, times.average_second_pick)} />
          </div>
        </StatBox>
        <p className="player-note player-label">
          {/* Russian: "по 1 игре / по 3 играм / по 61 игре" (dative), so the number and noun always agree. */}
          {t(`Times come from ${l.count(times.counted_games, ...GAMES)}; technical games are left out.`,
             `Время посчитано по ${l.count(times.counted_games, ["game", "games"], ["игре", "играм", "играм"])}; технические игры не учитываются.`)}
        </p>
      </aside>
    </div>
  );
}

export function PlayerPage({ playerId }: { playerId: string }) {
  const l = useLang();
  const { t } = l;
  const [params, setParams] = useSearchParams();
  const tab: Tab = tabs.find((name) => name === params.get("tab")) ?? "stats";
  const options: ListOptions = {
    sort: (SORTS.find((s) => s.value === params.get("sort"))?.value ?? "new"),
    result: params.get("result") === "W" || params.get("result") === "L" ? (params.get("result") as ResultFilter) : "",
    complete: params.get("complete") === "1",
  };

  function update(changes: Record<string, string>) {
    // React Router hands the function the params of the last render, so read the live URL instead.
    setParams(() => {
      const next = new URLSearchParams(window.location.search);
      for (const [key, value] of Object.entries(changes)) {
        if (value) next.set(key, value);
        else next.delete(key);
      }
      return next;
    }, { replace: true });
  }

  const setTab = (name: Tab) => update({ tab: name === "stats" ? "" : name });
  const major = params.get("major") === "1";
  const tournament = params.get("tournament") ?? "";
  // The picker's list comes with the player; kept so it stays filled while another tournament loads.
  const [tournaments, setTournaments] = useState<PlayedTournament[]>([]);
  const [player, setPlayer] = useState<PlayerDetail | null>(null);
  // Bumped after a profile edit to load the player again.
  const [version, setVersion] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    if (!version) setPlayer(null);
    setError("");
    fetchPlayer(playerId, controller.signal, major ? "major" : "all", tournament || undefined)
      .then((data) => { setPlayer(data); setTournaments(data.tournament_list); })
      .catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t("Couldn't load the player.", "Не удалось загрузить игрока.")); });
    return () => controller.abort();
  }, [playerId, major, tournament, version]);

  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="player-content">
            <div className="player-scope">
              {tournaments.length > 0 && <TournamentPicker tournaments={tournaments} value={tournament} onChange={(id) => update({ tournament: id })} />}
              {/* A single tournament already narrows everything down, so the majors switch only applies to "all". */}
              {!tournament && <MajorToggle on={major} onChange={(on) => update({ major: on ? "1" : "" })} />}
            </div>
            {error ? <p className="player-box player-message">{error}</p>
              : !player ? <p className="player-box player-message">{t("Loading player…", "Загрузка игрока…")}</p>
              : <>
                  <header className="player-box player-header">
                    <div className="player-identity">
                      {player.profile?.avatar_url && <img className="player-avatar" src={player.profile.avatar_url} alt="" width={72} height={72} />}
                      <div className="player-identity-text">
                        <div className="player-nickname">{player.name}</div>
                        {(player.profile?.real_name || player.profile?.age != null) && (
                          <div className="player-realname">
                            {[player.profile.real_name, player.profile.age != null ? l.count(player.profile.age, ["y.o.", "y.o."], ["год", "года", "лет"]) : null].filter(Boolean).join(" · ")}
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="player-fullname">{player.other_names.length ? `${t("Also played as", "Также играл как")} ${player.other_names.join(", ")}` : " "}</div>
                    <Records player={player} />
                    <StatRow label={t("Most picked character", "Чаще всего берёт")} value={characterCount(l, player.most_picked)} />
                    <StatRow label={t("Most banned character by opponent", "Чаще всего банят соперники")} value={characterCount(l, player.most_banned_against)} />
                  </header>

                  <div className="player-tabs" role="tablist" aria-label={t("Player sections", "Разделы игрока")}>
                    {tabs.map((name) => (
                      <button type="button" role="tab" aria-selected={tab === name} className={`player-tab${tab === name ? " active" : ""}`} onClick={() => setTab(name)} key={name}>{t(...TAB_LABELS[name])}</button>
                    ))}
                  </div>

                  {tab === "matches" ? <MatchList player={player} options={options} onChange={update} />
                    : tab === "tournaments" ? <TournamentList player={player} playerId={playerId} />
                    : <Stats player={player} />}
                  <SuggestBox playerId={playerId} playerName={player.name} profile={player.profile} history={player.profile_history}
                    onEdited={() => setVersion((v) => v + 1)} />
                </>}
          </div>
        </div>
      </div>
    </main>
  );
}
