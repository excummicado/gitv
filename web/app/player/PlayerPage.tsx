import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { MajorToggle } from "./MajorToggle";
import { useLang } from "../i18n";
import { EloBadge } from "../components/EloBadge";
import { distinctNames, fetchPlayer, type CharacterCount, type PlayedTournament, type PlayerDetail } from "./api";
import "./player-page.css";
import "./compare.css";
import { CharactersTab } from "./CharactersTab";
import { MatchList, SORTS, type ListOptions, type ResultFilter } from "./MatchesTab";
import { StatsTab } from "./StatsTab";
import { TournamentList } from "./TournamentsTab";
import { GAMES, PLACE_LABELS, StatRow, seconds, type L } from "./playerParts";
import { Nick } from "../components/PlayerNick";

const tabs = ["stats", "matches", "tournaments", "characters"] as const;
type Tab = (typeof tabs)[number];
const TAB_LABELS: Record<Tab, [string, string]> = { stats: ["Stats", "Статистика"], matches: ["Matches", "Матчи"], tournaments: ["Tournaments", "Турниры"], characters: ["Characters", "Персонажи"] };

const TOURNAMENTS: [[string, string], [string, string, string]] = [["tournament", "tournaments"], ["турнир", "турнира", "турниров"]];

function characterCount(l: L, item: CharacterCount | null) {
  return item ? `${l.name(item.character)} · ${l.count(item.games, ...GAMES)}` : "—";
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
                <Link className="player-top4-row" to={`/tournament/${f.tournament.id}`} key={f.tournament.id}>
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

// A date typed as dd.mm.yyyy: digits fill the day, the month and the year in turn and the dots come by themselves;
// a dot (or a dash, slash or space) typed after a single digit moves on, so "1.6.2024" works too.
export function maskDate(raw: string): string {
  const iso = raw.trim().match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (iso) return `${iso[3]}.${iso[2]}.${iso[1]}`;
  const parts = ["", "", ""];
  let i = 0;
  for (const ch of raw) {
    if (/\d/.test(ch)) {
      if (parts[i].length === (i === 2 ? 4 : 2)) {
        if (i === 2) break;
        i += 1;
      }
      parts[i] += ch;
    } else if (/[.\-/\s,]/.test(ch) && i < 2 && parts[i]) {
      parts[i] = parts[i].padStart(2, "0");
      i += 1;
    }
  }
  // A dot shows once the next part has begun (or one was typed), so Backspace goes through the dots as usual
  return parts.slice(0, i + 1).join(".");
}

// dd.mm.yyyy (or a two-digit year, taken as 20yy) as YYYY-MM-DD; null while it isn't a whole real date.
export function parseDate(text: string, partialYear = false): string | null {
  const m = text.match(/^(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})$/);
  if (!m || (m[3].length === 2 && !partialYear)) return null;
  const year = m[3].length === 2 ? 2000 + Number(m[3]) : Number(m[3]);
  const day = new Date(Date.UTC(year, Number(m[2]) - 1, Number(m[1])));
  if (day.getUTCDate() !== Number(m[1]) || day.getUTCMonth() !== Number(m[2]) - 1 || year < 2000) return null;
  return day.toISOString().slice(0, 10);
}

const shown = (day: string) => (day ? day.split("-").reverse().join(".") : "");

// The statistics' date range: "Count from" (tournaments that began on or after this day) and "Count to" (on or
// before it). Typed by hand as dd.mm.yyyy, applied once the date is whole (or on Enter / leaving the field); the
// calendar button opens the browser's date picker.
function DateFilter({ value, onChange, kind, min, max }: { value: string; onChange: (day: string) => void; kind: "since" | "until"; min?: string; max?: string }) {
  const { t } = useLang();
  const today = new Date().toISOString().slice(0, 10);
  const [draft, setDraft] = useState(shown(value));
  const [bad, setBad] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  useEffect(() => { setDraft(shown(value)); setBad(false); }, [value]);
  const [label, aria, title] = kind === "since"
    ? [t("Count from", "Считать с"), t("Count statistics from this date, dd.mm.yyyy", "Считать статистику с этой даты, дд.мм.гггг"),
      t("Only tournaments that started on or after this day count", "Учитываются только турниры, начавшиеся с этого дня")]
    : [t("Count to", "Считать по"), t("Count statistics up to this date, dd.mm.yyyy", "Считать статистику по эту дату, дд.мм.гггг"),
      t("Only tournaments that started on or before this day count", "Учитываются только турниры, начавшиеся не позже этого дня")];

  const apply = (day: string) => { if (day !== value) onChange(day); };
  // On Enter or leaving the field: an empty field clears the date, a whole one applies, anything else goes back.
  const settle = () => {
    if (!draft.trim()) return apply("");
    const day = parseDate(draft, true);
    if (day) apply(day);
    else { setDraft(shown(value)); setBad(false); }
  };

  return (
    <span className={`player-since${value ? " active" : ""}${bad ? " invalid" : ""}`}>
      <label>
        <span>{label}</span>
        <input type="text" inputMode="numeric" autoComplete="off" placeholder={t("dd.mm.yyyy", "дд.мм.гггг")} maxLength={10} value={draft}
          aria-label={aria} title={title} aria-invalid={bad}
          onChange={(e) => {
            const next = maskDate(e.target.value);
            setDraft(next);
            const whole = next.length === 10;
            const day = whole ? parseDate(next) : null;
            setBad(whole && !day);
            if (day) apply(day);
          }}
          onBlur={settle}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); settle(); } }} />
      </label>
      <button type="button" className="player-since-calendar" aria-label={t("Pick on a calendar", "Выбрать в календаре")} title={t("Calendar", "Календарь")}
        onClick={() => { const el = picker.current; if (el) { try { el.showPicker(); } catch { el.focus(); } } }}>
        <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden><path fill="currentColor" d="M4 0h1.5v2h5V0H12v2h2a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1h2zm9.5 6h-11v8.5h11zM5 8h2v2H5zm4 0h2v2H9z" /></svg>
      </button>
      <input ref={picker} className="player-since-picker" type="date" tabIndex={-1} aria-hidden value={value} min={min || undefined}
        max={max && max < today ? max : today} onChange={(e) => apply(e.target.value)} />
      {value && <button type="button" onClick={() => apply("")} aria-label={t("Remove this date", "Убрать эту дату")} title={t("Remove", "Убрать")}>×</button>}
    </span>
  );
}

