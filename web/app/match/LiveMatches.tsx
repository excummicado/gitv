// Unfinished matches of running tournaments (GET /api/v1/matches/live-matches, kept by the API's live poll):
// each game links to its draft on the tournament site, so people can watch it there.
import { Fragment, useState } from "react";
import { Link } from "react-router";
import { useLang } from "../i18n";
import { resolveLiveMatch, unresolveLiveMatch, type LiveGame, type LiveMatch } from "./api";
import { liveRoomPath } from "../schedule/api";
import "./live-matches.css";
import { Nick } from "../components/PlayerNick";

function gameState(g: LiveGame) {
  return g.status === "FINISHED" ? "done" : g.status === "NOT_STARTED" ? "waiting" : "live";
}

// room: the whole row opens the match's room (players, rosters, statistics), like the matches of the day; the players'
// and the games' own links stay clickable above it. Only the main page asks for it.
// showTournament: the tournament's name under the match, bottom left, where rows of several tournaments are listed.
// discord: the tournament's server, where games off stream can often be watched in its open voice channels.
// editor: an admin or the tournament's organizer, who can resolve a match that won't be played there by hand.
export function LiveMatchRow({ match, onlyLive = false, showTournament = false, discord = null, room = false, editor = false }: { match: LiveMatch; onlyLive?: boolean; showTournament?: boolean; discord?: string | null; room?: boolean; editor?: boolean }) {
  const { t } = useLang();
  const titles = { done: t("Finished: open the draft", "Завершена: открыть драфт"), waiting: t("Not started yet: open the draft", "Ещё не началась: открыть драфт"), live: t("Being played now: watch the draft", "Идёт сейчас: смотреть драфт") };
  const games = onlyLive ? match.games.filter((g) => gameState(g) === "live") : match.games;
  return (
    <div className={`live-match${match.started ? " is-started" : ""}`}>
      {room && <Link className="live-match-room" to={liveRoomPath(match.id)} aria-label={t(`Open the match ${match.players.map((p) => p.name).join(" vs ")}`, `Открыть матч ${match.players.map((p) => p.name).join(" vs ")}`)} />}
      <span className="live-match-players">
        {match.players.map((p, i) => (
          <Fragment key={i}>
            {i > 0 && <span className="live-match-vs">vs</span>}
            {p.id ? <Link className="player-match-link" to={`/player/${p.id}`}><Nick id={p.id} name={p.name} /></Link> : <span>{p.name}</span>}
          </Fragment>
        ))}
      </span>
      <span className="live-match-games">
        {games.map((g) => {
          const state = gameState(g);
          const label = <>{state === "live" && <i className="live-dot" />}{t("Game", "Игра")} {g.game_no}</>;
          return g.url
            ? <a key={g.game_no} className={`live-game is-${state}`} href={g.url} target="_blank" rel="noopener noreferrer" title={titles[state]}>{label} ↗</a>
            : <span key={g.game_no} className={`live-game is-${state}`}>{label}</span>;
        })}
        {discord && (
          <a className="live-game is-discord" href={discord} target="_blank" rel="noopener noreferrer"
            title={t("The tournament's Discord server: games are often played in its open voice channels", "Discord-сервер турнира: игры часто идут в его открытых голосовых каналах")}>
            {t("Watch in Discord", "Смотреть в Discord")} ↗
          </a>
        )}
      </span>
      {showTournament && <small className="live-match-tournament">{match.tournament}</small>}
      {editor && <ResolveByHand match={match} />}
    </div>
  );
}

// Resolve by hand, for a match the tournament site paired that won't be played there: a technical win for one of
// them, or "won't be played". Once saved the match leaves the list with the next refresh; until then it can be undone.
function ResolveByHand({ match }: { match: LiveMatch }) {
  const { t } = useLang();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState("");
  const run = (request: Promise<unknown>, then: () => void) => {
    setSaving(true);
    setError("");
    request.then(then)
      .catch((err) => setError(err instanceof Error ? err.message : t("Couldn't save.", "Не удалось сохранить.")))
      .finally(() => setSaving(false));
  };
  const resolve = (side: number | null) => {
    const label = side === null ? t("won't be played", "не будет сыгран") : t(`${match.players[side].name} wins technically`, `техническая победа ${match.players[side].name}`);
    run(resolveLiveMatch(match.id, side), () => { setDone(label); setOpen(false); });
  };
  return (
    <div className="live-match-resolve">
      {done ? (
        <>
          <span className="player-note">{t("Resolved by hand:", "Решён вручную:")} {done}</span>
          <button type="button" className="match-input" disabled={saving} onClick={() => run(unresolveLiveMatch(match.id), () => setDone(null))}>{t("Undo", "Отменить")}</button>
        </>
      ) : !open ? (
        <button type="button" className="match-input" onClick={() => setOpen(true)}
          title={t("For a match that won't be played on the tournament site", "Для матча, который не будет сыгран на турнирном сайте")}>{t("Resolve by hand", "Решить вручную")}</button>
      ) : (
        <>
          <span className="player-label">{t("Winner:", "Победитель:")}</span>
          {match.players.map((p, i) => (
            <button type="button" key={i} className="match-input" disabled={saving || !p.id} onClick={() => resolve(i)}
              title={p.id ? t("A technical win: counts in the statistics", "Техническая победа: идёт в статистику") : t("No page on the site yet: can't be the winner", "Ещё нет страницы на сайте: не может быть победителем")}>{p.name}</button>
          ))}
          <button type="button" className="match-input" disabled={saving} onClick={() => resolve(null)}>{t("Won't be played", "Не будет сыгран")}</button>
          <button type="button" className="match-input" disabled={saving} onClick={() => setOpen(false)}>{t("Cancel", "Отмена")}</button>
        </>
      )}
      {error && <span className="match-result-error" role="alert">{error}</span>}
    </div>
  );
}
