import { Fragment, useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { OrganizerName } from "../match/OrganizerName";
import { MatchRow } from "../match/MatchesPage";
import { fetchLiveMatches, fetchMatchesByTournament, type LiveMatch, type MatchSummary } from "../match/api";
import { LiveMatchRow } from "../match/LiveMatches";
import { useLang } from "../i18n";
import { fetchTournament, type TournamentLink, type BracketRound, type BracketSide, type PoolCharacter, type PoolPlayer, type TableRow, type TournamentDetail } from "./api";
import { DateRange, KIND_LABELS, Prize } from "./common";
import { TournamentAbyssBox } from "../abyss/TournamentAbyss";
import { TwitchPlayer } from "../components/TwitchPlayer";
import { fetchLiveStreams, type LiveStream } from "../schedule/api";
import "../character/characters.css";
import "./tournaments.css";
import { Nick } from "../components/PlayerNick";

type Tab = "standings" | "bracket" | "matches" | "stats";
const TAB_LABELS: Record<Tab, [string, string]> = {
  standings: ["Standings", "Таблица"], bracket: ["Bracket", "Сетка"], matches: ["Matches", "Матчи"], stats: ["Stats", "Статистика"],
};
const QUAL: Record<string, [string, string]> = { passed: ["Qualified", "Прошёл"], failed: ["Eliminated", "Не прошёл"], pending: ["Pending", "Ожидается"] };

function Box({ title, children }: { title: string; children: ReactNode }) {
  return <section className="player-box"><h2 className="player-box-title">{title}</h2>{children}</section>;
}

function Place({ row, manual = false }: { row: TableRow; manual?: boolean }) {
  const { t } = useLang();
  if (!row.place) return <span>—</span>;
  const [low, high] = row.place;
  const estimate = row.place_source === "estimate";
  const title = estimate ? t("Estimated from matches won", "Оценка по выигранным матчам")
    : manual ? t("From the tournament's bracket", "Из сетки турнира") : t("From the Challonge bracket", "Из сетки Challonge");
  return (
    <span title={title}>
      {low <= 4 ? <span className={`player-place-badge place-${low}`}>{low}</span>
        : <>{estimate && "≈ "}{low === high ? low : `${low}–${high}`}</>}
    </span>
  );
}

function Standings({ tournament }: { tournament: TournamentDetail }) {
  const { t } = useLang();
  const s = (v: number | null) => (v == null ? "—" : `${v}s`);
  const qualifier = tournament.kind === "qualifier";
  const bracket = tournament.kind === "bracket";
  if (tournament.table.length === 0) {
    return <Box title={t("Standings", "Таблица")}><p className="player-message">{t("Team events have no personal standings.", "У командных турниров нет личной таблицы.")}</p></Box>;
  }
  return (
    <Box title={t("Standings", "Таблица")}>
      <div className="tourney-table-row tourney-table-head player-label">
        <span>{bracket ? t("Place", "Место") : "#"}</span><span>{t("Player", "Игрок")}</span><span>{t("Matches", "Матчи")}</span>
        <span className="hide-xs">{t("Games", "Игры")}</span><span className="hide-sm">{t("Avg time", "Ср. время")}</span>
        <span className="hide-sm">{t("Best", "Лучшее")}</span><span className="hide-xs">{qualifier ? t("Qualifiers", "Квалы") : t("Tech L", "Тех. пор.")}</span>
      </div>
      {tournament.table.map((row, i) => (
        <Fragment key={row.player.id ?? `?${row.player.name}`}>
          {row.group && row.group !== tournament.table[i - 1]?.group && (
            <div className="tourney-group-head player-label">{t("Group", "Группа")} {row.group}</div>
          )}
          <div className="tourney-table-row">
            {bracket ? <Place row={row} manual={tournament.challonge_only && !tournament.challonge_url} />
              : <span className="player-label">{i + 1 - (row.group ? tournament.table.findIndex((r) => r.group === row.group) : 0)}</span>}
            {row.player.id
              ? <Link className="player-match-link tourney-player" to={`/player/${row.player.id}?tournament=${tournament.id}`}><Nick id={row.player.id} name={row.player.name} /></Link>
              : <span className="tourney-player player-ellipsis" title={t("Not on the site: matched to no player", "Нет на сайте: не сопоставлен с игроком")}>{row.player.name}</span>}
            <span>{row.match_wins} – {row.match_losses}{row.match_draws ? ` – ${row.match_draws}` : ""}</span>
            <span className="hide-xs">{row.games_won} – {row.games_lost}</span>
            <span className="hide-sm">{s(row.avg_time)}</span>
            <span className="hide-sm">{s(row.best_time)}</span>
            <span className="hide-xs">{qualifier
              ? (row.qualification ? <span className={`player-qual ${row.qualification}`}>{t(...QUAL[row.qualification])}</span> : "—")
              : row.tech_losses || "—"}</span>
          </div>
        </Fragment>
      ))}
      {tournament.challonge_only && !tournament.challonge_url && (
        <p className="player-note tourney-note">{t("Played before the site: matches and places come from its published bracket; there are no games, times or drafts. Names without a link aren't matched to a player on the site.",
          "Турнир проходил до сайта: матчи и места взяты из опубликованной сетки, игр, времени и драфтов нет. Имена без ссылки не сопоставлены с игроками сайта.")}</p>
      )}
      {tournament.challonge_only && tournament.challonge_url && (
        <p className="player-note tourney-note">{t("Played only on Challonge: matches and places come from its bracket; there are no games, times or drafts. Names without a link aren't matched to a player on the site.",
          "Турнир проходил только на Challonge: матчи и места взяты из его сетки, игр, времени и драфтов нет. Имена без ссылки не сопоставлены с игроками сайта.")}</p>
      )}
      {tournament.live && (
        <p className="player-note tourney-note">{t("The tournament is still being played: places appear once the final has a winner.",
          "Турнир ещё идёт: места появятся, когда в финале определится победитель.")}</p>
      )}
      {bracket && !tournament.live && !tournament.challonge_only && tournament.places_source !== "challonge" && (
        <p className="player-note tourney-note">{t("No Challonge bracket: places below the top four are estimated from matches won (≈).",
          "Сетки Challonge нет: места ниже четвёртого оценены по выигранным матчам (≈).")}</p>
      )}
    </Box>
  );
}

function roundName(round: number, rounds: BracketRound[], t: (en: string, ru: string) => string) {
  if (round === 0) return t("Third place", "За 3-е место");
  if (round < 0) return t(`Losers round ${-round}`, `Нижняя сетка, раунд ${-round}`);
  const double = rounds.some((r) => r.round < 0);
  const last = Math.max(...rounds.map((r) => r.round));
  if (double) return round === last ? t("Grand final", "Гранд-финал") : t(`Round ${round}`, `Раунд ${round}`);
  const fromEnd = last - round;
  return [t("Final", "Финал"), t("Semifinals", "Полуфиналы"), t("Quarterfinals", "Четвертьфиналы")][fromEnd] ?? t(`Round ${round}`, `Раунд ${round}`);
}

function Side({ side, won, score }: { side: BracketSide | null; won: boolean; score: number | undefined }) {
  const { t } = useLang();
  if (!side) return <div className="tourney-bracket-side is-empty"><span>{t("TBD", "—")}</span></div>;
  return (
    <div className={`tourney-bracket-side${won ? " is-winner" : ""}`}>
      {side.id ? <Link to={`/player/${side.id}`} className="player-match-link player-ellipsis"><Nick id={side.id} name={side.name} /></Link>
        : <span className="player-ellipsis" title={t("Not matched to a player", "Не сопоставлен с игроком")}>{side.name}</span>}
      <b>{score ?? ""}</b>
    </div>
  );
}

function Bracket({ rounds, unmatched, challonge }: { rounds: BracketRound[]; unmatched: string[]; challonge: boolean }) {
  const { t } = useLang();
  const main = rounds.filter((r) => r.round > 0 || r.round === 0);
  const losers = rounds.filter((r) => r.round < 0);
  const column = (r: BracketRound) => (
    <div className="tourney-bracket-round" key={r.round}>
      <h3 className="player-label">{roundName(r.round, rounds, t)}</h3>
      <div className="tourney-bracket-matches">
        {r.matches.map((m, i) => (
          <div className="tourney-bracket-match" key={i}>
            <Side side={m.player1} won={m.winner === 1} score={m.scores[0]} />
            <Side side={m.player2} won={m.winner === 2} score={m.scores[1]} />
          </div>
        ))}
      </div>
    </div>
  );
  return (
    <Box title={challonge ? t("Bracket (Challonge)", "Сетка (Challonge)") : t("Bracket", "Сетка")}>
      <div className="tourney-bracket">{main.map(column)}</div>
      {losers.length > 0 && <><h3 className="player-box-title tourney-subtitle">{t("Losers' bracket", "Нижняя сетка")}</h3><div className="tourney-bracket">{losers.map(column)}</div></>}
      {unmatched.length > 0 && (
        <p className="player-note tourney-note">{t("Not matched to a player: ", "Не сопоставлены с игроками: ")}{unmatched.join(", ")}</p>
      )}
    </Box>
  );
}

function Matches({ tournamentId }: { tournamentId: string }) {
  const { t } = useLang();
  const [groups, setGroups] = useState<{ title: string; items: MatchSummary[] }[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    // A stage of qualifier groups comes back as one list per group.
    fetchMatchesByTournament({ tournament: tournamentId, limit: 20, offset: 0 }, controller.signal)
      .then((r) => setGroups(r.groups.map((g) => ({ title: g.tournament.title, items: g.items }))))
      .catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t("Couldn't load the matches.", "Не удалось загрузить матчи.")); });
    return () => controller.abort();
  }, [tournamentId]);
  return (
    <Box title={t("Matches", "Матчи")}>
      {error ? <p className="player-message">{error}</p>
        : !groups ? <p className="player-message">{t("Loading matches…", "Загрузка матчей…")}</p>
        : groups.length > 1
          ? [...groups].sort((a, b) => a.title.localeCompare(b.title)).map((g) => (
              <Fragment key={g.title}>
                <div className="tourney-group-head player-label">{g.title}</div>
                {g.items.map((m) => <MatchRow match={m} key={m.id} />)}
              </Fragment>
            ))
          : (groups[0]?.items ?? []).map((m) => <MatchRow match={m} key={m.id} />)}
    </Box>
  );
}

