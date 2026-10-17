import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { MajorToggle } from "./MajorToggle";
import { useLang } from "../i18n";
import { fetchComparison, fetchPlayers, type CharacterCount, type Comparison, type CompareSide, type MeetingSide, type PlayerSummary } from "./api";
import "./compare.css";

type L = ReturnType<typeof useLang>;
// Which value is better: the higher, the lower (times, technical defeats), or neither (just shown).
type Better = "high" | "low" | null;
type Metric = { label: [string, string]; better: Better; get: (p: CompareSide) => number | null; show?: (v: number | null, p: CompareSide) => ReactNode };

const sec = (v: number | null) => (v == null ? "—" : `${v}s`);
const pct = (v: number | null) => (v == null ? "—" : `${v}%`);

const METRICS: { section: [string, string]; rows: Metric[] }[] = [
  { section: ["Achievements", "Достижения"], rows: [
    { label: ["Tournaments", "Турниры"], better: "high", get: (p) => p.tournaments },
    { label: ["Tournament wins", "Победы в турнирах"], better: "high", get: (p) => p.tournament_wins },
    { label: ["Finals lost (2nd)", "Вторые места"], better: "high", get: (p) => p.finals },
    { label: ["Top 4 finishes", "Топ-4"], better: "high", get: (p) => p.top_four },
  ] },
  { section: ["Results", "Результаты"], rows: [
    { label: ["Matches", "Матчи"], better: "high", get: (p) => p.matches },
    { label: ["Match winrate", "Винрейт матчей"], better: "high", get: (p) => p.match_winrate, show: (v, p) => <>{pct(v)} <small>{p.match_wins}/{p.matches}</small></> },
    { label: ["Games", "Игры"], better: "high", get: (p) => p.games },
    { label: ["Game winrate", "Винрейт игр"], better: "high", get: (p) => p.winrate, show: (v, p) => <>{pct(v)} <small>{p.wins}W/{p.losses}L</small></> },
    { label: ["First pick winrate", "Винрейт первым пиком"], better: "high", get: (p) => p.first_pick.winrate, show: (v) => pct(v) },
    { label: ["Second pick winrate", "Винрейт вторым пиком"], better: "high", get: (p) => p.second_pick.winrate, show: (v) => pct(v) },
    { label: ["Highest winstreak", "Лучшая серия побед"], better: "high", get: (p) => p.highest_winstreak },
    { label: ["Current winstreak", "Текущая серия"], better: "high", get: (p) => p.current_winstreak },
    { label: ["Technical defeats", "Тех. поражения"], better: "low", get: (p) => p.tech_losses },
    { label: ["Technical defeat rate", "Доля тех. поражений"], better: "low", get: (p) => p.tech_loss_rate, show: (v) => pct(v) },
  ] },
  { section: ["Times", "Время"], rows: [
    { label: ["Best time", "Лучшее время"], better: "low", get: (p) => p.times.best, show: (v) => sec(v) },
    { label: ["Average time", "Среднее время"], better: "low", get: (p) => p.times.average, show: (v) => sec(v) },
    { label: ["Average in wins", "Среднее в победах"], better: "low", get: (p) => p.times.average_win, show: (v) => sec(v) },
    { label: ["Average in losses", "Среднее в поражениях"], better: "low", get: (p) => p.times.average_loss, show: (v) => sec(v) },
    { label: ["Average first pick", "Среднее первым пиком"], better: "low", get: (p) => p.times.average_first_pick, show: (v) => sec(v) },
    { label: ["Average second pick", "Среднее вторым пиком"], better: "low", get: (p) => p.times.average_second_pick, show: (v) => sec(v) },
  ] },
];

function winner(a: number | null, b: number | null, better: Better): 0 | 1 | null {
  if (better == null || a == null || b == null || a === b) return null;
  return (better === "high") === (a > b) ? 0 : 1;
}

// Two values with a bar showing their share; the better one is highlighted.
function Row({ label, a, b, better, showA, showB }: { label: string; a: number | null; b: number | null; better: Better; showA: ReactNode; showB: ReactNode }) {
  const best = winner(a, b, better);
  const total = (a ?? 0) + (b ?? 0);
  // For "lower is better" the shorter value gets the longer bar.
  const share = total > 0 && a != null && b != null ? (better === "low" ? b / total : a / total) : 0.5;
  return (
    <div className="cmp-row">
      <span className={`cmp-value${best === 0 ? " is-better" : ""}`}>{showA}</span>
      <div className="cmp-mid">
        <span className="cmp-label">{label}</span>
        <div className="cmp-bar" aria-hidden><span style={{ width: `${share * 100}%` }} /></div>
      </div>
      <span className={`cmp-value right${best === 1 ? " is-better" : ""}`}>{showB}</span>
    </div>
  );
}

