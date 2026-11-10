import { Link } from "react-router";
import { useLang } from "../i18n";
import { Nick } from "../components/PlayerNick";
import type { EloChange, PlayerDetail, PlayerMatch } from "./api";
import { StatBox, resultLetter, seconds } from "./playerParts";

function GameChip({ result }: { result: string }) {
  const l = useLang();
  const kind = result === "W" ? "win" : result === "L" ? "loss" : "";
  return <span className={`player-game ${kind}`}>{resultLetter(l, result)}</span>;
}

export type Sort = "new" | "old" | "fast" | "slow";
export type ResultFilter = "" | "W" | "L";
export type ListOptions = { sort: Sort; result: ResultFilter; complete: boolean };

export const SORTS: { value: Sort; label: [string, string] }[] = [
  { value: "new", label: ["Newest first", "Сначала новые"] },
  { value: "old", label: ["Oldest first", "Сначала старые"] },
  { value: "fast", label: ["Fastest time", "Быстрее всего"] },
  { value: "slow", label: ["Slowest time", "Медленнее всего"] },
];

// Matches tab: sort by date or average clear time, wins or losses only, hide incomplete matches.
function filterAndSort<T extends { date: string; result: string; technical: boolean }>(items: T[], time: (item: T) => number | null, o: ListOptions) {
  const shown = items.filter((item) => (!o.result || item.result === o.result) && (!o.complete || (!item.technical && time(item) != null)));
  return shown.sort((a, b) => {
    if (o.sort === "new" || o.sort === "old") {
      const order = a.date < b.date ? -1 : a.date > b.date ? 1 : 0;
      return o.sort === "old" ? order : -order;
    }
    // Rows without a time always go last.
    const x = time(a), y = time(b);
    if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
    return o.sort === "fast" ? x - y : y - x;
  });
}

function ListControls({ options, onChange, total, shown }: { options: ListOptions; onChange: (changes: Record<string, string>) => void; total: number; shown: number }) {
  const { t } = useLang();
  const results: [ResultFilter, string][] = [["", t("All", "Все")], ["W", t("Wins", "Победы")], ["L", t("Losses", "Поражения")]];
  return (
    <div className="player-controls">
      <select className="player-control" aria-label={t("Sort", "Сортировка")} value={options.sort} onChange={(e) => onChange({ sort: e.target.value === "new" ? "" : e.target.value })}>
        {SORTS.map((s) => <option value={s.value} key={s.value}>{t(...s.label)}</option>)}
      </select>
      <div className="player-segment" role="group" aria-label={t("Result", "Результат")}>
        {results.map(([value, label]) => (
          <button type="button" key={value || "all"} className={`player-control${options.result === value ? " active" : ""}`} aria-pressed={options.result === value} onClick={() => onChange({ result: value })}>{label}</button>
        ))}
      </div>
      <label className="player-check">
        <input type="checkbox" checked={options.complete} onChange={(e) => onChange({ complete: e.target.checked ? "1" : "" })} />
        {t("Hide incomplete", "Скрыть неполные")}
      </label>
      <span className="player-label player-controls-count">{shown === total ? total : `${shown} ${t("of", "из")} ${total}`}</span>
    </div>
  );
}

export function MatchList({ player, options, onChange }: { player: PlayerDetail; options: ListOptions; onChange: (changes: Record<string, string>) => void }) {
  const l = useLang();
  const { t } = l;
  const matches = filterAndSort<PlayerMatch>([...player.match_list], (m) => m.avg_time, options);
  return (
    <StatBox title={t("Matches", "Матчи")}>
      <ListControls options={options} onChange={onChange} total={player.match_list.length} shown={matches.length} />
      <div className="player-match player-match-head">
        <span>{t("Date", "Дата")}</span><span>{t("Opponent", "Соперник")}</span><span>{t("Tournament", "Турнир")}</span>
        <span>{t("Score", "Счёт")}</span><span>{t("Avg time", "Ср. время")}</span><span>{t("Result", "Итог")}</span>
        <span>{t("Elo", "Эло")}</span>
      </div>
      {matches.map((m) => (
        <div className="player-match" key={m.match_id}>
          <Link className="gitv-date player-match-link" to={`/match/${m.match_id}`}>{l.date(m.date)}</Link>
          <span className="player-ellipsis">{m.opponent ? <Link className="player-match-link" to={`/player/${m.opponent.id}`}><Nick id={m.opponent.id} name={m.opponent.name} /></Link> : "—"}</span>
          <Link className="player-label player-ellipsis player-match-link" to={`/match/${m.match_id}`}>{m.tournament}{m.technical ? t(" · incomplete", " · неполный") : ""}</Link>
          <span>{m.games_won} – {m.games_lost}</span>
          <span>{seconds(l, m.avg_time)}</span>
          <GameChip result={m.result} />
          {m.elo ? <EloDelta elo={m.elo} /> : <span className="player-label" title={t("Not rated", "Не идёт в рейтинг")}>—</span>}
        </div>
      ))}
      {!matches.length && <div className="player-box-body player-label">{t("No matches match these filters.", "Под эти фильтры матчей нет.")}</div>}
    </StatBox>
  );
}

