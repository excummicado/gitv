import { useEffect, useMemo, useState } from "react";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { useCurrentUser } from "../auth/useCurrentUser";
import { useLang } from "../i18n";
import {
  cellVolume, fetchBundleStats, rowVolume,
  type AgentInfo, type BundleStats, type Pair, type Volume,
} from "./api";
import "./bundles.css";

type Tab = "pairs" | "levels" | "teams" | "bundles" | "inseparable";
const LEVELS = [0, 1, 2, 3, 4, 5, 6];

function useFormat() {
  const { t, locale, lang } = useLang();
  return useMemo(() => {
    const sec = (v: number | null | undefined, digits = 1) =>
      v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toLocaleString(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
    const name = (agents: Record<string, AgentInfo>, id: string | null) => {
      const a = id ? agents[id] : undefined;
      return (lang === "ru" ? a?.name_ru : a?.name_en) ?? a?.name_en ?? "?";
    };
    const games = (n: number, p: number) => `${n} ${t("games", "игр")} · ${p} ${t("players", "игроков")}`;
    return { t, sec, name, games, percent: (v: number | null) => (v == null ? "—" : `${Math.round(v * 100)}%`) };
  }, [t, locale, lang]);
}

function Icon({ agent }: { agent?: AgentInfo }) {
  return agent?.icon
    ? <img src={agent.icon} alt="" width={30} height={30} loading="lazy" className={`bs-icon rarity-${agent.rarity ?? 4}`} />
    : <span className="bs-icon" />;
}

function Agents({ ids, agents, fallback }: { ids: (string | null)[]; agents: Record<string, AgentInfo>; fallback?: string }) {
  const f = useFormat();
  const known = ids.every((id) => id && agents[id]);
  return (
    <span className="bs-agents">
      <span className="bs-icons">{ids.map((id, i) => <Icon key={i} agent={id ? agents[id] : undefined} />)}</span>
      <span className="bs-names">{known || !fallback ? ids.map((id) => f.name(agents, id)).join(" + ") : fallback}</span>
    </span>
  );
}

function Data({ volume, games, players }: { volume: Volume; games: number; players: number }) {
  const f = useFormat();
  return <span className={`bs-data bs-${volume}`}><i aria-hidden />{games === 0 ? f.t("no games", "нет игр") : f.games(games, players)}</span>;
}

/** The effect as a number with a bar: to the left of the middle line is faster, to the right slower. */
function Effect({ value, lo, hi, scale }: { value: number | null; lo?: number | null; hi?: number | null; scale: number }) {
  const f = useFormat();
  if (value == null) return <span className="bs-effect bs-effect--none">—</span>;
  const width = Math.min(50, (Math.abs(value) / scale) * 50);
  return (
    <span className="bs-effect" title={lo != null && hi != null ? `${f.t("90% interval", "90% интервал")}: ${f.sec(lo)} … ${f.sec(hi)}` : undefined}>
      <b className={value < 0 ? "is-faster" : "is-slower"}>{f.sec(value)}</b>
      <span className="bs-bar" aria-hidden>
        <span className={value < 0 ? "is-faster" : "is-slower"} style={value < 0 ? { right: "50%", width: `${width}%` } : { left: "50%", width: `${width}%` }} />
      </span>
      {lo != null && hi != null && <small>{f.sec(lo)} … {f.sec(hi)}</small>}
    </span>
  );
}

function Legend() {
  const { t } = useLang();
  return (
    <div className="bs-legend">
      <span className="bs-data bs-high"><i aria-hidden />{t("plenty of data", "много данных")}</span>
      <span className="bs-data bs-mid"><i aria-hidden />{t("some data", "средне")}</span>
      <span className="bs-data bs-low"><i aria-hidden />{t("little data", "мало данных")}</span>
      <span className="bs-data bs-none"><i aria-hidden />{t("no games: the model's guess", "игр нет: расчёт модели")}</span>
    </div>
  );
}

function ConstGrid({ pair, agents }: { pair: Pair; agents: Record<string, AgentInfo> }) {
  const f = useFormat();
  const [whole, setWhole] = useState(true);
  const values = whole ? pair.grid.t : pair.grid.s;
  return (
    <div className="bs-grid-box">
      <div className="bs-grid-head">
        <span>{f.t("Rows", "Строки")}: <b>{f.name(agents, pair.a)}</b> · {f.t("columns", "столбцы")}: <b>{f.name(agents, pair.b)}</b></span>
        <span className="player-segment">
          <button type="button" className={`player-control${whole ? " active" : ""}`} onClick={() => setWhole(true)}>{f.t("Whole effect", "Полный эффект")}</button>
          <button type="button" className={`player-control${whole ? "" : " active"}`} onClick={() => setWhole(false)}>{f.t("Pair only", "Только пара")}</button>
        </span>
      </div>
      <div className="bs-scroll">
        <table className="bs-grid">
          <thead><tr><th />{LEVELS.map((c) => <th key={c}>C{c}</th>)}</tr></thead>
          <tbody>
            {LEVELS.map((ca) => (
              <tr key={ca}>
                <th>C{ca}</th>
                {LEVELS.map((cb) => {
                  const i = ca * 7 + cb, n = pair.grid.n[i], p = pair.grid.p[i];
                  return (
                    <td key={cb} className={`bs-cell bs-${cellVolume(n, p)}`} title={n ? f.games(n, p) : f.t("No games: computed by the model", "Игр нет: расчёт модели")}>
                      <b>{f.sec(values[i])}</b>
                      <small>{n ? `${n} · ${p}` : "—"}</small>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="bs-hint">
        {whole
          ? f.t("Seconds per game against both at C0 without the pair: the characters' constellations plus the pair. Under the number: games · players.",
            "Секунды на игру относительно обоих на C0 без пары: созвездия персонажей плюс сама пара. Под числом: игр · игроков.")
          : f.t("Only what the pair adds beyond the two characters. It barely changes with constellations: the data doesn't show bundles getting stronger from them.",
            "Только то, что пара даёт сверх самих персонажей. От созвездий почти не меняется: данные не показывают, что связка от них усиливается.")}
      </p>
    </div>
  );
}

function Pairs({ data }: { data: BundleStats }) {
  const f = useFormat();
  const [all, setAll] = useState(false);
  const [byData, setByData] = useState(false);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const scale = useMemo(() => Math.max(...data.pairs.map((p) => Math.abs(p.e))), [data]);
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const has = (id: string) => `${data.agents[id]?.name_en ?? ""} ${data.agents[id]?.name_ru ?? ""}`.toLowerCase().includes(q);
    return data.pairs
      .filter((p) => (all || p.robust) && (!q || has(p.a) || has(p.b)))
      .sort((x, y) => (byData ? y.n - x.n : x.e - y.e));
  }, [data, all, byData, query]);
  return (
    <section className="player-box">
      <div className="player-controls">
        <span className="player-segment">
          <button type="button" className={`player-control${all ? "" : " active"}`} onClick={() => setAll(false)}>{f.t("Candidates", "Кандидаты")} · {data.meta.robust}</button>
          <button type="button" className={`player-control${all ? " active" : ""}`} onClick={() => setAll(true)}>{f.t("All pairs", "Все пары")} · {data.meta.pairs}</button>
        </span>
        <span className="player-segment">
          <button type="button" className={`player-control${byData ? "" : " active"}`} onClick={() => setByData(false)}>{f.t("By effect", "По эффекту")}</button>
          <button type="button" className={`player-control${byData ? " active" : ""}`} onClick={() => setByData(true)}>{f.t("By data", "По объёму данных")}</button>
        </span>
        <input className="bs-search" type="search" value={query} onChange={(e) => setQuery(e.target.value)}
          placeholder={f.t("Character", "Персонаж")} aria-label={f.t("Find a character", "Найти персонажа")} />
      </div>
      <div className="bs-row bs-row--head bs-row--pair">
        <span>{f.t("Pair", "Пара")}</span><span>{f.t("Data", "Данные")}</span><span>{f.t("Effect, s per game", "Эффект, с на игру")}</span>
        <span title={f.t("The effect without the pair's three most frequent players", "Эффект без трёх самых частых игроков пары")}>{f.t("Without top 3", "Без топ-3")}</span>
        <span>{f.t("Step", "Ступень")}</span><span>{f.t("Cost now", "Цена сейчас")}</span>
      </div>
      {rows.length === 0 && <p className="player-message">{f.t("Nothing found.", "Ничего не найдено.")}</p>}
      {rows.map((p) => {
        const key = `${p.a}-${p.b}`, volume = rowVolume(p.n, p.p);
        return (
          <div key={key} className={`bs-item bs-${volume}`}>
            <button type="button" className="bs-row bs-row--pair bs-row--button" aria-expanded={open === key} onClick={() => setOpen(open === key ? null : key)}>
              <Agents ids={[p.a, p.b]} agents={data.agents} />
              <Data volume={volume} games={p.n} players={p.p} />
              <Effect value={p.e} lo={p.lo} hi={p.hi} scale={scale} />
              <span className="bs-num" title={`${f.t("Share of the three most frequent players", "Доля трёх самых частых игроков")}: ${f.percent(p.top3)}`}>{f.sec(p.wo3)}</span>
              <span className="bs-num">{p.tier ?? (p.reliable ? f.t("few players", "мало игроков") : "—")}</span>
              <span className="bs-num">{p.cost ?? "—"}</span>
            </button>
            {open === key && <ConstGrid pair={p} agents={data.agents} />}
          </div>
        );
      })}
    </section>
  );
}

function Levels({ data }: { data: BundleStats }) {
  const f = useFormat();
  const [query, setQuery] = useState("");
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return Object.entries(data.levels)
      .map(([id, levels]) => ({ id, levels, games: levels.reduce((sum, l) => sum + (l?.n ?? 0), 0) }))
      .filter((r) => !q || `${data.agents[r.id]?.name_en ?? ""} ${data.agents[r.id]?.name_ru ?? ""}`.toLowerCase().includes(q))
      .sort((x, y) => y.games - x.games);
  }, [data, query]);
  return (
    <section className="player-box">
      <div className="player-controls">
        <input className="bs-search" type="search" value={query} onChange={(e) => setQuery(e.target.value)}
          placeholder={f.t("Character", "Персонаж")} aria-label={f.t("Find a character", "Найти персонажа")} />
        <span className="player-label bs-hint-inline">{f.t("Seconds per game against the same character at C0; below it, the cost of that level and games · players.",
          "Секунды на игру относительно того же персонажа на C0; ниже — цена уровня и игр · игроков.")}</span>
      </div>
      <div className="bs-scroll">
        <table className="bs-levels">
          <thead><tr><th>{f.t("Character", "Персонаж")}</th>{LEVELS.map((c) => <th key={c}>C{c}</th>)}</tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <th><Agents ids={[r.id]} agents={data.agents} /></th>
                {LEVELS.map((c) => {
                  const l = r.levels[c];
                  if (!l) return <td key={c} className="bs-cell bs-none"><b>—</b></td>;
                  return (
                    <td key={c} className={`bs-cell bs-${rowVolume(l.n, l.p)}`}
                      title={l.n ? `${f.games(l.n, l.p)}${l.lo != null ? ` · ${f.sec(l.lo)} … ${f.sec(l.hi)}` : ""}` : f.t("No games: computed by the model", "Игр нет: расчёт модели")}>
                      <b>{c === 0 ? "0" : f.sec(l.e)}</b>
                      <small>{l.cost ?? "—"} {f.t("pts", "оч.")}</small>
                      <small>{l.n ? `${l.n} · ${l.p}` : "—"}</small>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Teams({ data }: { data: BundleStats }) {
  const f = useFormat();
  const [byPoint, setByPoint] = useState(false);
  const scale = useMemo(() => Math.max(...data.teams.map((x) => Math.abs(x.e))), [data]);
  const rows = useMemo(() => [...data.teams].sort((x, y) => (byPoint ? (x.spp ?? 0) - (y.spp ?? 0) : x.e - y.e)), [data, byPoint]);
  return (
    <section className="player-box">
      <div className="player-controls">
        <span className="player-segment">
          <button type="button" className={`player-control${byPoint ? "" : " active"}`} onClick={() => setByPoint(false)}>{f.t("Fastest", "Самые быстрые")}</button>
          <button type="button" className={`player-control${byPoint ? " active" : ""}`} onClick={() => setByPoint(true)}>{f.t("Seconds per point", "Секунд за очко")}</button>
        </span>
        <span className="player-label bs-hint-inline">{f.t("A team's number is the sum of the model's estimates for its characters and pairs, against an average team.",
          "Оценка команды — сумма оценок модели для её персонажей и пар, относительно средней команды.")}</span>
      </div>
      <div className="bs-row bs-row--head bs-row--team">
        <span>{f.t("Team", "Команда")}</span><span>{f.t("Data", "Данные")}</span><span>{f.t("Estimate, s per game", "Оценка, с на игру")}</span>
        <span title={f.t("How these games differ from a model without pairs: an independent check", "Насколько эти игры расходятся с моделью без пар: независимая проверка")}>{f.t("Check", "Проверка")}</span>
        <span>{f.t("Cost", "Стоимость")}</span><span>{f.t("s per point", "с за очко")}</span>
      </div>
      {rows.map((x) => {
        const volume = rowVolume(x.n, x.p);
        return (
          <div key={x.agents.join("-")} className={`bs-item bs-${volume}`}>
            <div className="bs-row bs-row--team">
              <Agents ids={x.agents} agents={data.agents} />
              <Data volume={volume} games={x.n} players={x.p} />
              <Effect value={x.e} lo={x.lo} hi={x.hi} scale={scale} />
              <span className="bs-num">{f.sec(x.resid)}</span>
              <span className="bs-num">{x.cost ?? "—"}</span>
              <span className="bs-num">{x.spp == null ? "—" : f.sec(x.spp, 2)}</span>
            </div>
          </div>
        );
      })}
    </section>
  );
}

function Bundles({ data }: { data: BundleStats }) {
  const f = useFormat();
  const { lang } = useLang();
  const scale = useMemo(() => Math.max(1, ...data.bundles.map((x) => Math.abs(x.e ?? 0))), [data]);
  return (
    <section className="player-box">
      <div className="bs-row bs-row--head bs-row--bundle">
        <span>{f.t("Bundle", "Связка")}</span><span>{f.t("Data", "Данные")}</span><span>{f.t("Effect, s per game", "Эффект, с на игру")}</span>
        <span>{f.t("Cost now", "Цена сейчас")}</span><span>{f.t("Verdict", "Вывод")}</span>
      </div>
      {data.bundles.map((x, i) => {
        const volume = rowVolume(x.n, x.p), condition = lang === "ru" ? x.cond_ru || x.cond_en : x.cond_en;
        return (
          <div key={i} className={`bs-item bs-${volume}`}>
            <div className="bs-row bs-row--bundle">
              <span className="bs-stack">
                <Agents ids={x.agents} agents={data.agents} fallback={x.names} />
                {condition && <small className="player-label">{condition}</small>}
              </span>
              <Data volume={volume} games={x.n} players={x.p} />
              <Effect value={x.e} lo={x.lo} hi={x.hi} scale={scale} />
              <span className="bs-num">{x.cost ?? "—"}</span>
              <span className="bs-num">{x.status === "reliable" ? f.t("holds up", "надёжно") : x.status === "no_data" ? f.t("no data", "нет данных") : f.t("not certain", "не доказано")}</span>
            </div>
          </div>
        );
      })}
    </section>
  );
}

function InseparableList({ data }: { data: BundleStats }) {
  const f = useFormat();
  const scale = useMemo(() => Math.max(1, ...data.inseparable.map((x) => Math.abs(x.e ?? 0))), [data]);
  return (
    <section className="player-box">
      <p className="bs-hint bs-hint--top">
        {f.t("A character almost always played next to another: what it gives alone and what the pair gives can't be told apart, so they are estimated together.",
          "Персонаж почти всегда играет рядом с другим: его личный вклад и вклад пары разделить нельзя, поэтому они оценены вместе.")}
      </p>
      <div className="bs-row bs-row--head bs-row--insep">
        <span>{f.t("Character → with whom", "Персонаж → с кем")}</span><span>{f.t("Data", "Данные")}</span>
        <span>{f.t("Together", "Вместе")}</span><span>{f.t("Together, s per game", "Совместно, с на игру")}</span><span>{f.t("Character's cost", "Цена персонажа")}</span>
      </div>
      {data.inseparable.map((x) => {
        const volume = rowVolume(x.n, x.p);
        return (
          <div key={`${x.a}-${x.b}`} className={`bs-item bs-${volume}`}>
            <div className="bs-row bs-row--insep">
              <Agents ids={[x.a, x.b]} agents={data.agents} />
              <Data volume={volume} games={x.n} players={x.p} />
              <span className="bs-num">{x.kind === "half" ? `${f.percent(x.half)} ${f.t("in one half", "в одной половине")}` : `${f.percent(x.draft)} ${f.t("in one draft", "в одном драфте")}`}</span>
              <Effect value={x.e} lo={x.lo} hi={x.hi} scale={scale} />
              <span className="bs-num">{x.cost ?? "—"}</span>
            </div>
          </div>
        );
      })}
    </section>
  );
}

export function BundlesPage() {
  const user = useCurrentUser();
  const allowed = user?.role === "super_admin";
  const f = useFormat();
  const { date } = useLang();
  const [data, setData] = useState<BundleStats | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("pairs");

  useEffect(() => {
    if (!allowed) return;
    fetchBundleStats().then(setData).catch((err) => setError(err instanceof Error ? err.message : f.t("Couldn't load the bundles.", "Не удалось загрузить связки.")));
  }, [allowed]);

  const tabs: [Tab, string][] = [
    ["pairs", f.t("Pairs", "Пары")], ["levels", f.t("Constellations", "Созвездия персонажей")], ["teams", f.t("Teams", "Команды")],
    ["bundles", f.t("Current bundles", "Текущие связки")], ["inseparable", f.t("Inseparable", "Неразлучные")],
  ];
  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="player-content bs-content">
            {!allowed ? <p className="player-box player-message">{f.t("This page isn't open yet.", "Эта страница пока закрыта.")}</p>
              : error ? <p className="player-box player-message">{error}</p>
              : !data ? <p className="player-box player-message">{f.t("Loading bundles…", "Загрузка связок…")}</p>
              : <>
                <section className="player-box bs-intro">
                  <h1 className="bs-title">{f.t("Bundles: what they do to the timer", "Связки: влияние на таймер")}</h1>
                  <p className="bs-lead">
                    {f.t("How many seconds per game a pair in one half clears the Abyss faster than its two characters would apart. Minus is faster.",
                      "На сколько секунд за игру пара в одной половине проходит Бездну быстрее, чем эти два персонажа по отдельности. Минус — быстрее.")}
                  </p>
                  <div className="player-records bs-records">
                    <div className="player-record"><span className="player-label">{f.t("Games", "Игры")}</span><span className="player-value">{date(data.meta.from)} – {date(data.meta.to)}</span></div>
                    <div className="player-record"><span className="player-label">{f.t("Players' results", "Результатов игроков")}</span><span className="player-value">{data.meta.games}</span></div>
                    <div className="player-record"><span className="player-label">{f.t("Players", "Игроков")}</span><span className="player-value">{data.meta.players}</span></div>
                    <div className="player-record"><span className="player-label">{f.t("Pairs / candidates", "Пар / кандидатов")}</span><span className="player-value">{data.meta.pairs} / {data.meta.robust}</span></div>
                  </div>
                  <Legend />
                  <details className="bs-about">
                    <summary>{f.t("How to read this", "Как это читать")}</summary>
                    <ul>
                      <li>{f.t("Color shows how much data is behind a number, not how good the number is. Trust green, doubt red; grey cells have no games at all.",
                        "Цвет показывает, сколько данных стоит за числом, а не насколько оно хорошее. Зелёному можно доверять, красному — с осторожностью; в серых ячейках игр нет вовсе.")}</li>
                      <li>{f.t(`The Abyss phase, the player, Elo before the match, constellations and weapons are accounted for. No player weighs more than ${data.meta.weight_cap} games, and a player's skill on their own main character is taken out.`,
                        `Учтены фаза Бездны, игрок, Эло до матча, созвездия и оружие. Ни один игрок не весит больше ${data.meta.weight_cap} игр, а мастерство игрока на своём основном персонаже вынесено отдельно.`)}</li>
                      <li>{f.t("Candidates are pairs whose effect is certain, holds without their three most frequent players and was played by 15 or more people.",
                        "Кандидаты — пары, у которых эффект надёжен, сохраняется без трёх самых частых игроков и которыми играли 15 и более человек.")}</li>
                      <li>{f.t(`The signal is weak: estimates of the same pair on two random halves of the players agree poorly (correlation ${data.meta.stability}). Read the order and the step, not the exact seconds.`,
                        `Сигнал слабый: оценки одной пары на двух случайных половинах игроков совпадают плохо (корреляция ${String(data.meta.stability).replace(".", ",")}). Смотрите на порядок и ступень, а не на точные секунды.`)}</li>
                      <li>{f.t("A player's constellation rarely changes, so differences between constellations always compare different people.",
                        "Созвездие у игрока обычно одно, поэтому разница между созвездиями — всегда сравнение разных людей.")}</li>
                    </ul>
                  </details>
                </section>
                <div className="bs-tabs" role="tablist">
                  {tabs.map(([id, label]) => (
                    <button type="button" role="tab" key={id} aria-selected={tab === id} className={`player-tab${tab === id ? " active" : ""}`} onClick={() => setTab(id)}>{label}</button>
                  ))}
                </div>
                {tab === "pairs" && <Pairs data={data} />}
                {tab === "levels" && <Levels data={data} />}
                {tab === "teams" && <Teams data={data} />}
                {tab === "bundles" && <Bundles data={data} />}
                {tab === "inseparable" && <InseparableList data={data} />}
              </>}
          </div>
        </div>
      </div>
    </main>
  );
}