function Box({ title, children }: { title: ReactNode; children: ReactNode }) {
  return <section className="player-box"><h2 className="player-box-title">{title}</h2>{children}</section>;
}

function CharList({ items, l }: { items: CharacterCount[]; l: L }) {
  if (!items.length) return <p className="player-message">—</p>;
  return (
    <div>
      {items.map((c) => (
        <div className="cmp-char" key={c.character.id}>
          {c.character.icon ? <img src={c.character.icon} alt="" width={24} height={24} loading="lazy" className={`cmp-char-icon rarity-${c.character.rarity ?? 4}`} /> : <span className="cmp-char-icon" />}
          <span className="player-ellipsis">{l.name(c.character)}</span>
          <span className="player-label">{c.games}</span>
        </div>
      ))}
    </div>
  );
}

// Choose a player by name (any nickname they played under).
function PlayerPicker({ players, exclude, onPick, autoFocus }: { players: PlayerSummary[]; exclude: string; onPick: (id: string) => void; autoFocus?: boolean }) {
  const { t } = useLang();
  const [q, setQ] = useState("");
  const found = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return [];
    return players.filter((p) => p.id !== exclude && (p.name.toLowerCase().includes(needle) || p.other_names.some((n) => n.toLowerCase().includes(needle))))
      .sort((a, b) => b.matches - a.matches).slice(0, 8);
  }, [q, players, exclude]);
  return (
    <div className="cmp-picker">
      <input className="match-input" type="search" autoFocus={autoFocus} value={q} onChange={(e) => setQ(e.target.value)}
        placeholder={t("Find a player to compare with", "Найдите игрока для сравнения")} aria-label={t("Player to compare with", "Игрок для сравнения")} />
      {found.length > 0 && (
        <ul className="cmp-picker-list">
          {found.map((p) => (
            <li key={p.id}><button type="button" onClick={() => { onPick(p.id); setQ(""); }}>
              <b>{p.name}</b><span className="player-label">{p.matches} {t("matches", "матчей")}{p.other_names.length ? ` · ${p.other_names.slice(0, 2).join(", ")}` : ""}</span>
            </button></li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PlayerHead({ side, fallback, id, align }: { side: CompareSide | null; fallback: string; id: string; align: "left" | "right" }) {
  const { t } = useLang();
  const age = side?.profile?.age;
  return (
    <div className={`cmp-head ${align}`}>
      {side?.profile?.avatar_url && <img className="cmp-avatar" src={side.profile.avatar_url} alt="" width={56} height={56} />}
      <div className="cmp-head-text">
        <Link className="player-match-link cmp-name" to={`/player/${id}`}>{side?.name ?? fallback}</Link>
        <span className="player-label">{[side?.profile?.real_name, age ? t(`${age} y.o.`, `${age} лет`) : null].filter(Boolean).join(" · ") || " "}</span>
      </div>
    </div>
  );
}

function Form({ side }: { side: CompareSide }) {
  return (
    <div className="cmp-form">
      {side.last_games.slice(0, 10).map((g, i) => (
        <Link key={i} to={`/match/${g.match_id}`} className={`player-game ${g.result === "W" ? "win" : g.result === "L" ? "loss" : ""}`}>{g.result}</Link>
      ))}
    </div>
  );
}

function HeadToHead({ data, a, b, names }: { data: Comparison["head_to_head"]; a: string; b: string; names: [string, string] }) {
  const l = useLang();
  const { t, date } = l;
  const [sa, sb] = data.sides;
  if (!data.matches.length || !sa || !sb) {
    return <Box title={t("Head to head", "Личные встречи")}><p className="player-message">{t("These players haven't met in imported matches.", "Эти игроки не встречались в импортированных матчах.")}</p></Box>;
  }
  const rate = (r: { wins: number; games: number }) => (r.games ? `${Math.round((r.wins / r.games) * 1000) / 10}%` : "—");
  const rateNum = (r: { wins: number; games: number }) => (r.games ? r.wins / r.games : null);
  const rows: [string, number | null, number | null, Better, ReactNode, ReactNode][] = [
    [t("Matches won", "Выиграно матчей"), sa.match_wins, sb.match_wins, "high", sa.match_wins, sb.match_wins],
    [t("Games won", "Выиграно игр"), sa.game_wins, sb.game_wins, "high", sa.game_wins, sb.game_wins],
    [t("Game winrate", "Винрейт игр"), sa.game_winrate, sb.game_winrate, "high", pct(sa.game_winrate), pct(sb.game_winrate)],
    [t("Average time", "Среднее время"), sa.avg_time, sb.avg_time, "low", sec(sa.avg_time), sec(sb.avg_time)],
    [t("Best time", "Лучшее время"), sa.best_time, sb.best_time, "low",
      sa.best_match_id ? <Link className="player-match-link" to={`/match/${sa.best_match_id}`}>{sec(sa.best_time)}</Link> : sec(sa.best_time),
      sb.best_match_id ? <Link className="player-match-link" to={`/match/${sb.best_match_id}`}>{sec(sb.best_time)}</Link> : sec(sb.best_time)],
    [t("First pick winrate", "Винрейт первым пиком"), rateNum(sa.first_pick), rateNum(sb.first_pick), "high",
      <>{rate(sa.first_pick)} <small>{sa.first_pick.wins}/{sa.first_pick.games}</small></>, <>{rate(sb.first_pick)} <small>{sb.first_pick.wins}/{sb.first_pick.games}</small></>],
    [t("Second pick winrate", "Винрейт вторым пиком"), rateNum(sa.second_pick), rateNum(sb.second_pick), "high",
      <>{rate(sa.second_pick)} <small>{sa.second_pick.wins}/{sa.second_pick.games}</small></>, <>{rate(sb.second_pick)} <small>{sb.second_pick.wins}/{sb.second_pick.games}</small></>],
    [t("Technical defeats", "Тех. поражения"), sa.tech_losses, sb.tech_losses, "low", sa.tech_losses, sb.tech_losses],
  ];
  const streakName = data.streak ? (data.streak.player === a ? names[0] : names[1]) : null;
  const tags: Record<string, [string, string]> = { challonge: ["Challonge", "Challonge"], technical: ["Tech", "Тех."] };
  return (
    <>
      <Box title={t("Head to head", "Личные встречи")}>
        <div className="cmp-score">
          <span className={sa.match_wins > sb.match_wins ? "is-better" : ""}>{sa.match_wins}</span>
          <small>–</small>
          <span className={sb.match_wins > sa.match_wins ? "is-better" : ""}>{sb.match_wins}</span>
        </div>
        <p className="cmp-score-note player-label">
          {l.count(data.matches.length, ["meeting", "meetings"], ["встреча", "встречи", "встреч"])} · {l.count(data.tournaments, ["tournament", "tournaments"], ["турнир", "турнира", "турниров"])}
          {data.draws ? ` · ${t("draws", "ничьих")}: ${data.draws}` : ""}{data.no_result ? ` · ${t("no result", "без результата")}: ${data.no_result}` : ""}
          {streakName && data.streak && <> · {t("streak", "серия")}: <b>{streakName}</b> ×{data.streak.matches}</>}
        </p>
        {rows.map(([label, x, y, better, showX, showY]) => <Row key={label} label={label} a={x} b={y} better={better} showA={showX} showB={showY} />)}
      </Box>
      <div className="cmp-columns">
        <Box title={`${names[0]} · ${t("picked", "пики")}`}><CharList items={sa.most_picked} l={l} /></Box>
        <Box title={`${names[1]} · ${t("picked", "пики")}`}><CharList items={sb.most_picked} l={l} /></Box>
        <Box title={`${t("Banned against", "Банили против")} ${names[0]}`}><CharList items={sa.most_banned_by_opponent} l={l} /></Box>
        <Box title={`${t("Banned against", "Банили против")} ${names[1]}`}><CharList items={sb.most_banned_by_opponent} l={l} /></Box>
      </div>
      <Box title={t("Meetings", "История встреч")}>
        {data.matches.map((m) => (
          <Link className="cmp-meeting" to={`/match/${m.match_id}`} key={m.match_id}>
            <span className="gitv-date">{date(m.date)}</span>
            <span className="player-ellipsis cmp-meeting-tournament">{m.tournament.title}</span>
            <span className={`cmp-meeting-name${m.result === "W" ? " is-better" : ""}`}>{names[0]}</span>
            <span className="cmp-meeting-score">{m.games_won} – {m.games_lost}</span>
            <span className={`cmp-meeting-name right${m.result === "L" ? " is-better" : ""}`}>{names[1]}</span>
            <span className="cmp-meeting-tags">
              {m.source && tags[m.source] && <span className="match-tag">{t(...tags[m.source])}</span>}
              {m.result === "—" && <span className="match-tag">{t("No result", "Нет результата")}</span>}
            </span>
          </Link>
        ))}
      </Box>
    </>
  );
}

export function ComparePage({ playerId, otherId }: { playerId: string; otherId?: string }) {
  const [params, setParams] = useSearchParams();
  const major = params.get("major") === "1";
  const navigate = useNavigate();
  const l = useLang();
  const { t } = l;
  const [players, setPlayers] = useState<PlayerSummary[]>([]);
  const [data, setData] = useState<Comparison | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetchPlayers(controller.signal).then(setPlayers).catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!otherId) return;
    const controller = new AbortController();
    setData(null);
    setError("");
    fetchComparison(playerId, otherId, major ? "major" : "all", controller.signal)
      .then(setData)
      .catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t("Couldn't load the comparison.", "Не удалось загрузить сравнение.")); });
    return () => controller.abort();
  }, [playerId, otherId, major]);

  const nameOf = (id: string) => players.find((p) => p.id === id)?.name ?? "…";
  const go = (a: string, b?: string) => navigate(`/player/${a}/compare${b ? `/${b}` : ""}${major ? "?major=1" : ""}`);
  const [pa, pb] = data?.players ?? [null, null];
  const names: [string, string] = [pa?.name ?? nameOf(playerId), pb?.name ?? (otherId ? nameOf(otherId) : "")];

  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="player-content match-content">
            <div className="player-box cmp-top">
              <PlayerHead side={pa} fallback={names[0]} id={playerId} align="left" />
              <div className="cmp-vs">
                <span>VS</span>
                {otherId && <button type="button" className="player-control" onClick={() => go(otherId, playerId)} title={t("Swap sides", "Поменять местами")}>⇄</button>}
              </div>
              {otherId ? <PlayerHead side={pb} fallback={names[1]} id={otherId} align="right" />
                : <PlayerPicker players={players} exclude={playerId} onPick={(id) => go(playerId, id)} autoFocus />}
            </div>
            <div className="cmp-controls">
              {otherId && <PlayerPicker players={players} exclude={playerId} onPick={(id) => go(playerId, id)} />}
              <MajorToggle on={major} onChange={(on) => setParams((p) => { const next = new URLSearchParams(p); if (on) next.set("major", "1"); else next.delete("major"); return next; }, { replace: true })} />
            </div>

            {!otherId ? <p className="player-box player-message">{t("Pick a player to compare with.", "Выберите игрока для сравнения.")}</p>
              : error ? <p className="player-box player-message">{error}</p>
              : !data ? <p className="player-box player-message">{t("Loading comparison…", "Загрузка сравнения…")}</p>
              : <>
                {(!pa || !pb) && <p className="player-box player-message">
                  {t(`No games in major tournaments: ${[!pa && names[0], !pb && names[1]].filter(Boolean).join(", ")}.`,
                     `Нет игр в мейджорах: ${[!pa && names[0], !pb && names[1]].filter(Boolean).join(", ")}.`)}</p>}
                {pa && pb && (
                  <>
                    <Box title={t("Form · last 10 games", "Форма · последние 10 игр")}>
                      <div className="cmp-row cmp-form-row"><Form side={pa} /><span /><Form side={pb} /></div>
                    </Box>
                    {METRICS.map((group) => (
                      <Box title={t(...group.section)} key={group.section[0]}>
                        {group.rows.map((m) => {
                          const a = m.get(pa), b = m.get(pb);
                          return <Row key={m.label[0]} label={t(...m.label)} a={a} b={b} better={m.better}
                            showA={m.show ? m.show(a, pa) : a ?? "—"} showB={m.show ? m.show(b, pb) : b ?? "—"} />;
                        })}
                      </Box>
                    ))}
                    <Box title={t("Characters", "Персонажи")}>
                      {([
                        [t("Most picked", "Чаще всего пикает"), pa.most_picked, pb.most_picked],
                        [t("Most banned by opponents", "Чаще всего банят соперники"), pa.most_banned_against, pb.most_banned_against],
                      ] as const).map(([label, x, y]) => (
                        <div className="cmp-row" key={label}>
                          <span className="cmp-value">{x ? `${l.name(x.character)} · ${x.games}` : "—"}</span>
                          <div className="cmp-mid"><span className="cmp-label">{label}</span></div>
                          <span className="cmp-value right">{y ? `${l.name(y.character)} · ${y.games}` : "—"}</span>
                        </div>
                      ))}
                      <div className="cmp-row">
                        <span className="cmp-value">{pa.highest_winrate_character ? `${l.name(pa.highest_winrate_character.character)} · ${pct(pa.highest_winrate_character.winrate)}` : "—"}</span>
                        <div className="cmp-mid"><span className="cmp-label">{t("Best winrate character", "Лучший винрейт на персонаже")}</span></div>
                        <span className="cmp-value right">{pb.highest_winrate_character ? `${l.name(pb.highest_winrate_character.character)} · ${pct(pb.highest_winrate_character.winrate)}` : "—"}</span>
                      </div>
                    </Box>
                  </>
                )}
                <HeadToHead data={data.head_to_head} a={playerId} b={otherId} names={names} />
              </>}
          </div>
        </div>
      </div>
    </main>
  );
}