const KIND_LABELS: Record<EloChange["kind"], [string, string]> = {
  major: ["major tournament", "мейджор"],
  series: ["Abyss Ascend / New Gen", "Abyss Ascend / New Gen"],
  fast: ["fast cup", "быстрый кубок"],
  other: ["smaller organizer", "небольшой организатор"],
};

// A match's Elo change, with the sum behind it on hover or focus: K × weight × (result − expected).
function EloDelta({ elo }: { elo: EloChange }) {
  const { t } = useLang();
  const num = (n: number, digits = 1) => String(Number(n.toFixed(digits)));
  const signed = (n: number) => (n > 0 ? "+" : n < 0 ? "−" : "±") + num(Math.abs(n));
  const outcome = elo.score === 1 ? t("win", "победа") : elo.score === 0 ? t("loss", "поражение") : t("draw", "ничья");
  const tone = elo.change > 0 ? " is-up" : elo.change < 0 ? " is-down" : "";
  return (
    <span className={`player-elo-delta${tone}`} tabIndex={0} aria-label={`${t("Elo", "Эло")} ${signed(elo.change)}`}>
      {signed(elo.change)}
      <span className="player-elo-tip" role="tooltip">
        <span className="player-elo-tip-row"><b>{elo.before} → {elo.after}</b><b className={tone}>{signed(elo.change)}</b></span>
        <span className="player-elo-tip-row"><span>{t("Opponent's Elo", "Эло соперника")}</span><span>{elo.opponent_before}</span></span>
        <span className="player-elo-tip-row"><span>{t("Expected score", "Ожидание (шанс)")}</span><span>{Math.round(elo.expected * 100)}%</span></span>
        <span className="player-elo-tip-row"><span>{t("Result", "Результат")}</span><span>{outcome} ({num(elo.score)})</span></span>
        <span className="player-elo-tip-row"><span>K</span><span>{elo.k}</span></span>
        <span className="player-elo-tip-row"><span>{t("Weight", "Вес")}</span><span>×{num(elo.weight, 2)}</span></span>
        <span className="player-elo-tip-formula">
          {elo.k} × {num(elo.weight, 2)} × ({num(elo.score)} − {num(elo.expected, 2)}) = {signed(elo.change)}
        </span>
        <span className="player-elo-tip-note">
          {elo.k > 20
            ? t("K 40: one of the player's first 10 rated matches (20 after).", "K 40: один из первых 10 рейтинговых матчей игрока (потом 20).")
            : t("K 20: the player has 10+ rated matches.", "K 20: у игрока уже 10+ рейтинговых матчей.")}
          {" "}
          {t(`Weight ${num(elo.weight, 2)}: ${KIND_LABELS[elo.kind][0]}`, `Вес ${num(elo.weight, 2)}: ${KIND_LABELS[elo.kind][1]}`)}
          {t(" (majors 1, Ascend/New Gen 0.85, fast cups 0.7, others 0.5).", " (мейджоры 1, Ascend/New Gen 0.85, быстрые кубки 0.7, прочие 0.5).")}
          {" "}
          {elo.expected >= 0.5
            ? t("The player was the favourite: a win gives less, a loss costs more.", "Игрок был фаворитом: победа даёт меньше, поражение стоит больше.")
            : t("The player was the underdog: a win gives more, a loss costs less.", "Игрок был андердогом: победа даёт больше, поражение стоит меньше.")}
        </span>
      </span>
    </span>
  );
}
