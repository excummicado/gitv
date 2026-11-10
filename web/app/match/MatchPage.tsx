import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { OrganizerName } from "./OrganizerName";
import { PhaseBody, usePhase } from "../abyss/AbyssView";
import {
  clearGameResult, clearMatchWinner, fetchMatch, fillGameResult, setMatchWinner,
  type Character, type DraftMove, type Game, type GamePlayer, type MatchDetail, type Result,
} from "./api";
import { useAuth } from "../auth/useCurrentUser";
import { runsTournamentsOf } from "../auth/client";
import "./match-page.css";
import { useLang } from "../i18n";
import { Nick } from "../components/PlayerNick";

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

// A heading that opens and closes what's under it; the content is only made while open.
function Fold({ title, open: startOpen = false, className = "", children }: { title: React.ReactNode; open?: boolean; className?: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(startOpen);
  return (
    <>
      <button type="button" className={`match-fold ${className}`} aria-expanded={open} onClick={() => setOpen(!open)}>
        <span>{title}</span>
        <span className="match-fold-toggle" aria-hidden>{open ? "−" : "+"}</span>
      </button>
      {open && children}
    </>
  );
}

// How far apart two times are, with the arrow towards the faster side.
function Gap({ left, right }: { left: number; right: number }) {
  const { t } = useLang();
  const gap = Math.abs(left - right);
  return (
    <span className="match-gap-value">
      {left < right && <i className="match-gap-arrow" aria-hidden>◀</i>}
      {gap ? `${gap}${t("s", " с")}` : "="}
      {left > right && <i className="match-gap-arrow" aria-hidden>▶</i>}
    </span>
  );
}

// Between the two players: the game's time gap (with penalties, as it decides the game) and each room's.
function GameGap({ a, b }: { a: GamePlayer; b: GamePlayer }) {
  const { t } = useLang();
  const penalties = a.adjusted_time - a.clear_time !== b.adjusted_time - b.clear_time;
  const rooms = (a.rooms ?? []).map((time, i) => [time, b.rooms?.[i] ?? 0]);
  return (
    <div className="match-gap">
      <span className="player-label">{t("Time gap", "Разница")}</span>
      <strong><Gap left={a.adjusted_time} right={b.adjusted_time} /></strong>
      {penalties && <small className="player-label">{t("no penalty", "без штрафа")} <Gap left={a.clear_time} right={b.clear_time} /></small>}
      {rooms.some(([x, y]) => x > 0 && y > 0) && (
        <div className="match-gap-rooms">
          {rooms.map(([x, y], i) => x > 0 && y > 0 && (
            <span className="match-gap-room" key={i}>
              <span className="player-label">{t("Room", "Комн.")} {i + 1}</span>
              <Gap left={x} right={y} />
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function PlayerPanel({ player, game }: { player: GamePlayer; game: Game }) {
  const penalty = player.adjusted_time - player.clear_time;
  const { t, name } = useLang();
  const s = t("s", "с");
  return (
    <div className={`match-side${player.result === "W" ? " is-winner" : ""}`}>
      <div className="match-side-head">
        <div className="match-side-name">
          {player.user_id ? <Link className="match-player-link" to={`/player/${player.user_id}`}><Nick id={player.user_id} name={player.name} /></Link> : player.name}
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
          <div className="match-member" key={index} title={`${name(member.character)}${member.constellation == null ? "" : ` C${member.constellation}`}${member.weapon ? ` · ${name(member.weapon)} R${member.refinement ?? "?"}` : ""}`}>
            <div className="match-member-art">
              <Portrait character={member.character} size={88} />
              {member.constellation != null && <span className="match-badge">C{member.constellation}</span>}
              {member.weapon?.icon && <img className="match-weapon" src={member.weapon.icon} alt="" width={32} height={32} loading="lazy" />}
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

// Room times filled in by hand: each player's rooms (empty for one still unknown) and restarts. Event organizers and
// admins only, on a game with missing times or one filled in by hand before.
function ResultForm({ match, game, onSaved, onClose }: { match: MatchDetail; game: Game; onSaved: (m: MatchDetail) => void; onClose: () => void }) {
  const { t } = useLang();
  const count = Math.max(...game.players.map((p) => p.rooms?.length ?? 0), 0) || 3;
  const [values, setValues] = useState(() => game.players.map((p) => ({
    rooms: Array.from({ length: count }, (_, i) => (p.rooms?.[i] ? String(p.rooms[i]) : "")),
    restarts: String(p.restarts),
  })));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const run = (request: Promise<MatchDetail>) => {
    setSaving(true);
    setError("");
    request.then((m) => { onSaved(m); onClose(); })
      .catch((err) => setError(err instanceof Error ? err.message : t("Couldn't save.", "Не удалось сохранить.")))
      .finally(() => setSaving(false));
  };
  const save = (event: React.FormEvent) => {
    event.preventDefault();
    run(fillGameResult(match.id, game.id, game.players.map((p, i) => ({
      slot: p.slot,
      rooms: values[i].rooms.map((v) => Number(v) || 0),
      restarts: Number(values[i].restarts) || 0,
    }))));
  };
  const change = (i: number, update: (v: { rooms: string[]; restarts: string }) => { rooms: string[]; restarts: string }) =>
    setValues(values.map((v, k) => (k === i ? update(v) : v)));

  return (
    <form className="match-result-form" onSubmit={save}>
      <p className="player-note">{t(
        "Enter the missing times in seconds; leave a room empty if its time is still unknown. Times entered here win over the draft site's.",
        "Впишите недостающее время в секундах; комнату, время которой неизвестно, оставьте пустой. Время отсюда главнее времени с сайта драфтов.")}</p>
      {game.players.map((p, i) => (
        <div className="match-result-row" key={p.slot}>
          <span className="match-result-name">{p.name}</span>
          {values[i].rooms.map((v, r) => (
            <label key={r}>
              <span className="player-label">{t("Room", "Комн.")} {r + 1}</span>
              <input className="match-input" type="number" min={0} max={300} inputMode="numeric" value={v} placeholder="—"
                onChange={(e) => change(i, (x) => ({ ...x, rooms: x.rooms.map((y, k) => (k === r ? e.target.value : y)) }))} />
            </label>
          ))}
          <label>
            <span className="player-label">{t("Restarts", "Рестарты")}</span>
            <input className="match-input" type="number" min={0} max={99} inputMode="numeric" value={values[i].restarts}
              onChange={(e) => change(i, (x) => ({ ...x, restarts: e.target.value }))} />
          </label>
        </div>
      ))}
      {error && <p className="match-result-error" role="alert">{error}</p>}
      <div className="match-result-actions">
        <button type="submit" className="suggest-button" disabled={saving}>{saving ? t("Saving…", "Сохранение…") : t("Save", "Сохранить")}</button>
        <button type="button" className="match-input" disabled={saving} onClick={onClose}>{t("Cancel", "Отмена")}</button>
        {game.filled_by && (
          <button type="button" className="match-input" disabled={saving} onClick={() => run(clearGameResult(match.id, game.id))}>
            {t("Remove the times entered by hand", "Убрать время, внесённое вручную")}
          </button>
        )}
      </div>
    </form>
  );
}

function GameSection({ game, match, editor, onSaved }: { game: Game; match: MatchDetail; editor: boolean; onSaved: (m: MatchDetail) => void }) {
  const [editing, setEditing] = useState(false);
  const { t } = useLang();
  const duration = durationMinutes(game.started_at, game.finished_at);
  const [a, b] = game.players;
  // A technical game's times don't count, and a game without times has nothing to compare.
  const gap = a && b && game.players.length === 2 && a.clear_time > 0 && b.clear_time > 0 && !game.technical;
  return (
    <section className="player-box match-game">
      <h2 className="player-box-title match-game-title">
        <span>{t("Game", "Игра")} {game.game_no}</span>
        {game.technical && <span className="match-tag warn">{t("Technical", "Тех. поражение")}</span>}
        {duration && <span className="match-game-meta">{duration} {t("min", "мин")}</span>}
        {game.url && <a className="match-link" href={game.url} target="_blank" rel="noreferrer">{t("Open draft ↗", "Открыть драфт ↗")}</a>}
        {editor && game.editable && !editing && (
          <button type="button" className="match-input match-edit-button" onClick={() => setEditing(true)}>
            {game.filled_by ? t("Edit times", "Изменить время") : t("Fill in times", "Заполнить время")}
          </button>
        )}
      </h2>
      {game.filled_by && <p className="player-note match-filled">{t("Times filled in by hand by", "Время заполнено вручную:")} {game.filled_by}</p>}
      {editing && <ResultForm match={match} game={game} onSaved={onSaved} onClose={() => setEditing(false)} />}
      {game.technical && (
        <p className="match-notice">
          {game.winner_slot != null
            ? t("Unfinished after a technical defeat: the winner below comes from the technical-defeat rule, and the times aren't counted in player stats.",
                "Игра не доиграна после технического поражения: победитель ниже определён по правилу тех. поражения, а время не учитывается в статистике игроков.")
            : t("Unfinished, and neither player's defeat can be told: no result, and the times aren't counted in player stats.",
                "Игра не доиграна, и проигравшего определить нельзя: результата нет, а время не учитывается в статистике игроков.")}
        </p>
      )}
      <div className={`match-sides${gap ? " has-gap" : ""}`}>
        {gap
          ? <><PlayerPanel player={a} game={game} /><GameGap a={a} b={b} /><PlayerPanel player={b} game={game} /></>
          : game.players.map((player) => <PlayerPanel player={player} game={game} key={player.slot} />)}
      </div>
      <Fold title={t("Draft", "Драфт")} className="match-subtitle"><DraftMoves game={game} /></Fold>
    </section>
  );
}

function PhaseContent({ id }: { id: number }) {
  const { phase, error } = usePhase(String(id));
  const { t } = useLang();
  return (
    <div className="match-abyss-body">
      {error ? <p className="match-empty">{error}</p>
        : !phase ? <p className="match-empty">{t("Loading the Abyss…", "Загрузка Бездны…")}</p>
        : <>
            <Link className="player-match-link match-abyss-link" to={`/abyss/${phase.id}`}>{t("Version", "Версия")} {phase.version} ↗</Link>
            <PhaseBody phase={phase} />
          </>}
    </div>
  );
}

// The Abyss the match was played on, opened on request.
function MatchAbyss({ match }: { match: MatchDetail }) {
  const { t } = useLang();
  if (match.abyss_phase == null) return null;
  return (
    <section className="player-box match-abyss">
      <Fold title={<>{match.challonge_only ? "≈ " : ""}{t("Spiral Abyss of this match", "Бездна этого матча")}</>} className="player-box-title">
        <PhaseContent id={match.abyss_phase} />
      </Fold>
    </section>
  );
}

// The match's winner set by hand: only without a result from the bracket or the times (none, a technical defeat, or
// set by hand before).
function WinnerControl({ match, onSaved }: { match: MatchDetail; onSaved: (m: MatchDetail) => void }) {
  const { t } = useLang();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  if (match.challonge_only || match.sides.length !== 2) return null;
  if (match.winner != null && match.result_source !== "technical" && match.result_source !== "manual") return null;
  const run = (request: Promise<MatchDetail>) => {
    setSaving(true);
    setError("");
    request.then(onSaved)
      .catch((err) => setError(err instanceof Error ? err.message : t("Couldn't save.", "Не удалось сохранить.")))
      .finally(() => setSaving(false));
  };
  return (
    <div className="match-winner-control">
      <span className="player-label">{t("Set the winner by hand:", "Задать победителя вручную:")}</span>
      {match.sides.map((side, i) => (
        <button type="button" key={i} className={match.result_source === "manual" && match.winner === i ? "suggest-button" : "match-input"}
          disabled={saving} onClick={() => run(setMatchWinner(match.id, i))}>{side.name}</button>
      ))}
      {match.result_source === "manual" && (
        <button type="button" className="match-input" disabled={saving} onClick={() => run(clearMatchWinner(match.id))}>{t("Remove", "Убрать")}</button>
      )}
      {error && <span className="match-result-error" role="alert">{error}</span>}
    </div>
  );
}

function MatchHeader({ match, editor, onSaved }: { match: MatchDetail; editor: boolean; onSaved: (m: MatchDetail) => void }) {
  const [a, b] = match.sides;
  const { t, date, count } = useLang();
  const s = t("s", "с");
  const penalty = match.paid_restarts.length
    ? t(`then +${match.paid_restarts.join("s, +")}s per restart`, `далее +${match.paid_restarts.join(" с, +")} с за рестарт`)
    : t("no penalty", "без штрафа");
  return (
    <header className="player-box match-header">
      <div className="match-kicker">
        <span><Link className="match-player-link" to={`/tournament/${match.tournament_id}`}>{match.tournament}</Link>{match.organizer && <> · {t("by", "орг.")} <OrganizerName organizer={match.organizer} /></>}</span>
        <span className="gitv-date">{match.challonge_only ? "≈ " : ""}{date(match.created_at)}</span>
        {match.system && <span>{match.system}{match.mode ? ` · ${match.mode === "Abyss" ? t("Abyss", "Бездна") : match.mode}` : ""}</span>}
        {match.is_official && <span className="match-tag">{t("Official", "Официальный")}</span>}
      </div>
      {a && b && (
        <div className="match-score">
          <span className={`match-score-name${match.winner === 0 ? " is-winner" : ""}`}>{a.user_id ? <Link className="match-player-link" to={`/player/${a.user_id}`}><Nick id={a.user_id} name={a.name} /></Link> : a.name}</span>
          <span className="match-score-center">
            <span className="match-score-value">{a.games_won} – {b.games_won}</span>
            {a.total_time != null && b.total_time != null && <small className="player-label">{t("Time gap", "Разница")} <Gap left={a.total_time} right={b.total_time} /></small>}
          </span>
          <span className={`match-score-name right${match.winner === 1 ? " is-winner" : ""}`}>{b.user_id ? <Link className="match-player-link" to={`/player/${b.user_id}`}><Nick id={b.user_id} name={b.name} /></Link> : b.name}</span>
        </div>
      )}
      <div className="match-summary">
        {match.winner != null && a && b
          ? <>{t("Winner", "Победитель")}: <strong>{match.sides[match.winner].name}</strong>{match.result_source === "manual"
            ? <span title={t("The result was set by hand.", "Итог задан вручную.")}>{match.winner_set_by
              ? t(` (set by hand by ${match.winner_set_by})`, ` (задан вручную: ${match.winner_set_by})`)
              : t(" (set by hand)", " (задан вручную)")}</span>
            : match.result_source === "challonge"
            ? (match.challonge_only && !match.challonge_url
              ? <span>{t(" (tournament bracket)", " (по сетке турнира)")}</span>
              : <span title={t("The result as entered on the tournament's Challonge bracket.", "Результат из сетки турнира на Challonge.")}>{t(" (Challonge bracket)", " (по сетке Challonge)")}</span>)
            : match.technical && t(" by technical defeat", " по тех. поражению")}</>
          : t("No result", "Нет результата")}
        {a?.total_time != null && b?.total_time != null && <> · {t("Total time", "Общее время")} {a.total_time}{s} – {b.total_time}{s}</>}
        {!match.challonge_only && <> · {count(match.free_restarts ?? 0, ["free restart", "free restarts"], ["бесплатный рестарт", "бесплатных рестарта", "бесплатных рестартов"])}, {penalty}</>}
      </div>
      {editor && <WinnerControl match={match} onSaved={onSaved} />}
      {match.challonge_only && (
        <p className="player-note">{match.challonge_url
          ? t("This tournament was played only on Challonge: the result is from its bracket, there are no games, times or drafts.",
            "Этот турнир проходил только на Challonge: результат взят из сетки, игр, времени и драфтов нет.")
          : t("This tournament was played before the site: the result is from its published bracket, there are no games, times or drafts.",
            "Этот турнир проходил до сайта: результат взят из опубликованной сетки, игр, времени и драфтов нет.")}</p>
      )}
    </header>
  );
}

export function MatchPage({ matchId }: { matchId: string }) {
  const [match, setMatch] = useState<MatchDetail | null>(null);
  const [error, setError] = useState("");
  const { t } = useLang();
  const { user } = useAuth();
  // Event organizers and admins in every tournament; a member running some organizers' tournaments in theirs
  const editor = Boolean(match && runsTournamentsOf(user, match.organizer_id));

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
                  <MatchHeader match={match} editor={editor} onSaved={setMatch} />
                  <MatchAbyss match={match} />
                  {match.games.map((game) => <GameSection game={game} match={match} editor={editor} onSaved={setMatch} key={game.id} />)}
                </>}
          </div>
        </div>
      </div>
    </main>
  );
}