// The tournament's unfinished matches while it runs, each game linking to its draft on the tournament site;
// nothing once it's over. Checked again every minute (the API refreshes them every five).
function LiveMatches({ tournamentId }: { tournamentId: string }) {
  const { t } = useLang();
  const [items, setItems] = useState<LiveMatch[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    const load = () => fetchLiveMatches(tournamentId, controller.signal).then(setItems).catch(() => {});
    load();
    const timer = setInterval(load, 60000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [tournamentId]);
  if (!items.length) return null;
  return (
    <Box title={t("Being played and upcoming", "Идут и предстоят")}>
      {items.map((m) => <LiveMatchRow match={m} key={m.id} />)}
      <p className="player-note tourney-note">{t("Games open their draft on abyss.darte.gg. Updated every few minutes.",
        "Игры открывают драфт на abyss.darte.gg. Обновляется раз в несколько минут.")}</p>
    </Box>
  );
}

// The organizer's stream while the tournament runs and it's on air (Abyss Cup, House of the Hearth, Abyss New Gen:
// the streams are named as their tournaments' organizers). Checked again every minute.
function LiveStreamBox({ organizer }: { organizer: string }) {
  const { t } = useLang();
  const [items, setItems] = useState<LiveStream[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    const load = () => fetchLiveStreams(controller.signal).then(setItems).catch(() => {});
    load();
    const timer = setInterval(load, 60000);
    return () => { controller.abort(); clearInterval(timer); };
  }, []);
  const own = items.filter((s) => s.name === organizer);
  if (!own.length) return null;
  return <Box title={t("On stream", "Трансляция")}><TwitchPlayer streams={own} /></Box>;
}

