import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { OrganizerName } from "../match/OrganizerName";
import { MajorToggle } from "../player/MajorToggle";
import { useLang } from "../i18n";
import { fetchTournamentList, type TournamentKind, type TournamentRow } from "./api";
import { DateRange, KIND_LABELS, Prize } from "./common";
import "./tournaments.css";

const KINDS: ("" | TournamentKind)[] = ["", "bracket", "groups", "qualifier", "team"];

export function TournamentsPage() {
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const kind = (params.get("kind") ?? "") as "" | TournamentKind;
  const major = params.get("major") === "1";
  const organizer = params.get("organizer") ?? "";
  const [rows, setRows] = useState<TournamentRow[] | null>(null);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const { t, count } = useLang();

  useEffect(() => {
    const controller = new AbortController();
    fetchTournamentList(controller.signal)
      .then(setRows)
      .catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t("Couldn't load the tournaments.", "Не удалось загрузить турниры.")); });
    return () => controller.abort();
  }, []);

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

  const organizers = useMemo(() => {
    const seen = new Map<string, string>();
    for (const r of rows ?? []) if (r.organizer) seen.set(r.organizer.id, r.organizer.name);
    return [...seen].sort((a, b) => a[1].localeCompare(b[1]));
  }, [rows]);

  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (rows ?? []).filter((r) =>
      (!needle || r.title.toLowerCase().includes(needle) || r.winner?.name.toLowerCase().includes(needle))
      && (!kind || r.kind === kind) && (!major || r.major) && (!organizer || r.organizer?.id === organizer));
  }, [rows, search, kind, major, organizer]);

  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="player-content match-content">
            <div className="player-box tourneys-filters">
              <input className="match-input tourneys-search" type="search" value={search} placeholder={t("Tournament or winner", "Турнир или победитель")}
                aria-label={t("Search tournaments", "Поиск турниров")} onChange={(e) => { setSearch(e.target.value); update({ q: e.target.value.trim() }); }} />
              <select className="match-input" value={kind} aria-label={t("Format", "Формат")} onChange={(e) => update({ kind: e.target.value })}>
                {KINDS.map((k) => <option value={k} key={k}>{k ? t(...KIND_LABELS[k]) : t("Any format", "Любой формат")}</option>)}
              </select>
              <select className="match-input" value={organizer} aria-label={t("Organizer", "Организатор")} onChange={(e) => update({ organizer: e.target.value })}>
                <option value="">{t("Any organizer", "Любой организатор")}</option>
                {organizers.map(([id, name]) => <option value={id} key={id}>{name}</option>)}
              </select>
              <MajorToggle on={major} onChange={(on) => update({ major: on ? "1" : "" })} />
            </div>

            {error ? <div className="player-box player-message">{error}</div>
              : !rows ? <div className="player-box player-message">{t("Loading tournaments…", "Загрузка турниров…")}</div>
              : (
                <section className="player-box">
                  <h2 className="player-box-title">{count(shown.length, ["tournament", "tournaments"], ["турнир", "турнира", "турниров"])}</h2>
                  <div className="tourneys-row tourneys-head player-label">
                    <span>{t("Dates", "Даты")}</span><span>{t("Tournament", "Турнир")}</span><span className="hide-sm">{t("Format", "Формат")}</span>
                    <span className="hide-xs">{t("Players", "Игроки")}</span><span className="hide-sm">{t("Prize", "Приз")}</span><span>{t("Winner", "Победитель")}</span>
                  </div>
                  {shown.length === 0 && <p className="player-message">{t("No tournaments match the filters.", "Нет турниров под эти фильтры.")}</p>}
                  {shown.map((r) => (
                    // A row is a link, but holds links of its own (organizer, winner), so it navigates on click instead of being an <a>.
                    <div className="tourneys-row" key={r.id} role="link" tabIndex={0}
                      onClick={(e) => { if (!(e.target as HTMLElement).closest("a")) navigate(`/tournament/${r.id}`); }}
                      onKeyDown={(e) => { if (e.key === "Enter") navigate(`/tournament/${r.id}`); }}>
                      <span className="gitv-date"><DateRange first={r.first_match} last={r.last_match} /></span>
                      <span className="tourneys-title">
                        <Link to={`/tournament/${r.id}`} className="player-match-link">{r.title}</Link>
                        {r.major && <span className="match-tag tourneys-major">{t("Major", "Мейджор")}</span>}
                        {r.organizer && <small className="player-label">{t("by", "орг.")} <OrganizerName organizer={r.organizer} /></small>}
                      </span>
                      <span className="hide-sm">{t(...KIND_LABELS[r.kind])}</span>
                      <span className="hide-xs">{r.players}</span>
                      <span className="hide-sm"><Prize prize={r.prize} currency={r.currency} /></span>
                      <span className="tourneys-winner">{r.winner ? <Link to={`/player/${r.winner.id}`} className="player-match-link">{r.winner.name}</Link> : "—"}</span>
                    </div>
                  ))}
                </section>
              )}
          </div>
        </div>
      </div>
    </main>
  );
}
