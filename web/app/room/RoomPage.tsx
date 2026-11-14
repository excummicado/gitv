import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { EloBadge } from "../components/EloBadge";
import { Nick } from "../components/PlayerNick";
import { mayBet } from "../auth/client";
import { useAuth } from "../auth/useCurrentUser";
import { useLang } from "../i18n";
import { fetchMarket, visit, type Market, type Wallet } from "../bets/api";
import { MarketCard, STATES, useBetText } from "../bets/BetsPage";
import { fetchComparison, type Comparison } from "../player/api";
import { ComparisonBody } from "../player/ComparePage";
import { RosterPanel } from "../player/TournamentsTab";
import { fetchRoom, stageLabel, type Room, type RoomPlayer } from "../schedule/api";
import "../profile/profile.css";
import "../bets/bets.css";
import "../player/compare.css";
import "../player/player-page.css";
import "./room.css";

function PlayerHead({ player, won, align }: { player: RoomPlayer; won: boolean; align: "left" | "right" }) {
  return (
    <div className={`cmp-head ${align}`}>
      <div className="cmp-head-text">
        {player.id ? <Link className={`player-match-link cmp-name${won ? " room-winner" : ""}`} to={`/player/${player.id}`}><Nick id={player.id} name={player.name} /></Link>
          : <span className={`cmp-name${won ? " room-winner" : ""}`}>{player.name}</span>}
        <span className="room-head-sub">
          {player.elo != null && <EloBadge rating={player.elo} rank={player.elo_rank} tier={player.elo_tier} active={player.elo_active} />}
          {player.members?.map((m, i) => (
            <span key={i}>{i > 0 && "& "}{m.id ? <Link className="player-match-link" to={`/player/${m.id}`}><Nick id={m.id} name={m.name} /></Link> : m.name}</span>
          ))}
        </span>
      </div>
    </div>
  );
}

// The odds everyone sees, and the way to a bet: bet testers get the form (their points, their bets on the match),
// everyone else is told bets are being tested.
function Bets({ room, onBet }: { room: Room; onBet: () => void }) {
  const { user, ready } = useAuth();
  const allowed = mayBet(user);
  const f = useBetText();
  const { t } = f;
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [market, setMarket] = useState<Market | null>(null);
  const [asked, setAsked] = useState(false);

  useEffect(() => {
    if (!allowed) return;
    let stale = false;
    // The visit first: it starts the month's points, which a bet needs
    visit().then((w) => { if (!stale) setWallet(w); return fetchMarket(room.id); }).then((m) => { if (!stale) setMarket(m); }).catch(() => {});
    return () => { stale = true; };
    // Asked again when the room's own reading shows the bets have moved
  }, [allowed, room.id, room.bets, room.players[0].stake, room.players[1].stake]);

  function changed(next: Market) {
    setMarket(next);
    visit(true).then(setWallet).catch(() => {});
    onBet();
  }

  return (
    <section className="player-box">
      <h2 className="player-box-title match-game-title">
        <span>{t("Bets", "Ставки")}</span>
        <span className={`bets-state bets-state--${room.bets}`}>{t(...STATES[room.bets])}</span>
      </h2>
      {allowed && wallet && market ? <MarketCard market={market} wallet={wallet} onChange={changed} room />
        : (
          <div className="bets-match">
            <div className="bets-sides">
              {room.players.map((player, i) => (
                <div key={i} className={`bets-side${room.winner === i ? " is-winner" : ""}`}>
                  <span className="bets-side-top">
                    <span className="bets-side-name">{player.name}</span>
                    {player.odds != null && <span className="bets-side-odds">{f.odds(player.odds)}</span>}
                  </span>
                  <span className="bets-side-sub">
                    {player.elo != null ? `Elo ${player.elo}` : t("no Elo", "нет Elo")}
                    {player.stake > 0 && <> · {t(`${f.points(player.stake)} bet`, `поставлено ${f.points(player.stake)}`)}</>}
                    {room.winner === i && <> · {t("winner", "победитель")}</>}
                  </span>
                </div>
              ))}
            </div>
            {room.bets === "open" && ready && !allowed && (
              <div className="bets-form">
                <button type="button" className="profile-action" onClick={() => setAsked(true)}>{t("Bet", "Ставить")}</button>
                {asked && (
                  <span className="bets-form-win" role="status">
                    {t("Bets are being tested: for now only members with the bet tester role can make them.", "Ставки тестируются: пока их могут делать только участники с ролью тестера ставок.")}
                  </span>
                )}
              </div>
            )}
          </div>
        )}
      <p className="room-note">{t("Bets are for points, not money. The odds start from the players' Elo and move with the bets.", "Ставки на баллы, не на деньги. Коэффициент стартует от Elo игроков и меняется от ставок.")}</p>
    </section>
  );
}