const LINK_LABELS: Record<Exclude<TournamentLink["kind"], "site">, [string, string]> = {
  telegram: ["Telegram", "Telegram"], discord: ["Discord", "Discord"], twitch: ["Twitch", "Twitch"], youtube: ["YouTube", "YouTube"],
  vk: ["VK", "VK"], boosty: ["Boosty", "Boosty"], rules: ["Regulations", "Регламент"],
};

// A site's name for its link. Organizers type these on darte.gg: one the browser can't read shows as typed, rather
// than taking the whole page down.
function siteName(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

// The tournament's links on darte.gg (socials, regulations), a site of its own by its address.
function TournamentLinks({ links }: { links: TournamentLink[] }) {
  const { t } = useLang();
  if (!links.length) return null;
  return (
    <nav className="tourney-links" aria-label={t("Tournament links", "Ссылки турнира")}>
      {links.map((link) => (
        <a key={link.url} className="tourney-link" href={link.url} target="_blank" rel="noopener noreferrer">
          {link.kind === "site" ? siteName(link.url) : t(...LINK_LABELS[link.kind])} ↗
        </a>
      ))}
    </nav>
  );
}

const POOL_SHOWN = 20;
// A pool count; hovering (or focusing) it lists who had the character, as on the characters page: each player
// with the constellation they had it at, linked to their page when they have one.
function PoolPlayers({ title, players, children, className = "" }: {
  title: string; players: { player: PoolPlayer; constellation: number }[]; children: ReactNode; className?: string;
}) {
  const { t } = useLang();
  return (
    <span className={`${className} chars-players`} tabIndex={0} aria-label={t(`${title}: ${players.length} players`, `${title}: игроков ${players.length}`)}>
      <span className="chars-players-count">{children}</span>
      <div className="chars-players-pop tourney-pool-pop" role="tooltip">
        <div className="chars-games-head">
          <b>{title}</b>
          <span className="player-label">{t(`${players.length} players`, `игроков: ${players.length}`)}</span>
        </div>
        <div className="tourney-pool-players tourney-pool-players-head player-label">
          <span>{t("Player", "Игрок")}</span><span>{t("Const.", "Конста")}</span>
        </div>
        <div className="chars-games-list">
          {players.map(({ player, constellation }, i) => player.id
            ? <Link key={player.id} to={`/player/${player.id}?tab=characters`} className="tourney-pool-players chars-players-row">
                <b className="player-ellipsis"><Nick id={player.id} name={player.name} /></b><span>C{constellation}</span>
              </Link>
            : <span key={`?${player.name}${i}`} className="tourney-pool-players chars-players-row"
                title={t("Not on the site yet: no player page", "Ещё не играл на сайте: страницы игрока нет")}>
                <b className="player-ellipsis">{player.name}</b><span>C{constellation}</span>
              </span>)}
        </div>
      </div>
    </span>
  );
}

// The pool's sort: by how many have it, or by how many have it at one constellation (0-6); null is the default.
type PoolSort = { by: "owned" | number; desc: boolean } | null;

// Every character that was in the players' pools, with how many had it at each constellation.
function Pool({ pool }: { pool: TournamentDetail["pool"] }) {
  const { t, name, count } = useLang();
  const [all, setAll] = useState(false);
  const [sort, setSort] = useState<PoolSort>(null);
  const [fiveOnly, setFiveOnly] = useState(false);
  const value = (c: PoolCharacter) => (sort?.by === "owned" ? c.owned : c.constellations[sort?.by ?? 0]);
  // By default 5★ first (4★ are in nearly every pool, at C6), each by how many players had them; a column's header
  // sorts by it, most first, and again the other way round.
  const sorted = pool.characters.filter((c) => !fiveOnly || c.character.rarity === 5).sort((a, b) =>
    sort ? (value(b) - value(a)) * (sort.desc ? 1 : -1) || b.owned - a.owned
      : (b.character.rarity ?? 0) - (a.character.rarity ?? 0) || b.owned - a.owned);
  const shown = all ? sorted : sorted.slice(0, POOL_SHOWN);
  const header = (by: "owned" | number, label: string, className = "") => {
    const active = sort?.by === by;
    return (
      <button type="button" className={`tourney-pool-sort${active ? " active" : ""} ${className}`} aria-pressed={active}
        title={t("Sort", "Сортировать")} onClick={() => setSort(active ? { by, desc: !sort.desc } : { by, desc: true })}>
        {label}{active ? (sort.desc ? " ↓" : " ↑") : ""}
      </button>
    );
  };
  return (
    <Box title={t("Character pool", "Пул персонажей")}>
      {pool.players === 0 ? <p className="player-message">{t("No draft data.", "Нет данных драфтов.")}</p> : <>
        <p className="player-note tourney-note">{t(`Characters in the pools of the ${count(pool.players, ["player", "players"], ["игрок", "игрока", "игроков"])} with draft data (each player's last roster), by constellation.`,
          `Персонажи в пулах ${count(pool.players, ["player", "players"], ["игрока", "игроков", "игроков"])} с данными драфтов (последний ростер каждого), по созвездиям.`)}
          {pool.unplayed > 0 && " " + t(`${pool.unplayed} of them haven't played yet: their roster is from their draft to come.`,
            `${pool.unplayed} из них ещё не играли: их ростер взят из предстоящего драфта.`)}</p>
        <label className="tourney-pool-filter">
          <input type="checkbox" checked={fiveOnly} onChange={(e) => setFiveOnly(e.target.checked)} />
          {t("Only 5★", "Только 5★")}
        </label>
        <div className="tourney-pool">
          <div className="tourney-pool-row tourney-table-head player-label">
            <span />
            <button type="button" className={`tourney-pool-sort${sort ? "" : " active"}`} title={t("5★ first, by how many have them", "Сначала 5★, по числу владельцев")}
              onClick={() => setSort(null)}>{t("Character", "Персонаж")}</button>
            {header("owned", t("Have it", "Есть"))}
            {[0, 1, 2, 3, 4, 5, 6].map((c) => <Fragment key={c}>{header(c, `C${c}`, "hide-sm")}</Fragment>)}
          </div>
          {shown.map((c) => (
            <div className="tourney-pool-row" key={c.character.id}>
              {c.character.icon ? <img src={c.character.icon} alt="" width={28} height={28} loading="lazy" className={`tourney-char-icon rarity-${c.character.rarity ?? 4}`} /> : <span className="tourney-char-icon" />}
              <span className="player-ellipsis">{name(c.character)}</span>
              <PoolPlayers title={name(c.character)}
                players={c.holders.flatMap((players, i) => players.map((player) => ({ player, constellation: i })))
                  .sort((a, b) => b.constellation - a.constellation || a.player.name.localeCompare(b.player.name))}>
                <b>{c.rate == null ? "—" : `${c.rate}%`}</b> <small className="player-label">{c.owned}</small>
              </PoolPlayers>
              {c.constellations.map((n, i) => n
                ? <PoolPlayers key={i} className="hide-sm" title={`${name(c.character)} · C${i}`}
                    players={c.holders[i].map((player) => ({ player, constellation: i }))}>{n}</PoolPlayers>
                : <span key={i} className="tourney-pool-zero hide-sm">·</span>)}
            </div>
          ))}
        </div>
        {sorted.length > POOL_SHOWN && (
          <button type="button" className="tourney-pool-more" onClick={() => setAll(!all)}>
            {all ? t("Show fewer", "Свернуть") : t(`Show all ${sorted.length}`, `Показать всех (${sorted.length})`)}
          </button>
        )}
      </>}
    </Box>
  );
}

function Stats({ tournament }: { tournament: TournamentDetail }) {
  const { t, name } = useLang();
  const s = tournament.stats;
  const pct = (v: number | null) => (v == null ? "—" : `${v}%`);
  return (
    <>
      <div className="tourney-stats">
        <Box title={t("Games", "Игры")}>
          <div className="player-box-body">
            <div className="player-stat-row"><span className="player-label">{t("Games played", "Сыграно игр")}</span><span className="player-value">{s.games}</span></div>
            <div className="player-stat-row"><span className="player-label">{t("Technical defeats", "Тех. поражения")}</span><span className="player-value">{s.technical_games}</span></div>
            <div className="player-stat-row"><span className="player-label">{t("Average time", "Среднее время")}</span><span className="player-value">{s.avg_time == null ? "—" : `${s.avg_time}s`}</span></div>
            <div className="player-stat-row"><span className="player-label">{t("Fastest game", "Самая быстрая игра")}</span>
              <span className="player-value">{s.fastest ? <><Link className="player-match-link" to={`/match/${s.fastest.match_id}`}>{s.fastest.time}s</Link> · <Link className="player-match-link" to={`/player/${s.fastest.player.id}`}><Nick id={s.fastest.player.id} name={s.fastest.player.name} /></Link></> : "—"}</span></div>
          </div>
        </Box>
        <Box title={t("Most picked", "Чаще всего пикали")}>
          {s.picks.map((c) => (
            <div className="tourney-char" key={c.character.id}>
              {c.character.icon ? <img src={c.character.icon} alt="" width={28} height={28} loading="lazy" className={`tourney-char-icon rarity-${c.character.rarity ?? 4}`} /> : <span className="tourney-char-icon" />}
              <span className="player-ellipsis">{name(c.character)}</span>
              <span className="player-label">{c.picks} · {pct(c.pick_rate)}</span>
              <span title={t("Winrate", "Винрейт")}>{pct(c.winrate)}</span>
            </div>
          ))}
        </Box>
        <Box title={t("Most banned", "Чаще всего банили")}>
          {s.bans.length === 0 && <p className="player-message">{t("No draft data.", "Нет данных драфтов.")}</p>}
          {s.bans.map((c) => (
            <div className="tourney-char" key={c.character.id}>
              {c.character.icon ? <img src={c.character.icon} alt="" width={28} height={28} loading="lazy" className={`tourney-char-icon rarity-${c.character.rarity ?? 4}`} /> : <span className="tourney-char-icon" />}
              <span className="player-ellipsis">{name(c.character)}</span>
              <span className="player-label">{c.bans}</span>
              <span title={t("Share of games", "Доля игр")}>{pct(c.ban_rate)}</span>
            </div>
          ))}
        </Box>
      </div>
      <Pool pool={tournament.pool} />
    </>
  );
}

export function TournamentPage({ tournamentId }: { tournamentId: string }) {
  const [params, setParams] = useSearchParams();
  const [tournament, setTournament] = useState<TournamentDetail | null>(null);
  const [error, setError] = useState("");
  const { t, count } = useLang();
  const navigate = useNavigate();

  useEffect(() => {
    const controller = new AbortController();
    setTournament(null);
    setError("");
    fetchTournament(tournamentId, controller.signal)
      .then((found) => {
        // A qualifier group opens its round's stage: show that stage's address.
        if (found.id !== tournamentId) navigate(`/tournament/${found.id}${window.location.search}`, { replace: true });
        setTournament(found);
      })
      .catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t("Couldn't load the tournament.", "Не удалось загрузить турнир.")); });
    return () => controller.abort();
  }, [tournamentId]);

  // A Challonge-only tournament has no games: no match list or draft statistics.
  const tabs: Tab[] = (tournament?.bracket ? ["standings", "bracket", "matches", "stats"] as Tab[] : ["standings", "matches", "stats"] as Tab[])
    .filter((name) => !tournament?.challonge_only || name === "standings" || name === "bracket");
  const asked = params.get("tab") as Tab | null;
  const tab: Tab = asked && tabs.includes(asked) ? asked : "standings";
  const top = tournament?.table.filter((r) => r.place && r.place[0] <= 4) ?? [];

  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="player-content match-content">
            {error ? <div className="player-box player-message">{error}</div>
              : !tournament ? <div className="player-box player-message">{t("Loading tournament…", "Загрузка турнира…")}</div>
              : <>
                <header className="player-box player-header">
                  <div className="player-label tourney-kicker">
                    <Link className="player-match-link" to="/tournaments">{t("Tournaments", "Турниры")}</Link> · {t(...KIND_LABELS[tournament.kind])}
                    {tournament.major && <span className="match-tag tourneys-major">{t("Major", "Мейджор")}</span>}
                  </div>
                  {tournament.event && tournament.stages.length > 1 ? <>
                    <h1 className="player-nickname">{tournament.event.title}</h1>
                    <label className="tourney-stage">
                      <span className="player-label">{t("Stage", "Стадия")}</span>
                      <select className="match-input tourney-stage-select" id="tourney-stage" value={tournament.id}
                        onChange={(e) => navigate(`/tournament/${e.target.value}`)}>
                        {tournament.stages.map((s, i) => <option value={s.id} key={s.id}>{i + 1}. {s.title}</option>)}
                      </select>
                    </label>
                  </> : <h1 className="player-nickname">{tournament.title}</h1>}
                  <p className="player-fullname">
                    <DateRange first={tournament.first_match} last={tournament.last_match} estimated={tournament.date_estimated} />
                    {tournament.organizer && <> · {t("by", "орг.")} <OrganizerName organizer={tournament.organizer} /></>}
                    {tournament.system && <> · {tournament.system}</>}
                  </p>
                  <div className="player-records">
                    {tournament.teams
                      ? <div className="player-record"><span className="player-label">{t("Teams", "Команды")}</span><span className="player-value">{tournament.teams}</span></div>
                      : <div className="player-record"><span className="player-label">{t("Players", "Игроки")}</span><span className="player-value">{tournament.players}</span></div>}
                    <div className="player-record"><span className="player-label">{t("Matches", "Матчи")}</span><span className="player-value">{tournament.matches}</span></div>
                    {tournament.prize ? <div className="player-record"><span className="player-label">{t("Prize", "Приз")}</span><span className="player-value"><Prize prize={tournament.prize} currency={tournament.currency} /></span></div> : null}
                    {tournament.challonge_url && <div className="player-record"><span className="player-label">{t("Bracket", "Сетка")}</span>
                      <a className="player-value player-match-link" href={tournament.challonge_url} target="_blank" rel="noreferrer">Challonge ↗</a></div>}
                  </div>
                  <TournamentLinks links={tournament.links ?? []} />
                  {top.length > 0 && (
                    <div className="match-places" aria-label={t("Top four", "Первые четыре места")}>
                      {top.map((r) => r.player.id
                        ? <Link className={`match-place place-${r.place![0]}`} to={`/player/${r.player.id}`} key={r.player.id}>
                          <span className="match-place-no">{r.place![0]}</span><Nick id={r.player.id} name={r.player.name} />
                        </Link>
                        : <span className={`match-place place-${r.place![0]}`} key={`?${r.player.name}`}>
                          <span className="match-place-no">{r.place![0]}</span>{r.player.name}
                        </span>)}
                    </div>
                  )}
                </header>

                <TournamentAbyssBox phases={tournament.abyss ?? []} />
                {tournament.live && tournament.organizer && <LiveStreamBox organizer={tournament.organizer.name} />}
                {tournament.live && <LiveMatches tournamentId={tournament.id} />}

                <div className="player-tabs" role="tablist" style={{ gridTemplateColumns: `repeat(${tabs.length}, 1fr)` }} aria-label={t("Tournament sections", "Разделы турнира")}>
                  {tabs.map((name) => (
                    <button type="button" role="tab" aria-selected={tab === name} className={`player-tab${tab === name ? " active" : ""}`} key={name}
                      onClick={() => setParams((p) => { const next = new URLSearchParams(p); if (name === "standings") next.delete("tab"); else next.set("tab", name); return next; }, { replace: true })}>
                      {t(...TAB_LABELS[name])}
                    </button>
                  ))}
                </div>

                {tab === "bracket" && tournament.bracket ? <Bracket rounds={tournament.bracket} unmatched={tournament.unmatched} challonge={!!tournament.challonge_url} />
                  : tab === "matches" ? <Matches tournamentId={tournament.id} />
                  : tab === "stats" ? <Stats tournament={tournament} />
                  : <Standings tournament={tournament} />}
                <p className="player-note tourney-note">{tournament.challonge_only
                  ? count(tournament.table.length, ["player", "players"], ["игрок", "игрока", "игроков"])
                  : count(tournament.table.length, ["player with games", "players with games"], ["игрок с играми", "игрока с играми", "игроков с играми"])}</p>
              </>}
          </div>
        </div>
      </div>
    </main>
  );
}
