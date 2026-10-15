import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { fetchMatchesByTournament, fetchTournaments, type GroupedMatches, type MatchSummary, type TournamentGroup, type TournamentItem } from "./api";
import "../player/player-page.css";
import "../home/gitv-preview.css";
import { OrganizerName } from "./OrganizerName";
import { useLang } from "../i18n";
import "./match-page.css";

// Tournaments per page; a tournament is never split across pages.
const PAGE_SIZE = 3;

function MatchRow({ match }: { match: MatchSummary }) {
  const [a, b] = match.sides;
  const { t, date } = useLang();
  return (
    <Link className="match-row" to={`/match/${match.id}`}>
      <span className="gitv-date">{date(match.created_at)}</span>
      <span className={`match-row-name${match.winner === 0 ? " is-winner" : ""}`}>{a?.name ?? "—"}</span>
      <span className="match-row-score">{a && b ? `${a.games_won} – ${b.games_won}` : "—"}</span>
      <span className={`match-row-name right${match.winner === 1 ? " is-winner" : ""}`}>{b?.name ?? "—"}</span>
      <span className="match-row-flags">
        {match.technical && <span className="match-tag warn">{t("Tech", "Тех.")}</span>}
        {match.winner == null && <span className="match-tag">{t("No result", "Нет результата")}</span>}
      </span>
    </Link>
  );
}

function TournamentSection({ group, onPick, filtered }: { group: TournamentGroup; onPick: (id: string) => void; filtered: boolean }) {
  const { tournament, items, places } = group;
  const first = items[items.length - 1]?.created_at;
  const last = items[0]?.created_at;
  const { t, date, count } = useLang();
  return (
    <section className="player-box">
      <h2 className="player-box-title match-game-title">
        {filtered ? <span>{tournament.title}</span>
          : <button type="button" className="match-section-link" onClick={() => onPick(tournament.id)}>{tournament.title}</button>}
        {tournament.organizer && <span className="match-game-meta">{t("by", "орг.")} <OrganizerName organizer={tournament.organizer} /></span>}
        <span className="match-game-meta">{count(tournament.matches, ["match", "matches"], ["матч", "матча", "матчей"])}</span>
        {first && last && <span className="gitv-date match-section-dates">{date(first)}{first.slice(0, 10) !== last.slice(0, 10) ? ` – ${date(last)}` : ""}</span>}
      </h2>
      {places.length > 0 && (
        <div className="match-places" aria-label={t("Top four", "Первые четыре места")}>
          {places.map((p) => (
            <Link className={`match-place place-${p.place}`} to={`/player/${p.player.id}`} key={p.place}>
              <span className="match-place-no">{p.place}</span>{p.player.name}
            </Link>
          ))}
        </div>
      )}
      {items.map((match) => <MatchRow match={match} key={match.id} />)}
    </section>
  );
}

export function MatchesPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const tournament = params.get("tournament") ?? "";
  const page = Math.max(1, Number(params.get("page")) || 1);

  const [search, setSearch] = useState(q);
  const [tournaments, setTournaments] = useState<TournamentItem[]>([]);
  const [list, setList] = useState<GroupedMatches | null>(null);
  const [error, setError] = useState("");
  const { t, count } = useLang();

  // Applied to the live URL, not the one from this render, so quick successive changes all stick.
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

  // Typing filters after a short pause; going back to page 1 because the old page may not exist any more.
  useEffect(() => {
    if (search.trim() === q) return;
    const timer = setTimeout(() => update({ q: search.trim(), page: "" }), 300);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    const controller = new AbortController();
    fetchTournaments(controller.signal).then(setTournaments).catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    fetchMatchesByTournament({ q, tournament, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE }, controller.signal)
      .then(setList)
      .catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t("Couldn't load the matches.", "Не удалось загрузить матчи.")); });
    return () => controller.abort();
  }, [q, tournament, page]);

  const pages = list ? Math.max(1, Math.ceil(list.total / PAGE_SIZE)) : 1;

  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="player-content match-content">
            <div className="player-box match-filters">
              <input className="match-input" type="search" placeholder={t("Player or tournament", "Игрок или турнир")} aria-label={t("Search by player or tournament", "Поиск по игроку или турниру")} value={search} onChange={(e) => setSearch(e.target.value)} />
              <select className="match-input" aria-label={t("Tournament", "Турнир")} value={tournament} onChange={(e) => update({ tournament: e.target.value, page: "" })}>
                <option value="">{t("All tournaments", "Все турниры")}</option>
                {tournaments.map((item) => <option value={item.id} key={item.id}>{item.title} ({item.matches})</option>)}
              </select>
            </div>

            {list && !error && (
              <p className="match-count player-label">
                {count(list.matches, ["match", "matches"], ["матч", "матча", "матчей"])} {t("in", "в")} {count(list.total, ["tournament", "tournaments"], ["турнире", "турнирах", "турнирах"])}
              </p>
            )}
            {error ? <p className="player-box match-empty">{error}</p>
              : !list ? <p className="player-box match-empty">{t("Loading matches…", "Загрузка матчей…")}</p>
              : !list.groups.length ? <p className="player-box match-empty">{t("No matches found.", "Матчи не найдены.")}</p>
              : list.groups.map((group) => (
                  <TournamentSection group={group} filtered={Boolean(tournament)} key={group.tournament.id}
                    onPick={(id) => { update({ tournament: id, page: "" }); window.scrollTo(0, 0); }} />
                ))}

            {list && pages > 1 && (
              <nav className="match-pager" aria-label={t("Pages", "Страницы")}>
                <button type="button" className="match-input" disabled={page <= 1} onClick={() => { update({ page: String(page - 1) }); window.scrollTo(0, 0); }}>{t("Previous", "Назад")}</button>
                <span className="player-label">{t(`Page ${page} of ${pages}`, `Страница ${page} из ${pages}`)}</span>
                <button type="button" className="match-input" disabled={page >= pages} onClick={() => { update({ page: String(page + 1) }); window.scrollTo(0, 0); }}>{t("Next", "Вперёд")}</button>
              </nav>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
