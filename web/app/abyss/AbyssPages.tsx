import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { useLang } from "../i18n";
import { fetchPhase, fetchPhases, type PhaseDetail, type PhaseSummary } from "./api";
import { Credit, hpShort, MonsterIcon, PhaseBody } from "./AbyssView";

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="player-content match-content">{children}</div>
        </div>
      </div>
    </main>
  );
}

function usePhase(id: string) {
  const [phase, setPhase] = useState<PhaseDetail | null>(null);
  const [error, setError] = useState("");
  const { t } = useLang();
  useEffect(() => {
    const controller = new AbortController();
    setPhase(null);
    setError("");
    fetchPhase(id, controller.signal).then(setPhase)
      .catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t("Couldn't load the Abyss.", "Не удалось загрузить Бездну.")); });
    return () => controller.abort();
  }, [id]);
  return { phase, error };
}

function PhaseHeader({ phase }: { phase: PhaseDetail }) {
  const { t, date, count } = useLang();
  return (
    <header className="player-box player-header">
      <div className="player-label tourney-kicker">
        <Link className="player-match-link" to="/abyss">{t("Spiral Abyss", "Витая Бездна")}</Link> · {t("Floor 12", "12 этаж")}
        {phase.current && <span className="match-tag abyss-now">{t("Now", "Сейчас")}</span>}
      </div>
      <h1 className="player-nickname">{t("Version", "Версия")} {phase.version}</h1>
      <p className="player-fullname">{date(phase.starts_on)} – {date(phase.ends_on)}</p>
      <div className="player-records">
        <div className="player-record"><span className="player-label">{t("Tournament matches", "Матчей турниров")}</span><span className="player-value">{phase.matches}</span></div>
        <div className="player-record"><span className="player-label">{t("Tournaments", "Турниров")}</span><span className="player-value">{phase.tournaments}</span></div>
        <div className="player-record"><span className="player-label">{t("Median clear time", "Медианное время")}</span>
          <span className="player-value" title={count(phase.games, ["game with times", "games with times"], ["игра со временем", "игры со временем", "игр со временем"])}>{phase.median_time == null ? "—" : `${Math.round(phase.median_time)}${t("s", " с")}`}</span></div>
      </div>
    </header>
  );
}

function PhaseTournaments({ phase }: { phase: PhaseDetail }) {
  const { t } = useLang();
  if (!phase.tournament_list.length) return null;
  return (
    <section className="player-box">
      <h2 className="player-box-title">{t("Tournaments on this Abyss", "Турниры на этой Бездне")}</h2>
      {phase.tournament_list.map((r) => (
        <Link className="abyss-tourney" to={`/tournament/${r.id}`} key={r.id}>
          <span className="player-ellipsis">{r.title}{r.estimated && <span className="player-label" title={t("Date estimated", "Дата оценочная")}> ≈</span>}</span>
          <span className="player-label">{r.matches}</span>
        </Link>
      ))}
    </section>
  );
}

function Archive({ current }: { current: number | null }) {
  const { t, date, lang } = useLang();
  const [rows, setRows] = useState<PhaseSummary[] | null>(null);
  const [all, setAll] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetchPhases(controller.signal).then(setRows).catch(() => {});
    return () => controller.abort();
  }, []);
  if (!rows) return null;
  // Phases with tournament matches first in mind: the rest (before 2023) on request.
  const shown = all ? rows : rows.filter((r) => r.matches > 0 || r.current);
  return (
    <section className="player-box">
      <h2 className="player-box-title">{t("All phases", "Все сезоны")}</h2>
      {shown.map((r) => (
        <Link className={`abyss-archive-row${r.id === current ? " is-current" : ""}`} to={`/abyss/${r.id}`} key={r.id}>
          <span className="abyss-archive-ver">{r.version}</span>
          <span className="gitv-date">{date(r.starts_on)} – {date(r.ends_on)}</span>
          <span className="abyss-archive-bosses" aria-hidden>{r.bosses.map((b, i) => <MonsterIcon monster={b} size={26} key={i} />)}</span>
          <span className="abyss-archive-moon player-ellipsis">{r.blessings.join(" · ")}</span>
          <span className="hide-xs">HP {hpShort(r.total_hp, lang === "ru")}</span>
          <span className="player-label hide-xs">{r.matches ? t(`${r.matches} matches`, `${r.matches} матчей`) : ""}</span>
        </Link>
      ))}
      {!all && rows.length > shown.length && (
        <button type="button" className="player-control abyss-more" onClick={() => setAll(true)}>
          {t(`Show all ${rows.length} phases since 1.0`, `Показать все ${rows.length} сезонов с версии 1.0`)}
        </button>
      )}
    </section>
  );
}

// /abyss: the phase running now in full, then the archive.
export function AbyssPage() {
  const { phase, error } = usePhase("current");
  const { t } = useLang();
  return (
    <Frame>
      {error ? <div className="player-box player-message">{error}</div>
        : !phase ? <div className="player-box player-message">{t("Loading the Abyss…", "Загрузка Бездны…")}</div>
        : <><PhaseHeader phase={phase} /><PhaseBody phase={phase} /><PhaseTournaments phase={phase} /></>}
      <Archive current={phase?.id ?? null} />
      <Credit />
    </Frame>
  );
}

// /abyss/:phaseId: one phase, with the tournaments played on it.
export function AbyssPhasePage({ phaseId }: { phaseId: string }) {
  const { phase, error } = usePhase(phaseId);
  const { t } = useLang();
  return (
    <Frame>
      {error ? <div className="player-box player-message">{error}</div>
        : !phase ? <div className="player-box player-message">{t("Loading the Abyss…", "Загрузка Бездны…")}</div>
        : <><PhaseHeader phase={phase} /><PhaseBody phase={phase} /><PhaseTournaments phase={phase} /><Credit /></>}
    </Frame>
  );
}
