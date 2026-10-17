import { useEffect, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { OrganizerName } from "../match/OrganizerName";
import { MatchRow } from "../match/MatchesPage";
import { fetchMatchesByTournament, type MatchSummary } from "../match/api";
import { useLang } from "../i18n";
import { fetchTournament, type BracketRound, type BracketSide, type TableRow, type TournamentDetail } from "./api";
import { DateRange, KIND_LABELS, Prize } from "./common";
import "./tournaments.css";

type Tab = "standings" | "bracket" | "matches" | "stats";
const TAB_LABELS: Record<Tab, [string, string]> = {
  standings: ["Standings", "Таблица"], bracket: ["Bracket", "Сетка"], matches: ["Matches", "Матчи"], stats: ["Stats", "Статистика"],
};
const QUAL: Record<string, [string, string]> = { passed: ["Qualified", "Прошёл"], failed: ["Eliminated", "Не прошёл"], pending: ["Pending", "Ожидается"] };

function Box({ title, children }: { title: string; children: ReactNode }) {
  return <section className="player-box"><h2 className="player-box-title">{title}</h2>{children}</section>;
}

function Place({ row }: { row: TableRow }) {
  const { t } = useLang();
  if (!row.place) return <span>—</span>;
  const [low, high] = row.place;
  const estimate = row.place_source === "estimate";
  const title = estimate ? t("Estimated from matches won", "Оценка по выигранным матчам") : t("From the Challonge bracket", "Из сетки Challonge");
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
        <div className="tourney-table-row" key={row.player.id}>
          {bracket ? <Place row={row} /> : <span className="player-label">{i + 1}</span>}
          <Link className="player-match-link tourney-player" to={`/player/${row.player.id}?tournament=${tournament.id}`}>{row.player.name}</Link>
          <span>{row.match_wins} – {row.match_losses}{row.match_draws ? ` – ${row.match_draws}` : ""}</span>
          <span className="hide-xs">{row.games_won} – {row.games_lost}</span>
          <span className="hide-sm">{s(row.avg_time)}</span>
          <span className="hide-sm">{s(row.best_time)}</span>
          <span className="hide-xs">{qualifier
            ? (row.qualification ? <span className={`player-qual ${row.qualification}`}>{t(...QUAL[row.qualification])}</span> : "—")
            : row.tech_losses || "—"}</span>
        </div>
      ))}
      {bracket && tournament.places_source !== "challonge" && (
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
      {side.id ? <Link to={`/player/${side.id}`} className="player-match-link player-ellipsis">{side.name}</Link>
        : <span className="player-ellipsis" title={t("Not matched to a player", "Не сопоставлен с игроком")}>{side.name}</span>}
      <b>{score ?? ""}</b>
    </div>
  );
}

function Bracket({ rounds, unmatched }: { rounds: BracketRound[]; unmatched: string[] }) {
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
    <Box title={t("Bracket (Challonge)", "Сетка (Challonge)")}>
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
  const [items, setItems] = useState<MatchSummary[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    fetchMatchesByTournament({ tournament: tournamentId, limit: 1, offset: 0 }, controller.signal)
      .then((r) => setItems(r.groups[0]?.items ?? []))
      .catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t("Couldn't load the matches.", "Не удалось загрузить матчи.")); });
    return () => controller.abort();
  }, [tournamentId]);
  return (
    <Box title={t("Matches", "Матчи")}>
      {error ? <p className="player-message">{error}</p>
        : !items ? <p className="player-message">{t("Loading matches…", "Загрузка матчей…")}</p>
        : items.map((m) => <MatchRow match={m} key={m.id} />)}
    </Box>
  );
}

