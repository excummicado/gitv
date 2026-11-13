import { useCallback, useEffect, useState } from "react";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { mayBet } from "../auth/client";
import { useAuth } from "../auth/useCurrentUser";
import { useLang } from "../i18n";
import {
  fetchLeaderboard, fetchMarkets, fetchMyBets, placeBet, setResult, visit,
  type BetStatus, type HistoryRow, type Market, type MarketState, type Result, type Standing, type Wallet,
} from "./api";
import "../profile/profile.css";
import "./bets.css";

const STATES: Record<MarketState, [string, string]> = {
  open: ["Bets are open", "Ставки открыты"],
  no_elo: ["No bets: a player has no Elo", "Ставок нет: у игрока нет Elo"],
  started: ["Started, waiting for the result", "Начался, ждёт результата"],
  settled: ["Settled", "Рассчитан"],
  void: ["Bets returned", "Ставки возвращены"],
};
const STATUSES: Record<BetStatus, [string, string]> = {
  pending: ["waiting", "ждёт"], won: ["won", "выиграла"], lost: ["lost", "проиграла"], refunded: ["returned", "возвращена"],
};

function useBetText() {
  const { t, locale, count } = useLang();
  return {
    t,
    points: (n: number) => n.toLocaleString(locale),
    odds: (value: number) => value.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    when: (value: string) => new Date(value).toLocaleString(locale, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }),
    days: (n: number) => count(n, ["day", "days"], ["день", "дня", "дней"]),
  };
}

