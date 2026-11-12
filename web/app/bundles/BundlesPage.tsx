import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { useCurrentUser } from "../auth/useCurrentUser";
import { useLang } from "../i18n";
import { fetchBundleStats, type AgentInfo, type BundleStats, type GridCell, type Pair, type Volume } from "./api";
import "./bundles.css";

type Tab = "pairs" | "levels" | "teams" | "bundles" | "inseparable";
const LEVELS = [0, 1, 2, 3, 4, 5, 6];

/** Words and numbers the whole page shares, so a second is written the same way everywhere. */
function useFormat() {
  const { t, locale, lang } = useLang();
  return useMemo(() => {
    const number = (v: number, digits = 1) => Math.abs(v).toLocaleString(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits });
    const s = t("s", "с");
    return {
      t,
      number,
      /** "26.2 s faster" / "3.9 s slower": what a negative or positive effect means, in words. */
      speed: (v: number) => (Math.abs(v) < 0.05 ? t("no difference", "без разницы")
        : v < 0 ? t(`${number(v)} s faster`, `быстрее на ${number(v)} ${s}`) : t(`${number(v)} s slower`, `медленнее на ${number(v)} ${s}`)),
      /** The 90% interval in words. */
      range: (lo: number, hi: number) => (hi <= 0 ? t(`likely ${number(hi)}–${number(lo)} s faster`, `скорее всего быстрее на ${number(hi)}–${number(lo)} ${s}`)
        : lo >= 0 ? t(`likely ${number(lo)}–${number(hi)} s slower`, `скорее всего медленнее на ${number(lo)}–${number(hi)} ${s}`)
        : t(`from ${number(lo)} s faster to ${number(hi)} s slower`, `от «быстрее на ${number(lo)} ${s}» до «медленнее на ${number(hi)} ${s}»`)),
      name: (agents: Record<string, AgentInfo>, id: string | null) => {
        const a = id ? agents[id] : undefined;
        return (lang === "ru" ? a?.name_ru : a?.name_en) ?? a?.name_en ?? "?";
      },
      games: (n: number, p: number) => t(`${n} games · ${p} players`, `${n} игр · ${p} игроков`),
      points: (v: number | null) => (v == null ? "—" : t(`${v} pts`, `${v} оч.`)),
    };
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
  return <span className={`bs-data bs-${volume}`}><i aria-hidden />{f.games(games, players)}</span>;
}

/** The effect in words, a bar from the middle line (left is faster) and the likely range under it. */
function Effect({ value, lo, hi, scale }: { value: number | null; lo?: number | null; hi?: number | null; scale: number }) {
  const f = useFormat();
  if (value == null) return <span className="bs-effect bs-effect--none">—</span>;
  const width = Math.min(50, (Math.abs(value) / scale) * 50);
  return (
    <span className="bs-effect">
      <b className={value < 0 ? "is-faster" : "is-slower"}>{f.speed(value)}</b>
      <span className="bs-bar" aria-hidden>
        <span className={value < 0 ? "is-faster" : "is-slower"} style={value < 0 ? { right: "50%", width: `${width}%` } : { left: "50%", width: `${width}%` }} />
      </span>
      {lo != null && hi != null && <small>{f.range(lo, hi)}</small>}
    </span>
  );
}

/** The same effect for the tight cells of a grid: the direction in small letters over the seconds. */
function Delta({ value }: { value: number }) {
  const f = useFormat();
  if (Math.abs(value) < 0.05) return <b>{f.t("no difference", "без разницы")}</b>;
  return (
    <>
      <small className="bs-dir">{value < 0 ? f.t("faster by", "быстрее на") : f.t("slower by", "медленнее на")}</small>
      <b className={value < 0 ? "is-faster" : "is-slower"}>{f.number(value)} {f.t("s", "с")}</b>
    </>
  );
}

/** What a tab shows and what each of its columns means, always open above the table. */
function About({ lead, terms }: { lead: ReactNode; terms: [string, ReactNode][] }) {
  return (
    <div className="bs-about">
      <p>{lead}</p>
      <dl>{terms.map(([term, meaning]) => <div key={term}><dt>{term}</dt><dd>{meaning}</dd></div>)}</dl>
    </div>
  );
}

function Hidden({ count, what }: { count: number; what: string }) {
  const { t } = useLang();
  if (!count) return null;
  return <p className="bs-hidden">{t(`Not shown: ${count} ${what} with too little data.`, `Не показано: ${count} ${what} — по ним слишком мало данных.`)}</p>;
}

function ConstGrid({ pair, agents }: { pair: Pair; agents: Record<string, AgentInfo> }) {
  const f = useFormat();
  const [whole, setWhole] = useState(true);
  const cells = useMemo(() => new Map<number, GridCell>(pair.grid.map((c) => [c[0], c])), [pair]);
  const a = f.name(agents, pair.a), b = f.name(agents, pair.b);
  // Only the constellations somebody played: rows and columns without a single cell are left out.
  const rows = LEVELS.filter((ca) => pair.grid.some((c) => Math.floor(c[0] / 7) === ca));
  const columns = LEVELS.filter((cb) => pair.grid.some((c) => c[0] % 7 === cb));
  if (pair.grid.length < 2) {
    return <div className="bs-grid-box"><p className="bs-hint">{f.t("There aren't enough games to split this pair by constellations.", "Игр не хватает, чтобы разбить эту пару по созвездиям.")}</p></div>;
  }
  return (
    <div className="bs-grid-box">
      <div className="bs-grid-head">
        <span>{f.t("By constellations", "По созвездиям")}: {f.t("rows", "строки")} — <b>{a}</b>, {f.t("columns", "столбцы")} — <b>{b}</b></span>
        <span className="player-segment">
          <button type="button" className={`player-control${whole ? " active" : ""}`} onClick={() => setWhole(true)}>{f.t("Characters + pair", "Персонажи + пара")}</button>
          <button type="button" className={`player-control${whole ? "" : " active"}`} onClick={() => setWhole(false)}>{f.t("Pair only", "Только пара")}</button>
        </span>
      </div>
      <div className="bs-scroll">
        <table className="bs-grid">
          <thead><tr><th />{columns.map((c) => <th key={c}>{b} C{c}</th>)}</tr></thead>
          <tbody>
            {rows.map((ca) => (
              <tr key={ca}>
                <th>{a} C{ca}</th>
                {columns.map((cb) => {
                  const cell = cells.get(ca * 7 + cb);
                  if (!cell) return <td key={cb} className="bs-cell bs-cell--empty" />;
                  const [, games, players, total, own, volume] = cell;
                  return (
                    <td key={cb} className={`bs-cell bs-${volume}`} title={`${f.speed(whole ? total : own)} · ${f.games(games, players)}`}>
                      <Delta value={whole ? total : own} />
                      <small>{f.t(`${games} games`, `${games} игр`)}</small>
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
          ? f.t(`Seconds per game against ${a} C0 and ${b} C0 playing apart, so the number holds both what their constellations give and what the pair gives.`,
            `Секунды на игру относительно «${a} C0 и ${b} C0 играют порознь», то есть в числе и то, что дают созвездия, и то, что даёт сама пара.`)
          : f.t("Only what the pair adds on top of the two characters. It is almost the same in every cell: the data doesn't show bundles growing stronger with constellations, so one cost for all constellations is fair.",
            "Только то, что пара добавляет сверх самих персонажей. Оно почти одинаково во всех клетках: данные не показывают, что связка усиливается от созвездий, поэтому одна цена на все созвездия честна.")}
        {" "}{f.t("Constellations and cells with too few games (under 20, or under 5 players) are left out.", "Созвездия и клетки, по которым мало игр (меньше 20 или меньше 5 игроков), не показаны.")}
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
      <About
        lead={f.t("Two characters in one half of a team. The number is how much faster the pair clears a game than the same two characters would be expected to apart: this is what a bundle should cost for.",
          "Два персонажа в одной половине команды. Число — на сколько пара проходит игру быстрее, чем ожидалось бы от этих же двух персонажей по отдельности: именно это и должна стоить связка.")}
        terms={[
          [f.t("Effect on the timer", "Влияние на таймер"), f.t("Seconds per game (three rooms). The line under it is the range the true value most likely lies in.", "Секунды на игру (три комнаты). Строка под числом — диапазон, в котором скорее всего лежит настоящее значение.")],
          [f.t("Without the 3 most frequent players", "Без 3 частых игроков"), f.t("The same effect counted without the three people who played the pair most. Close to the main number means the pair is strong by itself, not because of who plays it.", "Тот же эффект, посчитанный без трёх человек, которые играли парой чаще всех. Близко к основному числу — значит, сильна сама пара, а не те, кто ею играет.")],
          [f.t("Suggested cost", "Рекомендуемая цена"), f.t("A floor by how bundles are priced now: 11 for 22 s and more, 8 for 16–22 s, 5 below that. Only for candidates.", "Нижняя граница по тому, как связки оценены сейчас: 11 за 22 с и больше, 8 за 16–22 с, 5 за меньшее. Только для кандидатов.")],
          [f.t("Candidates", "Кандидаты"), f.t("Pairs whose effect is certain, holds without their three most frequent players and was played by 15 or more people. Click a pair to see it by constellations.", "Пары, у которых эффект подтверждён, сохраняется без трёх частых игроков и которыми играли 15 и более человек. Нажмите на пару, чтобы увидеть её по созвездиям.")],
        ]} />
      <div className="player-controls">
        <span className="player-segment">
          <button type="button" className={`player-control${all ? "" : " active"}`} onClick={() => setAll(false)}>{f.t("Candidates", "Кандидаты")} · {data.meta.robust}</button>
          <button type="button" className={`player-control${all ? " active" : ""}`} onClick={() => setAll(true)}>{f.t("All pairs", "Все пары")} · {data.meta.pairs}</button>
        </span>
        <span className="player-segment">
          <button type="button" className={`player-control${byData ? "" : " active"}`} onClick={() => setByData(false)}>{f.t("Strongest first", "Сначала сильные")}</button>
          <button type="button" className={`player-control${byData ? " active" : ""}`} onClick={() => setByData(true)}>{f.t("Most games first", "Сначала с большей выборкой")}</button>
        </span>
        <input className="bs-search" type="search" value={query} onChange={(e) => setQuery(e.target.value)}
          placeholder={f.t("Find a character", "Найти персонажа")} aria-label={f.t("Find a character", "Найти персонажа")} />
      </div>
      <div className="bs-row bs-row--head bs-row--pair">
        <span>{f.t("Pair", "Пара")}</span><span>{f.t("Data", "Сколько данных")}</span><span>{f.t("Effect on the timer", "Влияние на таймер")}</span>
        <span>{f.t("Without the 3 most frequent players", "Без 3 частых игроков")}</span><span>{f.t("Suggested cost", "Рекомендуемая цена")}</span><span>{f.t("Cost now", "Цена сейчас")}</span>
      </div>
      {rows.length === 0 && <p className="player-message">{f.t("Nothing found.", "Ничего не найдено.")}</p>}
      {rows.map((p) => {
        const key = `${p.a}-${p.b}`;
        return (
          <div key={key} className={`bs-item bs-${p.v}`}>
            <button type="button" className="bs-row bs-row--pair bs-row--button" aria-expanded={open === key} onClick={() => setOpen(open === key ? null : key)}>
              <Agents ids={[p.a, p.b]} agents={data.agents} />
              <Data volume={p.v} games={p.n} players={p.p} />
              <Effect value={p.e} lo={p.lo} hi={p.hi} scale={scale} />
              <span className="bs-num">{p.wo3 == null ? "—" : f.speed(p.wo3)}</span>
              <span className="bs-num">{p.tier ? <b>{f.points(p.tier)}</b> : <span className="bs-quiet">{f.t("not a candidate", "не кандидат")}</span>}</span>
              <span className="bs-num">{p.cost == null ? <span className="bs-quiet">{f.t("no bundle", "связки нет")}</span> : f.points(p.cost)}</span>
            </button>
            {open === key && <ConstGrid pair={p} agents={data.agents} />}
          </div>
        );
      })}
      {all && <Hidden count={data.meta.hidden.pairs} what={f.t("pairs", "пар")} />}
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
      <About
        lead={f.t("What a character's constellations do to the timer by themselves, next to what each level costs in the draft. A level that saves much time for few extra points is underpriced.",
          "Что созвездия персонажа дают таймеру сами по себе — рядом с ценой каждого уровня в драфте. Уровень, который экономит много времени за мало лишних очков, недооценён.")}
        terms={[
          [f.t("Base", "База"), f.t("The character's lowest constellation with enough games. Every other level is compared with it.", "Самое низкое созвездие персонажа, по которому хватает игр. С ним сравниваются остальные уровни.")],
          [f.t("Number in a cell", "Число в клетке"), f.t("How many seconds per game the level is faster or slower than the base. Under it, the level's cost and the games played.", "На сколько секунд за игру уровень быстрее или медленнее базы. Под ним — цена уровня и число игр.")],
          [f.t("Caution", "Осторожно"), f.t("A player's constellation rarely changes, so levels always compare different people. A yellow cell may hold as few as 15 of them.", "Созвездие у игрока обычно одно, поэтому уровни — всегда сравнение разных людей. В жёлтой клетке их может быть всего 15.")],
        ]} />
      <div className="player-controls">
        <input className="bs-search" type="search" value={query} onChange={(e) => setQuery(e.target.value)}
          placeholder={f.t("Find a character", "Найти персонажа")} aria-label={f.t("Find a character", "Найти персонажа")} />
        <span className="player-label bs-hint-inline">{f.t("Only characters with enough games at two levels or more; an empty cell has too few games.",
          "Только персонажи, у которых хватает игр хотя бы на двух уровнях; пустая клетка — мало игр.")}</span>
      </div>
      <div className="bs-scroll">
        <table className="bs-levels">
          <thead><tr><th>{f.t("Character", "Персонаж")}</th>{LEVELS.map((c) => <th key={c}>C{c}</th>)}</tr></thead>
          <tbody>
            {rows.map((r) => {
              const base = r.levels.findIndex(Boolean);
              return (
                <tr key={r.id}>
                  <th><Agents ids={[r.id]} agents={data.agents} /></th>
                  {LEVELS.map((c) => {
                    const l = r.levels[c];
                    if (!l) return <td key={c} className="bs-cell bs-cell--empty" />;
                    return (
                      <td key={c} className={`bs-cell bs-${l.v}`} title={`${c === base ? f.t("Base", "База") : f.speed(l.e)} · ${f.games(l.n, l.p)}`}>
                        {c === base ? <b>{f.t("base", "база")}</b> : <Delta value={l.e} />}
                        <small>{f.points(l.cost)}</small>
                        <small>{f.t(`${l.n} games`, `${l.n} игр`)}</small>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Teams({ data }: { data: BundleStats }) {
  const f = useFormat();
  const [byGain, setByGain] = useState(false);
  const scale = useMemo(() => Math.max(1, ...data.teams.map((x) => Math.abs(x.e))), [data]);
  const rows = useMemo(() => [...data.teams].sort((x, y) => (byGain ? (y.gain ?? 0) - (x.gain ?? 0) : x.e - y.e)), [data, byGain]);
  return (
    <section className="player-box">
      <About
        lead={f.t("Whole teams of four that were played often enough. A team that is fast and cheap is where the costs are too low.",
          "Целые четвёрки, которыми играли достаточно часто. Быстрая и при этом дешёвая команда — место, где цены занижены.")}
        terms={[
          [f.t("Against an average team", "Относительно средней команды"), f.t("How much faster the team clears a game than an average team of the same players. It is the sum of the model's numbers for its characters and pairs, not a separate measurement.", "На сколько команда проходит игру быстрее средней команды у тех же игроков. Это сумма оценок модели для её персонажей и пар, а не отдельное измерение.")],
          [f.t("Cost", "Стоимость"), f.t("The four characters at their usual constellations plus the bundles that apply, in the current Abyss Cup system.", "Четыре персонажа на их обычных созвездиях плюс действующие связки, в текущей системе Abyss Cup.")],
          [f.t("Seconds per point", "Секунд за очко"), f.t("Seconds saved for each point of cost. The higher, the more the team gives for its price.", "Сколько секунд выигрыша приходится на одно очко стоимости. Чем больше, тем больше команда даёт за свою цену.")],
        ]} />
      <div className="player-controls">
        <span className="player-segment">
          <button type="button" className={`player-control${byGain ? "" : " active"}`} onClick={() => setByGain(false)}>{f.t("Fastest first", "Сначала быстрые")}</button>
          <button type="button" className={`player-control${byGain ? " active" : ""}`} onClick={() => setByGain(true)}>{f.t("Best for the cost first", "Сначала выгодные")}</button>
        </span>
      </div>
      <div className="bs-row bs-row--head bs-row--team">
        <span>{f.t("Team", "Команда")}</span><span>{f.t("Data", "Сколько данных")}</span><span>{f.t("Against an average team", "Относительно средней команды")}</span>
        <span>{f.t("Cost", "Стоимость")}</span><span>{f.t("Seconds per point", "Секунд за очко")}</span>
      </div>
      {rows.map((x) => (
        <div key={x.agents.join("-")} className={`bs-item bs-${x.v}`}>
          <div className="bs-row bs-row--team">
            <Agents ids={x.agents} agents={data.agents} />
            <Data volume={x.v} games={x.n} players={x.p} />
            <Effect value={x.e} lo={x.lo} hi={x.hi} scale={scale} />
            <span className="bs-num">{f.points(x.cost)}</span>
            <span className="bs-num">{x.gain == null ? "—" : x.gain > 0 ? <b>{f.number(x.gain, 2)}</b> : <span className="bs-quiet">{f.t("slower than average", "медленнее средней")}</span>}</span>
          </div>
        </div>
      ))}
      <Hidden count={data.meta.hidden.teams} what={f.t("teams", "команд")} />
    </section>
  );
}

function Bundles({ data }: { data: BundleStats }) {
  const f = useFormat();
  const { lang } = useLang();
  const scale = useMemo(() => Math.max(1, ...data.bundles.map((x) => Math.abs(x.e))), [data]);
  return (
    <section className="player-box">
      <About
        lead={f.t("The bundles of the current Abyss Cup system, with what the games say about each. Compare a bundle's cost with its effect: a high cost for a small effect, or the other way round, is worth another look.",
          "Связки текущей системы Abyss Cup и то, что о каждой говорят игры. Сравните цену связки с её эффектом: высокая цена при малом эффекте или наоборот — повод пересмотреть.")}
        terms={[
          [f.t("Effect on the timer", "Влияние на таймер"), f.t("As for pairs: seconds per game beyond the characters themselves, and the likely range.", "Как у пар: секунды на игру сверх самих персонажей и вероятный диапазон.")],
          [f.t("Confirmed", "Подтверждён"), f.t("The range doesn't include zero and the effect holds when checked against chance. Not confirmed doesn't mean there is no effect, only that the games don't prove it.", "Диапазон не включает ноль, и эффект выдерживает проверку на случайность. «Не подтверждён» не значит, что эффекта нет, — только что игры его не доказывают.")],
        ]} />
      <div className="bs-row bs-row--head bs-row--bundle">
        <span>{f.t("Bundle", "Связка")}</span><span>{f.t("Data", "Сколько данных")}</span><span>{f.t("Effect on the timer", "Влияние на таймер")}</span>
        <span>{f.t("Cost now", "Цена сейчас")}</span><span>{f.t("Effect", "Эффект")}</span>
      </div>
      {data.bundles.map((x, i) => {
        const condition = lang === "ru" ? x.cond_ru || x.cond_en : x.cond_en;
        return (
          <div key={i} className={`bs-item bs-${x.v}`}>
            <div className="bs-row bs-row--bundle">
              <span className="bs-stack">
                <Agents ids={x.agents} agents={data.agents} fallback={x.names} />
                {condition && <small className="player-label">{f.t("Only with", "Только при")}: {condition}</small>}
              </span>
              <Data volume={x.v} games={x.n} players={x.p} />
              <Effect value={x.e} lo={x.lo} hi={x.hi} scale={scale} />
              <span className="bs-num">{f.points(x.cost)}</span>
              <span className="bs-num">{x.reliable ? <b>{f.t("confirmed", "подтверждён")}</b> : <span className="bs-quiet">{f.t("not confirmed", "не подтверждён")}</span>}</span>
            </div>
          </div>
        );
      })}
      <Hidden count={data.meta.hidden.bundles} what={f.t("bundles", "связок")} />
    </section>
  );
}

function InseparableList({ data }: { data: BundleStats }) {
  const f = useFormat();
  const scale = useMemo(() => Math.max(1, ...data.inseparable.map((x) => Math.abs(x.e ?? 0))), [data]);
  const percent = (v: number) => `${Math.round(v * 100)}%`;
  return (
    <section className="player-box">
      <About
        lead={f.t("Characters almost never played without a certain partner. What such a character gives alone and what the pair gives can't be told apart, so the two are counted as one.",
          "Персонажи, которые почти не играют без определённого напарника. Личный вклад такого персонажа и вклад пары разделить нельзя, поэтому они посчитаны как одно целое.")}
        terms={[
          [f.t("Played together", "Играют вместе"), f.t("The share of the character's games with the partner beside it: in the same half, or at least in the same draft.", "Доля игр персонажа, в которых напарник рядом: в той же половине или хотя бы в том же драфте.")],
          [f.t("Character with the pair", "Персонаж вместе с парой"), f.t("The character's own effect plus the pair's, in seconds per game. Empty when the two usually sit in different halves, where there is no pair to count.", "Личный эффект персонажа плюс эффект пары, секунды на игру. Пусто, если эти двое обычно стоят в разных половинах: там пары нет.")],
        ]} />
      <div className="bs-row bs-row--head bs-row--insep">
        <span>{f.t("Character → partner", "Персонаж → напарник")}</span><span>{f.t("Data", "Сколько данных")}</span>
        <span>{f.t("Played together", "Играют вместе")}</span><span>{f.t("Character with the pair", "Персонаж вместе с парой")}</span><span>{f.t("Character's cost", "Цена персонажа")}</span>
      </div>
      {data.inseparable.map((x) => (
        <div key={`${x.a}-${x.b}`} className={`bs-item bs-${x.v}`}>
          <div className="bs-row bs-row--insep">
            <Agents ids={[x.a, x.b]} agents={data.agents} />
            <Data volume={x.v} games={x.n} players={x.p} />
            <span className="bs-num">{x.kind === "half" ? f.t(`${percent(x.half)} in one half`, `${percent(x.half)} в одной половине`) : f.t(`${percent(x.draft)} in one draft`, `${percent(x.draft)} в одном драфте`)}</span>
            <Effect value={x.e} lo={x.lo} hi={x.hi} scale={scale} />
            <span className="bs-num">{f.points(x.cost)}</span>
          </div>
        </div>
      ))}
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

  const tabs: [Tab, string, number | null][] = data ? [
    ["pairs", f.t("Pairs", "Пары"), data.meta.pairs], ["levels", f.t("Constellations", "Созвездия"), Object.keys(data.levels).length],
    ["teams", f.t("Teams", "Команды"), data.teams.length], ["bundles", f.t("Current bundles", "Текущие связки"), data.bundles.length],
    ["inseparable", f.t("Inseparable", "Неразлучные"), data.inseparable.length],
  ] : [];
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
                    {f.t(`Which characters clear the Abyss faster together than apart, and by how many seconds, from ${data.meta.games} results of ${data.meta.players} players between ${date(data.meta.from)} and ${date(data.meta.to)}.`,
                      `Какие персонажи вместе проходят Бездну быстрее, чем порознь, и на сколько секунд — по ${data.meta.games} результатам ${data.meta.players} игроков с ${date(data.meta.from)} по ${date(data.meta.to)}.`)}
                  </p>
                  <div className="bs-keys">
                    <div>
                      <h2>{f.t("The numbers", "Числа")}</h2>
                      <p>{f.t("Seconds per game of three rooms. “Faster by 20 s” means the team finishes 20 seconds sooner than expected without the pair.",
                        "Секунды на одну игру из трёх комнат. «Быстрее на 20 с» — команда заканчивает на 20 секунд раньше, чем ожидалось бы без этой пары.")}</p>
                    </div>
                    <div>
                      <h2>{f.t("The colors", "Цвета")}</h2>
                      <p>
                        <span className="bs-data bs-high"><i aria-hidden />{f.t("plenty of data", "много данных")}</span>{" "}
                        <span className="bs-data bs-mid"><i aria-hidden />{f.t("enough data", "данных достаточно")}</span>
                      </p>
                      <p>{f.t("Color is about how many games stand behind a number, not about the number. Anything with too few games isn't shown at all.",
                        "Цвет — о том, сколько игр стоит за числом, а не о самом числе. Всё, по чему игр слишком мало, не показано вовсе.")}</p>
                    </div>
                    <div>
                      <h2>{f.t("How far to trust it", "Насколько верить")}</h2>
                      <p>{f.t("The order of pairs and the suggested step are reliable; the exact seconds are not. Treat “26 s” as “one of the strongest”, not as a measurement.",
                        "Порядку пар и рекомендуемой ступени цены верить можно, точным секундам — нет. «26 с» читайте как «одна из самых сильных», а не как замер.")}</p>
                    </div>
                  </div>
                  <details className="bs-method">
                    <summary>{f.t("How it was counted", "Как это посчитано")}</summary>
                    <ul>
                      <li>{f.t("A pair's effect is what is left of the room times after taking out the Abyss phase, the player's strength (their own average and Elo before the match), each character alone, constellations and weapons.",
                        "Эффект пары — то, что остаётся от времени комнат после вычета фазы Бездны, силы игрока (его собственное среднее и Эло до матча), каждого персонажа отдельно, созвездий и оружия.")}</li>
                      <li>{f.t(`So that costs suit everyone, no player weighs more than ${data.meta.weight_cap} games, and a player's skill on their own main character is counted apart from the pair.`,
                        `Чтобы цена подходила всем, ни один игрок не весит больше ${data.meta.weight_cap} игр, а мастерство игрока на своём основном персонаже считается отдельно от пары.`)}</li>
                      <li>{f.t(`Why the seconds are rough: counted on two random halves of the players, the same pairs agree only weakly (correlation ${data.meta.stability}).`,
                        `Почему секунды приблизительны: на двух случайных половинах игроков оценки одних и тех же пар совпадают слабо (корреляция ${String(data.meta.stability).replace(".", ",")}).`)}</li>
                      <li>{f.t("Shown: pairs, teams and constellation levels with 30+ games by 15+ players (green from 100 games by 30 players); grid cells with 20+ games by 5+ players (green from 50 by 15).",
                        "Показаны: пары, команды и уровни созвездий с 30+ играми у 15+ игроков (зелёные — от 100 игр у 30 игроков); клетки сетки с 20+ играми у 5+ игроков (зелёные — от 50 у 15).")}</li>
                    </ul>
                  </details>
                </section>
                <div className="bs-tabs" role="tablist">
                  {tabs.map(([id, label, count]) => (
                    <button type="button" role="tab" key={id} aria-selected={tab === id} className={`player-tab${tab === id ? " active" : ""}`} onClick={() => setTab(id)}>
                      {label}{count != null && <span className="bs-count">{count}</span>}
                    </button>
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
