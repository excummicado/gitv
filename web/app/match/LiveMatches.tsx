// Unfinished matches of running tournaments (GET /api/v1/matches/live-matches, kept by the API's live poll):
// each game links to its draft on the tournament site, so people can watch it there.
import { Fragment } from "react";
import { Link } from "react-router";
import { useLang } from "../i18n";
import type { LiveGame, LiveMatch } from "./api";
import "./live-matches.css";
import { Nick } from "../components/PlayerNick";

function gameState(g: LiveGame) {
  return g.status === "FINISHED" ? "done" : g.status === "NOT_STARTED" ? "waiting" : "live";
}

// showTournament: the tournament's name under the match, bottom left, where rows of several tournaments are listed.
// discord: the tournament's server, where games off stream can often be watched in its open voice channels.
export function LiveMatchRow({ match, onlyLive = false, showTournament = false, discord = null }: { match: LiveMatch; onlyLive?: boolean; showTournament?: boolean; discord?: string | null }) {
  const { t } = useLang();
  const titles = { done: t("Finished: open the draft", "Завершена: открыть драфт"), waiting: t("Not started yet: open the draft", "Ещё не началась: открыть драфт"), live: t("Being played now: watch the draft", "Идёт сейчас: смотреть драфт") };
  const games = onlyLive ? match.games.filter((g) => gameState(g) === "live") : match.games;
  return (
    <div className={`live-match${match.started ? " is-started" : ""}`}>
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
    </div>
  );
}
