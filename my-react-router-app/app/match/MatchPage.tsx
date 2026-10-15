import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { OrganizerName } from "./OrganizerName";
import { fetchMatch, type Character, type DraftMove, type Game, type GamePlayer, type MatchDetail, type Result } from "./api";
import "../player/player-page.css";
import "../home/gitv-preview.css";
import "./match-page.css";
import { useLang } from "../i18n";

const MOVE_LABELS: Record<string, [string, string]> = {
  IMMUNE_BAN: ["Immune ban", "Иммунный бан"], IMMUNE_PICK: ["Immune pick", "Иммунный пик"], IMMUNE: ["Immune", "Иммунитет"],
  PREBAN: ["Preban", "Пребан"], BAN: ["Ban", "Бан"], PICK: ["Pick", "Пик"], MIRROR: ["Mirror", "Зеркало"],
};

function moveKind(type: string) {
  if (type.includes("BAN")) return "ban";
  if (type.startsWith("IMMUNE")) return "immune";
  return "pick";
}

function durationMinutes(from: string | null, to: string | null) {
  if (!from || !to) return null;
  const minutes = Math.round((new Date(to).getTime() - new Date(from).getTime()) / 60000);
  return minutes > 0 ? minutes : null;
}

function ResultChip({ result }: { result: Result }) {
  const { t } = useLang();
  const kind = result === "W" ? "win" : result === "L" ? "loss" : "none";
  const letter = result === "W" ? t("W", "В") : result === "L" ? t("L", "П") : result === "D" ? t("D", "Н") : "–";
  return <span className={`player-game match-result ${kind}`}>{letter}</span>;
}

function Portrait({ character, size = 44 }: { character: Character; size?: number }) {
  return character.icon
    ? <img className={`match-portrait rarity-${character.rarity ?? 4}`} src={character.icon} alt="" width={size} height={size} loading="lazy" />
    : <span className="match-portrait match-portrait-empty" style={{ width: size, height: size }} />;
}

