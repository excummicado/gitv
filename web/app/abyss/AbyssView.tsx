import { useState } from "react";
import { useLang } from "../i18n";
import type { AbyssMonster, Chamber, Guide, PhaseDetail, Shield, Text } from "./api";
import "./abyss.css";

// The API serves element icons under alioth's names.
const ELEMENT_FILE: Record<string, string> = {
  Pyro: "Fire", Hydro: "Water", Cryo: "Ice", Electro: "Elec", Anemo: "Wind", Geo: "Rock", Dendro: "Grass",
};
const ELEMENT_RU: Record<string, string> = {
  Pyro: "Пиро", Hydro: "Гидро", Cryo: "Крио", Electro: "Электро", Anemo: "Анемо", Geo: "Гео", Dendro: "Дендро",
  Physical: "Физ.", All: "Все",
};

export function useText() {
  const { lang } = useLang();
  return (t: Text) => (lang === "ru" && t.ru ? t.ru : t.en);
}

export function hpShort(hp: number | null, ru: boolean) {
  if (hp == null) return "—";
  if (hp >= 1_000_000) return `${(hp / 1_000_000).toFixed(hp >= 10_000_000 ? 1 : 2)}${ru ? " млн" : "M"}`;
  return `${Math.round(hp / 1000)}${ru ? " тыс." : "K"}`;
}

export function ElementIcon({ element, size = 14 }: { element: string | null; size?: number }) {
  const file = element ? ELEMENT_FILE[element] : undefined;
  if (!file) return null;
  return <img className="abyss-element" src={`/api/v1/abyss-assets/elements/${file}.png`} alt={element ?? ""} title={element ?? ""} width={size} height={size} loading="lazy" />;
}

export function MonsterIcon({ monster, size = 44 }: { monster: AbyssMonster; size?: number }) {
  return monster.icon
    ? <img className={`abyss-monster-icon el-${(monster.element ?? "none").toLowerCase()}`} src={monster.icon} alt="" width={size} height={size} loading="lazy" />
    : <span className="abyss-monster-icon is-empty" style={{ width: size, height: size }} />;
}

function elementName(element: string, ru: boolean) {
  return ru ? ELEMENT_RU[element] ?? element : element;
}

function shieldText(s: Shield, ru: boolean, locale: string) {
  if (s.hp != null) return ru ? `щит ${s.hp.toLocaleString(locale)} HP` : `${s.hp.toLocaleString(locale)} HP shield`;
  if (s.hits != null) return ru ? `щит на ${s.hits} ударов` : `${s.hits}-hit shield`;
  const name = s.element ? elementName(s.element, ru) : "";
  return ru ? `${name}-щит ${s.units} ед.` : `${name} shield ${s.units} U`;
}

// alioth's wave labels in the site's language: "WAVES 1~3", "Group A WAVE 2".
function waveLabel(label: string, ru: boolean) {
  return ru ? label.replace(/WAVES/g, "Волны").replace(/WAVE/g, "Волна").replace(/Group/g, "Группа") : label;
}

function MonsterRow({ monster }: { monster: AbyssMonster }) {
  const { lang, t } = useLang();
  const ru = lang === "ru";
  return (
    <div className="abyss-monster">
      <MonsterIcon monster={monster} />
      <div className="abyss-monster-text">
        <span className="abyss-monster-name">
          {monster.name}{monster.count > 1 && <b className="abyss-count"> ×{monster.count}</b>}
        </span>
        <span className="abyss-monster-meta">
          <ElementIcon element={monster.element} />
          <span title={monster.hp.toLocaleString(ru ? "ru-RU" : "en-GB")}>HP {monster.hp.toLocaleString(ru ? "ru-RU" : "en-GB")}</span>
          {monster.shields.length > 0 && <span className="abyss-shield">{monster.shields.map((s) => shieldText(s, ru, ru ? "ru-RU" : "en-GB")).join(", ")}</span>}
        </span>
        {monster.resistances.length > 0 && (
          <span className="abyss-res">
            {t("RES", "Сопр.")}{" "}
            {monster.resistances.map((r, i) => (
              <span key={i} className={r.value.startsWith("-") ? "is-low" : r.value === "0%" ? "" : "is-high"}>
                {r.elements.map((e) => elementName(e, ru)).join("/")} {r.value}{i < monster.resistances.length - 1 ? "; " : ""}
              </span>
            ))}
          </span>
        )}
      </div>
    </div>
  );
}