function MarketCard({ market, wallet, onChange }: { market: Market; wallet: Wallet; onChange: (market: Market) => void }) {
  const f = useBetText();
  const { t } = f;
  const [side, setSide] = useState<0 | 1 | null>(null);
  const [amount, setAmount] = useState("100");
  const [confirming, setConfirming] = useState<Result | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const staked = market.my_bets.reduce((sum, bet) => sum + bet.amount, 0);
  const left = Math.min(wallet.rules.max_per_match - staked, wallet.balance);
  const canBet = market.state === "open" && wallet.can_bet && left >= wallet.rules.min_bet;
  const chosen = canBet ? side ?? market.my_side : null;
  const value = Number(amount);
  const valid = Number.isInteger(value) && value >= wallet.rules.min_bet && value <= left;
  const price = chosen == null ? null : market.players[chosen].odds;

  async function send(request: () => Promise<Market>) {
    setSaving(true);
    setError("");
    try {
      onChange(await request());
      setSide(null);
      setConfirming(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Something went wrong. Try again.", "Что-то пошло не так. Попробуйте ещё раз."));
      // The odds may have moved: show the new ones
      fetchMarkets().then((rows) => { const fresh = rows.find((m) => m.id === market.id); if (fresh) onChange(fresh); }).catch(() => {});
    } finally {
      setSaving(false);
    }
  }

  const results: [Result, string][] = [
    ["player1", t(`${market.players[0].name} won`, `Победил ${market.players[0].name}`)],
    ["player2", t(`${market.players[1].name} won`, `Победил ${market.players[1].name}`)],
    ["void", t("Return the bets", "Вернуть ставки")],
  ];

  return (
    <div className="bets-match">
      <div className="bets-match-head">
        <span>{market.tournament_title} · {f.when(market.starts_at)}</span>
        <span className={`bets-state bets-state--${market.state}`}>{t(...STATES[market.state])}</span>
      </div>
      <div className="bets-sides">
        {market.players.map((player, i) => {
          const index = i as 0 | 1;
          const pickable = canBet && (market.my_side == null || market.my_side === index);
          const body = (
            <>
              <span className="bets-side-top">
                <span className="bets-side-name">{player.name}</span>
                {player.odds != null && <span className="bets-side-odds">{f.odds(player.odds)}</span>}
              </span>
              <span className="bets-side-sub">
                {player.elo != null ? `Elo ${player.elo}` : t("no Elo", "нет Elo")}
                {player.stake > 0 && <> · {t(`${f.points(player.stake)} bet`, `поставлено ${f.points(player.stake)}`)}</>}
                {market.winner === index && <> · {t("winner", "победитель")}</>}
              </span>
            </>
          );
          const classes = `bets-side${chosen === index ? " is-chosen" : ""}${market.winner === index ? " is-winner" : ""}`;
          return market.state === "open"
            ? <button type="button" key={i} className={classes} disabled={!pickable} aria-pressed={chosen === index} onClick={() => { setSide(index); setError(""); }}>{body}</button>
            : <div key={i} className={classes}>{body}</div>;
        })}
      </div>
      {market.my_bets.length > 0 && market.my_side != null && (
        <p className="bets-mine">
          {t("Your bets on", "Ваши ставки на")} <b>{market.players[market.my_side].name}</b>:{" "}
          {market.my_bets.map((bet, i) => (
            <span key={i} className={bet.status === "won" ? "is-won" : bet.status === "lost" ? "is-lost" : undefined}>
              {i > 0 && ", "}{f.points(bet.amount)} × {f.odds(bet.odds)}
              {bet.status === "pending" ? t(` (pays ${f.points(bet.payout)})`, ` (выплата ${f.points(bet.payout)})`)
                : bet.status === "won" ? t(` (won ${f.points(bet.payout)})`, ` (выигрыш ${f.points(bet.payout)})`)
                : ` (${t(...STATUSES[bet.status])})`}
            </span>
          ))}
        </p>
      )}
      {chosen != null && price != null && (
        <form className="bets-form" onSubmit={(event) => { event.preventDefault(); if (valid) send(() => placeBet(market.id, chosen, value, price)); }} noValidate>
          <input className="bets-amount" type="number" inputMode="numeric" min={wallet.rules.min_bet} max={left} step={10}
            aria-label={t("Points to bet", "Сколько баллов поставить")} value={amount} onChange={(event) => { setAmount(event.target.value); setError(""); }} />
          <button type="submit" className="profile-action" disabled={saving || !valid}>
            {t(`Bet on ${market.players[chosen].name}`, `Поставить на ${market.players[chosen].name}`)}
          </button>
          <span className="bets-form-win">
            {valid ? t(`Pays ${f.points(Math.floor(value * price + 1e-9))} if they win. A bet can't be taken back.`, `При победе выплата ${f.points(Math.floor(value * price + 1e-9))}. Ставку нельзя отменить.`)
              : t(`From ${wallet.rules.min_bet} to ${f.points(left)} points.`, `От ${wallet.rules.min_bet} до ${f.points(left)} баллов.`)}
          </span>
        </form>
      )}
      {market.can_settle && (
        <div className="bets-settle">
          {confirming ? (
            <>
              <span>{results.find(([result]) => result === confirming)?.[1]}? {t("This can't be changed afterwards.", "Потом это не изменить.")}</span>
              <button type="button" className="profile-action" disabled={saving} onClick={() => send(() => setResult(market.id, confirming))}>{t("Confirm", "Подтвердить")}</button>
              <button type="button" className="profile-action profile-action--quiet" disabled={saving} onClick={() => setConfirming(null)}>{t("Cancel", "Отмена")}</button>
            </>
          ) : (
            <>
              <span>{t("Result:", "Результат:")}</span>
              {results.filter(([result]) => result === "void" || new Date(market.starts_at).getTime() <= Date.now()).map(([result, label]) => (
                <button type="button" key={result} className="profile-action profile-action--quiet" onClick={() => { setConfirming(result); setError(""); }}>{label}</button>
              ))}
            </>
          )}
        </div>
      )}
      {error && <p className="bets-error" role="alert">{error}</p>}
    </div>
  );
}

function History({ rows }: { rows: HistoryRow[] }) {
  const f = useBetText();
  const { t } = f;
  return (
    <section className="player-box">
      <h2 className="player-box-title">{t("My bets", "Мои ставки")}</h2>
      {rows.length === 0 ? <p className="match-empty">{t("No bets yet.", "Ставок пока нет.")}</p> : rows.map((row, i) => (
        <div className="bets-history-row" key={i}>
          <span className="gitv-date">{f.when(row.created_at)}</span>
          <span className="player-ellipsis">{row.player1} vs {row.player2}</span>
          <span className="player-ellipsis">{t("on", "на")} {row.side === 0 ? row.player1 : row.player2} · {f.points(row.amount)} × {f.odds(row.odds)}</span>
          <span className={row.status === "won" ? "is-won" : row.status === "lost" ? "is-lost" : "is-quiet"}>
            {row.status === "won" ? `+${f.points(row.payout - row.amount)}` : row.status === "lost" ? `−${f.points(row.amount)}` : t(...STATUSES[row.status])}
          </span>
        </div>
      ))}
    </section>
  );
}

// Bets for points on the announced matches: the member's points, this month's matches with their odds, the month's
// table and the member's own bets. Opening the page counts as the day's visit.
export function BetsPage() {
  const { user, ready } = useAuth();
  const allowed = mayBet(user);
  const f = useBetText();
  const { t } = f;
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [markets, setMarkets] = useState<Market[] | null>(null);
  const [table, setTable] = useState<Standing[]>([]);
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      // The visit first: it starts the month's points and closes last month's, which the rest read
      setWallet(await visit(true));
      const [m, s, h] = await Promise.all([fetchMarkets(), fetchLeaderboard(), fetchMyBets()]);
      setMarkets(m);
      setTable(s);
      setHistory(h);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Couldn't load the bets.", "Не удалось загрузить ставки."));
    }
  }, []);

  useEffect(() => {
    if (allowed) load();
  }, [allowed, load]);

  // After a bet or a result: the changed match at once, then the points, the table and the history
  function changed(market: Market) {
    setMarkets((rows) => rows?.map((m) => (m.id === market.id ? market : m)) ?? null);
    load();
  }

  const rules = wallet?.rules;
  // Matches that still take bets or wait for a result first, the finished ones after them
  const active = markets?.filter((m) => m.state === "open" || m.state === "started" || m.state === "no_elo") ?? [];
  const done = markets?.filter((m) => m.state === "settled" || m.state === "void") ?? [];

  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="player-content match-content">
            {!ready ? null
              : !allowed ? <p className="player-box player-message">{t("Bets are being tested and aren't open to you yet.", "Ставки тестируются и вам пока недоступны.")}</p>
              : error && !wallet ? <p className="player-box player-message">{error}</p>
              : !wallet || !markets || !rules ? <p className="player-box player-message">{t("Loading bets…", "Загрузка ставок…")}</p>
              : <>
                <section className="player-box">
                  <h2 className="player-box-title">{t("My points", "Мои баллы")}</h2>
                  <div className="bets-wallet">
                    <span className="bets-balance">{f.points(wallet.balance)}<small>{t("points", "баллов")}</small></span>
                    {wallet.bonus > 0 && <span className="bets-bonus">{t(`+${wallet.bonus} for today's visit`, `+${wallet.bonus} за сегодняшний заход`)}</span>}
                    <span className="bets-wallet-fact">{t("Visits in a row:", "Заходов подряд:")} <b>{f.days(wallet.streak)}</b></span>
                    {wallet.handicap > 0 && <span className="bets-wallet-fact">{t("Head start for last month:", "Фора за прошлый месяц:")} <b>+{wallet.handicap}</b></span>}
                  </div>
                  {!wallet.can_bet && <p className="bets-note">{t("Your Discord account is younger than six months, so you can't bet yet.", "Вашему Discord-аккаунту меньше полугода, поэтому ставить пока нельзя.")}</p>}
                  <details>
                    <summary className="player-label unresolved-hint">{t("Rules", "Правила")}</summary>
                    <ul className="bets-rules">
                      <li>{t(`Everyone starts a month with ${f.points(rules.start)} points; the month is counted by Moscow time.`, `Каждый месяц все начинают с ${f.points(rules.start)} баллов; месяц считается по московскому времени.`)}</li>
                      <li>{t(`The first visit of a day gives ${rules.daily} points, every ${rules.streak_days}th day in a row ${rules.streak_bonus} more.`, `Первый заход за день даёт ${rules.daily} баллов, каждый ${rules.streak_days}-й день подряд ещё ${rules.streak_bonus}.`)}</li>
                      <li>{t(`A bet is ${rules.min_bet} to ${rules.max_per_match} points per match, on one player, until the match starts. It can't be taken back.`, `Ставка от ${rules.min_bet} до ${rules.max_per_match} баллов на матч, на одного игрока, до начала матча. Отменить её нельзя.`)}</li>
                      <li>{t("The odds start from the players' Elo and move with the bets. Your bet keeps the odds it was made at.", "Коэффициент стартует от Elo игроков и меняется от ставок. Ваша ставка сохраняет коэффициент, по которому сделана.")}</li>
                      <li>{t("A match nobody settled by the end of the month returns its bets.", "Матч, не рассчитанный до конца месяца, возвращает ставки.")}</li>
                      <li>{t(`The month's table is by points. Its top three start the next month with +${rules.handicap.join(" / +")}.`, `Таблица месяца — по баллам. Первая тройка начинает следующий месяц с +${rules.handicap.join(" / +")}.`)}</li>
                    </ul>
                  </details>
                </section>
                <section className="player-box">
                  <h2 className="player-box-title match-game-title"><span>{t("This month's matches", "Матчи этого месяца")}</span><span className="match-game-meta">{active.length}</span></h2>
                  {active.length === 0 ? <p className="match-empty">{t("No announced matches to bet on.", "Нет анонсированных матчей, на которые можно поставить.")}</p>
                    : active.map((m) => <MarketCard key={m.id} market={m} wallet={wallet} onChange={changed} />)}
                </section>
                <section className="player-box">
                  <h2 className="player-box-title">{t("Table of the month", "Таблица месяца")}</h2>
                  {table.map((row) => (
                    <div className={`bets-table-row${row.me ? " is-me" : ""}`} key={row.nickname}>
                      <span className={`bets-place bets-place--${row.place}`}>{row.place}</span>
                      <span className="player-ellipsis">{row.nickname}</span>
                      <b>{f.points(row.balance)}</b>
                    </div>
                  ))}
                </section>
                {done.length > 0 && (
                  <section className="player-box">
                    <h2 className="player-box-title match-game-title"><span>{t("Finished", "Завершённые")}</span><span className="match-game-meta">{done.length}</span></h2>
                    {done.map((m) => <MarketCard key={m.id} market={m} wallet={wallet} onChange={changed} />)}
                  </section>
                )}
                <History rows={history} />
              </>}
          </div>
        </div>
      </div>
    </main>
  );
}