function PlayerPanel({ player, game }: { player: GamePlayer; game: Game }) {
  const penalty = player.adjusted_time - player.clear_time;
  const { t, name } = useLang();
  const s = t("s", "с");
  return (
    <div className={`match-side${player.result === "W" ? " is-winner" : ""}`}>
      <div className="match-side-head">
        <div className="match-side-name">
          {player.user_id ? <Link className="match-player-link" to={`/player/${player.user_id}`}>{player.name}</Link> : player.name}
          {game.first_pick_slot === player.slot && <span className="match-tag">{t("First pick", "Первый пик")}</span>}
        </div>
        <ResultChip result={player.result} />
      </div>

      <div className="match-figures">
        <div><span className="player-label">{t("Time", "Время")}</span><strong>{player.clear_time ? `${player.clear_time}${s}` : "—"}</strong></div>
        <div><span className="player-label">{t("With penalty", "Со штрафом")}</span><strong>{player.clear_time ? `${player.adjusted_time}${s}` : "—"}{penalty > 0 && <em> +{penalty}</em>}</strong></div>
        <div><span className="player-label">{t("Restarts", "Рестарты")}</span><strong>{player.restarts}</strong></div>
      </div>

      {player.rooms && (
        <div className="match-rooms">
          {player.rooms.map((time, index) => (
            <div className={`match-room${time > 0 ? "" : " is-missing"}`} key={index}>
              <span className="player-label">{t("Room", "Комната")} {index + 1}</span>
              <strong>{time > 0 ? `${time}${s}` : "—"}</strong>
            </div>
          ))}
        </div>
      )}

      <div className="match-team">
        {player.team.map((member, index) => (
          <div className="match-member" key={index} title={`${name(member.character)} C${member.constellation}${member.weapon ? ` · ${name(member.weapon)} R${member.refinement ?? "?"}` : ""}`}>
            <div className="match-member-art">
              <Portrait character={member.character} />
              <span className="match-badge">C{member.constellation}</span>
              {member.weapon?.icon && <img className="match-weapon" src={member.weapon.icon} alt="" width={22} height={22} loading="lazy" />}
            </div>
            <span className="match-member-name">{name(member.character)}</span>
            {member.weapon && <span className="match-member-weapon">{name(member.weapon)} · R{member.refinement ?? "?"}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

function DraftMoves({ game }: { game: Game }) {
  const { t, name } = useLang();
  const names = Object.fromEntries(game.players.map((p) => [p.slot, p.name]));
  let previous = game.started_at;
  const rows = game.moves.map((move: DraftMove) => {
    const took = previous && move.at ? Math.max(0, Math.round((new Date(move.at).getTime() - new Date(previous).getTime()) / 1000)) : null;
    previous = move.at ?? previous;
    return { move, took };
  });
  if (!rows.length) return <p className="match-empty">{t("No draft moves recorded for this game.", "Для этой игры ходы драфта не записаны.")}</p>;
  return (
    <div className="match-moves" role="table" aria-label={t(`Draft of game ${game.game_no}`, `Драфт игры ${game.game_no}`)}>
      <div className="match-move match-move-head" role="row"><span>#</span><span>{t("Player", "Игрок")}</span><span>{t("Action", "Ход")}</span><span>{t("Character", "Персонаж")}</span><span>{t("Took", "Время")}</span></div>
      {rows.map(({ move, took }) => (
        <div className={`match-move side-${move.slot ?? "x"}`} role="row" key={move.seq}>
          <span className="player-label">{move.seq}</span>
          <span className="match-move-player">{move.slot != null ? names[move.slot] : "—"}</span>
          <span className={`match-move-type ${moveKind(move.type)}`}>{MOVE_LABELS[move.type] ? t(...MOVE_LABELS[move.type]) : move.type}</span>
          <span className="match-move-character">
            {move.character ? <><Portrait character={move.character} size={26} />{name(move.character)}</> : <span className="player-label">{t("Skipped", "Пропущено")}</span>}
          </span>
          <span className="player-label">{took != null ? `${took}${t("s", "с")}` : "—"}</span>
        </div>
      ))}
    </div>
  );
}

function GameSection({ game }: { game: Game }) {
  const { t } = useLang();
  const duration = durationMinutes(game.started_at, game.finished_at);
  return (
    <section className="player-box match-game">
      <h2 className="player-box-title match-game-title">
        <span>{t("Game", "Игра")} {game.game_no}</span>
        {game.technical && <span className="match-tag warn">{t("Technical", "Тех. поражение")}</span>}
        {duration && <span className="match-game-meta">{duration} {t("min", "мин")}</span>}
        {game.url && <a className="match-link" href={game.url} target="_blank" rel="noreferrer">{t("Open draft ↗", "Открыть драфт ↗")}</a>}
      </h2>
      {game.technical && (
        <p className="match-notice">
          {game.winner_slot != null
            ? t("Unfinished after a technical defeat: the winner below comes from the technical-defeat rule, and the times aren't counted in player stats.",
                "Игра не доиграна после технического поражения: победитель ниже определён по правилу тех. поражения, а время не учитывается в статистике игроков.")
            : t("Unfinished, and neither player's defeat can be told: no result, and the times aren't counted in player stats.",
                "Игра не доиграна, и проигравшего определить нельзя: результата нет, а время не учитывается в статистике игроков.")}
        </p>
      )}
      <div className="match-sides">
        {game.players.map((player) => <PlayerPanel player={player} game={game} key={player.slot} />)}
      </div>
      <h3 className="match-subtitle">{t("Draft", "Драфт")}</h3>
      <DraftMoves game={game} />
    </section>
  );
}

function MatchHeader({ match }: { match: MatchDetail }) {
  const [a, b] = match.sides;
  const { t, date, count } = useLang();
  const s = t("s", "с");
  const penalty = match.paid_restarts.length
    ? t(`then +${match.paid_restarts.join("s, +")}s per restart`, `далее +${match.paid_restarts.join(" с, +")} с за рестарт`)
    : t("no penalty", "без штрафа");
  return (
    <header className="player-box match-header">
      <div className="match-kicker">
        <span>{match.tournament}{match.organizer && <> · {t("by", "орг.")} <OrganizerName organizer={match.organizer} /></>}</span>
        <span className="gitv-date">{date(match.created_at)}</span>
        {match.system && <span>{match.system}{match.mode ? ` · ${match.mode === "Abyss" ? t("Abyss", "Бездна") : match.mode}` : ""}</span>}
        {match.is_official && <span className="match-tag">{t("Official", "Официальный")}</span>}
      </div>
      {a && b && (
        <div className="match-score">
          <span className={`match-score-name${match.winner === 0 ? " is-winner" : ""}`}>{a.user_id ? <Link className="match-player-link" to={`/player/${a.user_id}`}>{a.name}</Link> : a.name}</span>
          <span className="match-score-value">{a.games_won} – {b.games_won}</span>
          <span className={`match-score-name right${match.winner === 1 ? " is-winner" : ""}`}>{b.user_id ? <Link className="match-player-link" to={`/player/${b.user_id}`}>{b.name}</Link> : b.name}</span>
        </div>
      )}
      <div className="match-summary">
        {match.winner != null && a && b
          ? <>{t("Winner", "Победитель")}: <strong>{match.sides[match.winner].name}</strong>{match.technical && t(" by technical defeat", " по тех. поражению")}</>
          : t("No result", "Нет результата")}
        {a?.total_time != null && b?.total_time != null && <> · {t("Total time", "Общее время")} {a.total_time}{s} – {b.total_time}{s}</>}
        <> · {count(match.free_restarts ?? 0, ["free restart", "free restarts"], ["бесплатный рестарт", "бесплатных рестарта", "бесплатных рестартов"])}, {penalty}</>
      </div>
    </header>
  );
}

export function MatchPage({ matchId }: { matchId: string }) {
  const [match, setMatch] = useState<MatchDetail | null>(null);
  const [error, setError] = useState("");
  const { t } = useLang();

  useEffect(() => {
    const controller = new AbortController();
    setMatch(null);
    setError("");
    fetchMatch(matchId, controller.signal)
      .then(setMatch)
      .catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t("Couldn't load the match.", "Не удалось загрузить матч.")); });
    return () => controller.abort();
  }, [matchId]);

  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="player-content match-content">
            {error ? <p className="player-box match-empty">{error}</p>
              : !match ? <p className="player-box match-empty">{t("Loading match…", "Загрузка матча…")}</p>
              : <>
                  <MatchHeader match={match} />
                  {match.games.map((game) => <GameSection game={game} key={game.id} />)}
                </>}
          </div>
        </div>
      </div>
    </main>
  );
}