function Half({ chamber }: { chamber: Chamber }) {
  const { lang, t } = useLang();
  const ru = lang === "ru";
  return (
    <div className="abyss-half">
      <div className="abyss-half-head">
        <b>{t(`Half ${chamber.half}`, `${chamber.half}-я половина`)}</b>
        <span className="player-label">{chamber.level != null && `${t("Lv.", "Ур.")} ${chamber.level} · `}HP {hpShort(chamber.hp, ru)}</span>
      </div>
      {chamber.waves.map((w, i) => (
        <div className="abyss-wave" key={i}>
          {chamber.waves.length > 1 && <span className="abyss-wave-label player-label">{w.label ? waveLabel(w.label, ru) : t(`Wave ${i + 1}`, `Волна ${i + 1}`)}</span>}
          {w.monsters.map((m, j) => <MonsterRow monster={m} key={j} />)}
        </div>
      ))}
    </div>
  );
}

// Floor 12: three chambers, each in two halves side by side.
export function Chambers({ chambers }: { chambers: Chamber[] }) {
  const { lang } = useLang();
  const ru = lang === "ru";
  const byRoom = [1, 2, 3].map((n) => chambers.filter((c) => c.index === n).sort((a, b) => a.half - b.half));
  return (
    <div className="abyss-chambers">
      {byRoom.map((halves, i) => halves.length > 0 && (
        <section className="player-box abyss-chamber" key={i}>
          <h3 className="player-box-title abyss-chamber-title">
            <span>12-{i + 1}</span>
            <span className="player-label">HP {hpShort(halves.reduce((s, c) => s + c.hp, 0), ru)}</span>
          </h3>
          <div className="abyss-halves">{halves.map((c) => <Half chamber={c} key={c.half} />)}</div>
        </section>
      ))}
    </div>
  );
}

function Guides({ guides }: { guides: Guide[] }) {
  const { t } = useLang();
  const tx = useText();
  const [open, setOpen] = useState<string | null>(null);
  if (!guides.length) return null;
  return (
    <section className="player-box">
      <h2 className="player-box-title">{t("Boss mechanics", "Механики боссов")}</h2>
      {guides.map((g) => (
        <div className="abyss-guide" key={g.monster}>
          <button type="button" className="abyss-guide-head" aria-expanded={open === g.monster} onClick={() => setOpen(open === g.monster ? null : g.monster)}>
            {g.icon ? <img src={g.icon} alt="" width={28} height={28} loading="lazy" /> : <span />}
            <b>{g.monster}</b>
            <span className="abyss-guide-toggle" aria-hidden>{open === g.monster ? "−" : "+"}</span>
          </button>
          {open === g.monster && (
            <div className="abyss-guide-body">
              {g.mechanics.map((m, i) => (
                <div key={i}>
                  <b>{tx(m.title)}</b>
                  {m.lines.map((l, j) => <p key={j}>{tx(l)}</p>)}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </section>
  );
}

// Moon blessing, Ley Line Disorder and HP: the phase's rules at a glance.
export function PhaseRules({ phase }: { phase: PhaseDetail }) {
  const { t, lang } = useLang();
  const tx = useText();
  const ru = lang === "ru";
  return (
    <div className="abyss-rules">
      {phase.blessing_list.map((b) => (
        <div className="abyss-rule" key={b.name + b.desc.en.slice(0, 20)}>
          <span className="player-label">{t("Moon blessing", "Благословение луны")}</span>
          <b className="abyss-moon">{b.name}</b>
          <p>{tx(b.desc)}</p>
        </div>
      ))}
      {phase.disorder.length > 0 && (
        <div className="abyss-rule">
          <span className="player-label">{t("Ley Line Disorder", "Нарушение лей-линий")}</span>
          {phase.disorder.map((d, i) => <p key={i}>{tx(d)}</p>)}
        </div>
      )}
      <div className="abyss-rule abyss-rule-hp">
        <span className="player-label">{t("Floor 12 HP", "HP 12 этажа")}</span>
        <b>{hpShort(phase.total_hp, ru)}</b>
        {phase.hp_ratio != null && <span className="player-label">{t("enemy HP", "HP врагов")} ×{phase.hp_ratio}</span>}
      </div>
    </div>
  );
}

export function PhaseBody({ phase }: { phase: PhaseDetail }) {
  return (
    <>
      <PhaseRules phase={phase} />
      <Chambers chambers={phase.chambers} />
      <Guides guides={phase.guides} />
    </>
  );
}

export function Credit() {
  const { t } = useLang();
  return (
    <p className="player-note abyss-credit">
      {t("Abyss data: ", "Данные Бездны: ")}<a href="https://alioth.wiki/en/gi/abyss" target="_blank" rel="noopener noreferrer" className="player-match-link">alioth.wiki</a>
      {t(". Enemy and element icons © HoYoverse.", ". Иконки врагов и стихий © HoYoverse.")}
    </p>
  );
}