function Stats({ tournament }: { tournament: TournamentDetail }) {
  const { t, name } = useLang();
  const s = tournament.stats;
  const pct = (v: number | null) => (v == null ? "—" : `${v}%`);
  return (
    <div className="tourney-stats">
      <Box title={t("Games", "Игры")}>
        <div className="player-box-body">
          <div className="player-stat-row"><span className="player-label">{t("Games played", "Сыграно игр")}</span><span className="player-value">{s.games}</span></div>
          <div className="player-stat-row"><span className="player-label">{t("Technical defeats", "Тех. поражения")}</span><span className="player-value">{s.technical_games}</span></div>
          <div className="player-stat-row"><span className="player-label">{t("Average time", "Среднее время")}</span><span className="player-value">{s.avg_time == null ? "—" : `${s.avg_time}s`}</span></div>
          <div className="player-stat-row"><span className="player-label">{t("Fastest game", "Самая быстрая игра")}</span>
            <span className="player-value">{s.fastest ? <><Link className="player-match-link" to={`/match/${s.fastest.match_id}`}>{s.fastest.time}s</Link> · <Link className="player-match-link" to={`/player/${s.fastest.player.id}`}>{s.fastest.player.name}</Link></> : "—"}</span></div>
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
  );
}

export function TournamentPage({ tournamentId }: { tournamentId: string }) {
  const [params, setParams] = useSearchParams();
  const [tournament, setTournament] = useState<TournamentDetail | null>(null);
  const [error, setError] = useState("");
  const { t, count } = useLang();

  useEffect(() => {
    const controller = new AbortController();
    setTournament(null);
    setError("");
    fetchTournament(tournamentId, controller.signal)
      .then(setTournament)
      .catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t("Couldn't load the tournament.", "Не удалось загрузить турнир.")); });
    return () => controller.abort();
  }, [tournamentId]);

  const tabs: Tab[] = tournament?.bracket ? ["standings", "bracket", "matches", "stats"] : ["standings", "matches", "stats"];
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
                  <h1 className="player-nickname">{tournament.title}</h1>
                  <p className="player-fullname">
                    <DateRange first={tournament.first_match} last={tournament.last_match} />
                    {tournament.organizer && <> · {t("by", "орг.")} <OrganizerName organizer={tournament.organizer} /></>}
                    {tournament.system && <> · {tournament.system}</>}
                  </p>
                  <div className="player-records">
                    <div className="player-record"><span className="player-label">{t("Players", "Игроки")}</span><span className="player-value">{tournament.players}</span></div>
                    <div className="player-record"><span className="player-label">{t("Matches", "Матчи")}</span><span className="player-value">{tournament.matches}</span></div>
                    {tournament.prize ? <div className="player-record"><span className="player-label">{t("Prize", "Приз")}</span><span className="player-value"><Prize prize={tournament.prize} currency={tournament.currency} /></span></div> : null}
                    {tournament.challonge_url && <div className="player-record"><span className="player-label">{t("Bracket", "Сетка")}</span>
                      <a className="player-value player-match-link" href={tournament.challonge_url} target="_blank" rel="noreferrer">Challonge ↗</a></div>}
                  </div>
                  {top.length > 0 && (
                    <div className="match-places" aria-label={t("Top four", "Первые четыре места")}>
                      {top.map((r) => (
                        <Link className={`match-place place-${r.place![0]}`} to={`/player/${r.player.id}`} key={r.player.id}>
                          <span className="match-place-no">{r.place![0]}</span>{r.player.name}
                        </Link>
                      ))}
                    </div>
                  )}
                </header>

                <div className="player-tabs" role="tablist" style={{ gridTemplateColumns: `repeat(${tabs.length}, 1fr)` }} aria-label={t("Tournament sections", "Разделы турнира")}>
                  {tabs.map((name) => (
                    <button type="button" role="tab" aria-selected={tab === name} className={`player-tab${tab === name ? " active" : ""}`} key={name}
                      onClick={() => setParams((p) => { const next = new URLSearchParams(p); if (name === "standings") next.delete("tab"); else next.set("tab", name); return next; }, { replace: true })}>
                      {t(...TAB_LABELS[name])}
                    </button>
                  ))}
                </div>

                {tab === "bracket" && tournament.bracket ? <Bracket rounds={tournament.bracket} unmatched={tournament.unmatched} />
                  : tab === "matches" ? <Matches tournamentId={tournament.id} />
                  : tab === "stats" ? <Stats tournament={tournament} />
                  : <Standings tournament={tournament} />}
                <p className="player-note tourney-note">{count(tournament.table.length, ["player with games", "players with games"], ["игрок с играми", "игрока с играми", "игроков с играми"])}</p>
              </>}
          </div>
        </div>
      </div>
    </main>
  );
}