// "Major champion ×N" next to the nickname; hovering or focusing it lists the majors won.
function MajorChampion({ titles }: { titles: PlayerDetail["major_titles"] }) {
  const { t, date } = useLang();
  if (!titles?.length) return null;
  return (
    <span className="player-major-champion" tabIndex={0} aria-describedby="player-major-titles">
      {t("Major champion", "Чемпион мейджора")}{titles.length > 1 && <b> ×{titles.length}</b>}
      <span className="player-major-tip" role="tooltip" id="player-major-titles">
        {titles.map((m) => (
          <Link key={m.tournament_id} to={`/tournament/${m.tournament_id}`} className="player-major-tip-row">
            <span>{m.title}</span><span className="gitv-date">{date(m.date)}</span>
          </Link>
        ))}
      </span>
    </span>
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
  const sinceParam = params.get("since") ?? "";
  const since = /^\d{4}-\d{2}-\d{2}$/.test(sinceParam) ? sinceParam : "";
  const untilParam = params.get("until") ?? "";
  const until = /^\d{4}-\d{2}-\d{2}$/.test(untilParam) ? untilParam : "";
  // The picker's list comes with the player; kept so it stays filled while another tournament loads.
  const [tournaments, setTournaments] = useState<PlayedTournament[]>([]);
  const [player, setPlayer] = useState<PlayerDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setPlayer(null);
    setError("");
    fetchPlayer(playerId, controller.signal, major ? "major" : "all", tournament || undefined, since || undefined, until || undefined)
      .then((data) => { setPlayer(data); setTournaments(data.tournament_list); })
      .catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t("Couldn't load the player.", "Не удалось загрузить игрока.")); });
    return () => controller.abort();
  }, [playerId, major, tournament, since, until]);

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
              {!tournament && <DateFilter kind="since" value={since} max={until} onChange={(day) => update({ since: day })} />}
              {!tournament && <DateFilter kind="until" value={until} min={since} onChange={(day) => update({ until: day })} />}
              {!tournament && <MajorToggle on={major} onChange={(on) => update({ major: on ? "1" : "" })} />}
              <Link className="player-compare-link" to={`/player/${playerId}/compare${major ? "?major=1" : ""}`}>{t("Compare", "Сравнить")}</Link>
            </div>
            {error ? <p className="player-box player-message">{error}</p>
              : !player ? <p className="player-box player-message">{t("Loading player…", "Загрузка игрока…")}</p>
              : <>
                  <header className="player-box player-header">
                    <div className="player-identity">
                      <div className="player-identity-text">
                        <div className="player-name-row">
                          <div className="player-nickname"><Nick id={player.id} name={player.name} /></div>
                          <MajorChampion titles={player.major_titles} />
                        </div>
                      </div>
                      {player.elo && (
                        <div className="player-elo">
                          <EloBadge rating={player.elo.rating} rank={player.elo.rank} tier={player.elo.tier} active={player.elo.active} className="is-large" />
                          <span className="player-label">{player.elo.active ? `${t("Elo", "Эло")} · #${player.elo.rank}` : t("Elo · inactive", "Эло · неактивен")}</span>
                        </div>
                      )}
                    </div>
                    <div className="player-fullname">{distinctNames(player.name, player.other_names).length ? `${t("Also played as", "Также играл как")} ${distinctNames(player.name, player.other_names).join(", ")}` : " "}</div>
                    <Records player={player} />
                    <StatRow label={t("Most picked character", "Чаще всего берёт")} value={characterCount(l, player.most_picked)} />
                    <StatRow label={t("Most banned character by opponent", "Чаще всего банят соперники")} value={characterCount(l, player.most_banned_against)} />
                  </header>

                  <div className="player-tabs" role="tablist" style={{ gridTemplateColumns: `repeat(${tabs.length}, 1fr)` }} aria-label={t("Player sections", "Разделы игрока")}>
                    {tabs.map((name) => (
                      <button type="button" role="tab" aria-selected={tab === name} className={`player-tab${tab === name ? " active" : ""}`} onClick={() => setTab(name)} key={name}>{t(...TAB_LABELS[name])}</button>
                    ))}
                  </div>

                  {tab === "matches" ? <MatchList player={player} options={options} onChange={update} />
                    : tab === "tournaments" ? <TournamentList player={player} playerId={playerId} />
                    : tab === "characters" ? <CharactersTab playerId={playerId} since={tournament ? undefined : since || undefined} until={tournament ? undefined : until || undefined} />
                    : <StatsTab player={player} />}
                </>}
          </div>
        </div>
      </div>
    </main>
  );
}
