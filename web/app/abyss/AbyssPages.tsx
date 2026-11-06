import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { useLang } from "../i18n";
import { useCached } from "../cached";
import { fetchPhases, type PhaseDetail, type PhaseSummary } from "./api";
import { Credit, hpShort, MonsterIcon, PhaseBody, usePhase, useText } from "./AbyssView";
import { abyssCard } from "./shareImage";

// Saves the phase as a 1920×1080 picture (shareImage.ts).
function DownloadImage({ phase }: { phase: PhaseDetail }) {
  const { t, lang, date } = useLang();
  const tx = useText();
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      const blob = await abyssCard(phase, { ru: lang === "ru", tx, date });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `abyss-${phase.version}.png`;
      a.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } finally {
      setBusy(false);
    }
  };
  return (
    <button type="button" className="player-control abyss-download" onClick={save} disabled={busy}>
      {busy ? t("Drawing…", "Рисую…") : t("Download image", "Скачать картинку")}
    </button>
  );
}

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

function PhaseHeader({ phase }: { phase: PhaseDetail }) {
  const { t, date, count } = useLang();
  return (
    <header className="player-box player-header">
      <div className="player-label tourney-kicker">
        <Link className="player-match-link" to="/abyss">{t("Spiral Abyss", "Витая Бездна")}</Link> · {t("Floor 12", "12 этаж")}
        {phase.current && <span className="match-tag abyss-now">{t("Now", "Сейчас")}</span>}
        {phase.upcoming && <span className="match-tag abyss-next">{t("Next", "Следующая")}</span>}
      </div>
      <div className="abyss-title-row">
        <h1 className="player-nickname">{t("Version", "Версия")} {phase.version}</h1>
        <DownloadImage phase={phase} />
      </div>
      <p className="player-fullname">{date(phase.starts_on)} – {date(phase.ends_on)}</p>
      {phase.upcoming && <p className="player-note">{t("Not out yet: from the beta, it may still change before it starts.",
        "Ещё не вышла: данные из беты, до старта могут измениться.")}</p>}
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

type ArchiveSort = "date" | "hp" | "matches";
const ARCHIVE_SORTS: { key: ArchiveSort; label: [string, string] }[] = [
  { key: "date", label: ["Date", "Дата"] },
  { key: "hp", label: ["HP", "HP"] },
  { key: "matches", label: ["Matches", "Матчи"] },
];

function archiveValue(r: PhaseSummary, sort: ArchiveSort) {
  return sort === "hp" ? r.total_hp : sort === "matches" ? r.matches : r.starts_on;
}

function Archive({ current }: { current: number | null }) {
  const { t, date, lang } = useLang();
  const { data: rows } = useCached("abyss-phases", fetchPhases, "");
  const [all, setAll] = useState(false);
  const [params, setParams] = useSearchParams();
  const sortParam = params.get("sort");
  const sort: ArchiveSort = sortParam === "hp" || sortParam === "matches" ? sortParam : "date";
  const ascending = params.get("dir") === "asc";
  // Phases with tournament matches first in mind: the rest (before 2023) on request.
  const shown = useMemo(() => {
    const kept = (rows ?? []).filter((r) => all || r.matches > 0 || r.current || r.upcoming);
    // Phases without the value go last; equal ones newest first.
    return [...kept].sort((a, b) => {
      const x = archiveValue(a, sort), y = archiveValue(b, sort);
      if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
      if (x === y) return b.starts_on.localeCompare(a.starts_on);
      return (x < y ? -1 : 1) * (ascending ? 1 : -1);
    });
  }, [rows, all, sort, ascending]);
  if (!rows) return null;

  function sortBy(key: ArchiveSort) {
    const asc = key === sort && !ascending;
    setParams(() => {
      const next = new URLSearchParams(window.location.search);
      if (key === "date") next.delete("sort"); else next.set("sort", key);
      if (asc) next.set("dir", "asc"); else next.delete("dir");
      return next;
    }, { replace: true, preventScrollReset: true });
  }

  return (
    <section className="player-box">
      <h2 className="player-box-title abyss-archive-title">
        <span>{t("All phases", "Все сезоны")}</span>
        <span className="player-segment" role="group" aria-label={t("Sort the phases", "Сортировка сезонов")}>
          {ARCHIVE_SORTS.map((s) => (
            <button type="button" key={s.key} className={`player-control${sort === s.key ? " active" : ""}`} aria-pressed={sort === s.key} onClick={() => sortBy(s.key)}>
              {t(...s.label)}{sort === s.key ? (ascending ? " ↑" : " ↓") : ""}
            </button>
          ))}
        </span>
      </h2>
      {shown.map((r) => (
        <Link className={`abyss-archive-row${r.id === current ? " is-current" : ""}`} to={`/abyss/${r.id}`} key={r.id}>
          <span className="abyss-archive-ver">{r.version}{r.upcoming && <span className="match-tag abyss-next">{t("Next", "Следующая")}</span>}</span>
          <span className="gitv-date">{date(r.starts_on)} – {date(r.ends_on)}</span>
          <span className="abyss-archive-bosses" aria-hidden>{r.bosses.map((b, i) => <MonsterIcon monster={b} size={26} key={i} />)}</span>
          <span className="abyss-archive-moon player-ellipsis">{r.blessings.join(" · ")}</span>
          <span>HP {hpShort(r.total_hp, lang === "ru")}</span>
          <span className="abyss-archive-matches">{r.matches ? t(`${r.matches} matches`, `${r.matches} матчей`) : ""}</span>
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
