import { Link } from "react-router";
import { useLang } from "../i18n";
import type { TournamentAbyss } from "./api";
import { hpShort, MonsterIcon, useText } from "./AbyssView";
import "./abyss.css";

// The Spiral Abyss floor 12 the tournament was played on: one block per phase its matches fall in.
export function TournamentAbyssBox({ phases }: { phases: TournamentAbyss[] }) {
  const { t, date, lang } = useLang();
  const tx = useText();
  if (!phases.length) return null;
  const several = phases.length > 1;
  return (
    <section className="player-box abyss-tournament">
      <h2 className="player-box-title">{several ? t("Spiral Abyss during the tournament (two phases)", "Бездна во время турнира (два сезона)") : t("Spiral Abyss during the tournament", "Бездна во время турнира")}</h2>
      {phases.map((p) => (
        <div className="abyss-tournament-phase" key={p.id}>
          <div className="abyss-tournament-head">
            <Link className="player-match-link abyss-tournament-ver" to={`/abyss/${p.id}`}>{t("Version", "Версия")} {p.version} · {t("Floor 12", "12 этаж")}</Link>
            <span className="gitv-date">{date(p.starts_on)} – {date(p.ends_on)}</span>
            {several && <span className="player-label">{t(`${p.matches} matches`, `матчей: ${p.matches}`)}</span>}
            {p.estimated && <span className="player-label" title={t("The tournament's date is estimated", "Дата турнира оценочная")}>≈ {t("by estimated date", "по оценочной дате")}</span>}
          </div>
          <div className="abyss-tournament-bosses">
            {p.bosses.map((b, i) => (
              <span className="abyss-tournament-boss" key={i} title={`12-${Math.floor(i / 2) + 1} · ${b.name} · HP ${b.hp.toLocaleString(lang === "ru" ? "ru-RU" : "en-GB")}`}>
                <MonsterIcon monster={b} size={40} />
                <small className="player-label">12-{Math.floor(i / 2) + 1}</small>
              </span>
            ))}
          </div>
          <dl className="abyss-tournament-facts">
            {p.blessings.length > 0 && <><dt className="player-label">{t("Moon", "Луна")}</dt><dd>{p.blessings.join(" · ")}</dd></>}
            {p.disorder.length > 0 && <><dt className="player-label">{t("Disorder", "Нарушение")}</dt><dd>{p.disorder.map((d, i) => <span key={i}>{tx(d)}</span>)}</dd></>}
            <dt className="player-label">HP</dt><dd>{hpShort(p.total_hp, lang === "ru")}{p.hp_ratio != null && <span className="player-label"> · {t("enemy HP", "HP врагов")} ×{p.hp_ratio}</span>}</dd>
          </dl>
        </div>
      ))}
    </section>
  );
}