function Rosters({ room }: { room: Room }) {
  const { t } = useLang();
  return (
    <section className="player-box">
      <h2 className="player-box-title">{t("Rosters", "Ростеры")}</h2>
      <div className="room-rosters">
        {room.players.map((player, i) => (
          <div key={i} className="room-roster">
            <div className="room-roster-head">
              <b>{player.name}</b>
              {player.id && player.roster && (
                <span className="player-label">
                  {player.roster.id === room.tournament_id ? t("in this tournament", "на этом турнире") : <>{t("latest known, from", "последний известный, с турнира")}{" "}
                    <Link className="player-match-link" to={`/tournament/${player.roster.id}`}>{player.roster.title || player.roster.id}</Link></>}
                </span>
              )}
            </div>
            {player.id && player.roster ? <RosterPanel playerId={player.id} tournamentId={player.roster.id} />
              : <p className="player-message">{player.members?.length ? t("A team: open its players for their rosters.", "Команда: ростеры смотрите у её игроков.") : t("No roster known.", "Ростер неизвестен.")}</p>}
          </div>
        ))}
      </div>
    </section>
  );
}

function Stats({ room }: { room: Room }) {
  const { t } = useLang();
  const [a, b] = [room.players[0].id, room.players[1].id];
  const [data, setData] = useState<Comparison | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!a || !b) return;
    const controller = new AbortController();
    setData(null);
    setError("");
    fetchComparison(a, b, "all", controller.signal).then(setData)
      .catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t("Couldn't load the statistics.", "Не удалось загрузить статистику.")); });
    return () => controller.abort();
  }, [a, b]);

  if (!a || !b) return <p className="player-box player-message">{t("Statistics are shown when both players are known to the site.", "Статистика показывается, когда оба игрока известны сайту.")}</p>;
  if (error) return <p className="player-box player-message">{error}</p>;
  if (!data) return <p className="player-box player-message">{t("Loading statistics…", "Загрузка статистики…")}</p>;
  return (
    <>
      <ComparisonBody data={data} a={a} b={b} names={[room.players[0].name, room.players[1].name]} />
      <p className="room-more"><Link className="player-match-link" to={`/player/${a}/compare/${b}`}>{t("Open the full comparison", "Открыть полное сравнение")} →</Link></p>
    </>
  );
}

// A match of the day's room: who plays and when, the odds of the bets on it (and the bet itself, for bet testers),
// the players' rosters and their statistics against each other. Read again every minute, like the matches of the day.
export function RoomPage({ roomId }: { roomId: string }) {
  const l = useLang();
  const { t, locale } = l;
  const [room, setRoom] = useState<Room | null>(null);
  const [error, setError] = useState("");

  const load = useCallback((signal?: AbortSignal) => {
    fetchRoom(roomId, signal).then((r) => { setRoom(r); setError(""); })
      .catch((err) => { if (!signal?.aborted) setError(err instanceof Error ? err.message : t("Couldn't load the match.", "Не удалось загрузить матч.")); });
  }, [roomId]);

  useEffect(() => {
    const controller = new AbortController();
    setRoom(null);
    load(controller.signal);
    const timer = window.setInterval(() => load(controller.signal), 60 * 1000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [load]);

  const moment = room ? room.starts_at ?? room.live_at ?? room.announced_at : null;
  const when = moment && new Date(moment);
  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="player-content match-content">
            {!room ? <p className="player-box player-message">{error || t("Loading the match…", "Загрузка матча…")}</p> : (
              <>
                <section className="player-box">
                  <div className="cmp-top">
                    <PlayerHead player={room.players[0]} won={room.winner === 0} align="left" />
                    <div className="cmp-vs room-when">
                      {room.live ? <b className="room-live">{t("On air", "Идёт")}</b>
                        : room.finished_at || room.winner != null ? <span>{t("Finished", "Сыгран")}</span>
                        : <span>VS</span>}
                      {when && <b className="room-time">{when.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" })}</b>}
                      {when && <small>{when.toLocaleDateString(locale, { weekday: "short", day: "2-digit", month: "2-digit" })}</small>}
                    </div>
                    <PlayerHead player={room.players[1]} won={room.winner === 1} align="right" />
                  </div>
                  <p className="room-meta">
                    {room.tournament_id ? <Link className="player-match-link" to={`/tournament/${room.tournament_id}`}>{room.tournament_title}</Link> : <span>{room.tournament_title}</span>}
                    {room.stage && <span>{stageLabel(room.stage, t)}</span>}
                    {room.kind === "stream" && !room.starts_at && !room.live_at && <span>{t("on stream, the time is the day's announcement", "на стриме, время — анонса дня")}</span>}
                    {room.casters && <span>{t("casters", "ведут")} {room.casters}</span>}
                    {room.stream_url && <a className="player-match-link" href={room.stream_url} target="_blank" rel="noreferrer">{room.stream_name ?? "Twitch"} · Twitch ↗</a>}
                    {room.post_url && <a className="player-match-link" href={room.post_url} target="_blank" rel="noreferrer">{t("Announcement", "Анонс")} ↗</a>}
                  </p>
                </section>
                <Bets room={room} onBet={() => load()} />
                <Rosters room={room} />
                <Stats room={room} />
              </>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
