import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { isPlayerEditor, STAFF_ROLES } from "../auth/client";
import { useAuth } from "../auth/useCurrentUser";
import { useLang } from "../i18n";
import { fetchStreamNames, fetchUnresolved, rejectStreamName, tieStreamName, type StreamName, type UnresolvedMatch, type UnresolvedReason } from "./api";
import "./unresolved.css";

const REASONS: Record<UnresolvedReason, [string, string]> = {
  bracket: ["Waiting for the Challonge bracket", "Ждёт сетку Challonge"],
  tournament_end: ["Technical defeat held until the tournament ends", "Тех. поражение ждёт конца турнира"],
  both_technical: ["Both players took a technical defeat", "Тех. поражение у обоих"],
  no_time: ["A time wasn't entered", "Не внесено время"],
  unclear: ["Technical defeat, loser unclear", "Тех. поражение, проигравший неясен"],
};

// One nickname from the streams' posts no player was found for: tie it to a suggested player (or any other, by
// nickname or id), say a suggestion isn't them, or hide it when it isn't a player at all (a team).
function StreamNameRow({ row, onDone }: { row: StreamName; onDone: () => void }) {
  const { t, date } = useLang();
  const [other, setOther] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function act(request: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await request();
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Couldn't save the change. Try again.", "Не удалось сохранить изменение. Попробуйте ещё раз."));
      setBusy(false);
    }
  }

  const tieOther = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (other.trim()) act(() => tieStreamName(row.name, other.trim()));
  };

  return (
    <div className="names-row">
      <div className="names-head">
        <strong className="names-name">{row.name}</strong>
        <span className="names-meta">
          {t(`${row.matches} on stream`, `матчей на стриме: ${row.matches}`)} · {row.appearances.map((a) => `${t("vs", "против")} ${a.opponent}, ${a.tournament}, ${date(a.date)}`).join("; ")}
        </span>
      </div>
      <div className="names-candidates">
        {row.candidates.length === 0 && <span className="names-meta">{t("Nobody's name looks like it.", "Похожих ников нет.")}</span>}
        {row.candidates.map((c) => (
          <div className="names-candidate" key={c.id}>
            <Link to={`/player/${c.id}`} className="names-player" target="_blank" rel="noopener">{c.name}</Link>
            <span className="names-meta">
              {c.likeness}% · {t(`${c.matches} matches`, `матчей: ${c.matches}`)}{c.rating ? ` · Elo ${c.rating}` : ""}{c.last_played ? ` · ${date(c.last_played)}` : ""}
            </span>
            <button type="button" className="names-btn names-btn--yes" disabled={busy} onClick={() => act(() => tieStreamName(row.name, c.id))}>{t("That's them", "Это он")}</button>
            <button type="button" className="names-btn" disabled={busy} title={t("Not this player: don't suggest again", "Не он: больше не предлагать")}
              onClick={() => act(() => rejectStreamName(row.name, c.id))}>{t("Not them", "Не он")}</button>
          </div>
        ))}
      </div>
      <form className="names-other" onSubmit={tieOther}>
        <input className="names-input" value={other} onChange={(event) => setOther(event.target.value)} maxLength={64}
          placeholder={t("Another player: nickname or id", "Другой игрок: ник или id")} aria-label={t("Another player", "Другой игрок")} />
        <button type="submit" className="names-btn" disabled={busy || !other.trim()}>{t("Tie", "Привязать")}</button>
        <button type="button" className="names-btn names-btn--quiet" disabled={busy} title={t("A team or nobody on the site: hide it", "Команда или игрока нет на сайте: скрыть")}
          onClick={() => act(() => rejectStreamName(row.name))}>{t("Not a player — hide", "Не игрок — скрыть")}</button>
      </form>
      {error && <div className="names-error" role="alert">{error}</div>}
    </div>
  );
}

function StreamNames() {
  const { t } = useLang();
  const [rows, setRows] = useState<StreamName[] | null>(null);
  const load = () => fetchStreamNames(true).then(setRows).catch(() => setRows([]));
  useEffect(() => { load(); }, []);
  if (rows === null) return null;
  return (
    <section className="player-box">
      <h2 className="player-box-title match-game-title"><span>{t("Stream nicknames without a player", "Ники со стримов без игрока")}</span><span className="match-game-meta">{rows.length}</span></h2>
      <p className="player-label unresolved-hint">
        {t("Matches of the day name these players in a way the site can't tie to anyone. A tie counts everywhere: matches of the day, brackets, statistics.",
          "Матчи дня называют этих игроков так, что сайт не может их ни к кому привязать. Привязка действует везде: матчи дня, сетки, статистика.")}
      </p>
      {rows.length === 0 ? <p className="match-empty">{t("Every nickname is tied.", "Все ники привязаны.")}</p> : rows.map((r) => <StreamNameRow key={r.name} row={r} onDone={load} />)}
    </section>
  );
}

// Matches of the organizer's tournaments (all of them for event organizers and admins) that have no result: the
// ones only a winner set by hand settles first, then those still waiting for their bracket or the tournament's end.
export function UnresolvedPage() {
  const { user, ready } = useAuth();
  const editor = isPlayerEditor(user);
  const staff = Boolean(user && STAFF_ROLES.includes(user.role));
  const { t, date } = useLang();
  const [rows, setRows] = useState<UnresolvedMatch[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!editor) return;
    fetchUnresolved(true).then(setRows).catch((err) => setError(err instanceof Error ? err.message : t("Couldn't load the matches.", "Не удалось загрузить матчи.")));
  }, [editor]);

  const section = (title: string, hint: string, list: UnresolvedMatch[]) => (
    <section className="player-box">
      <h2 className="player-box-title match-game-title"><span>{title}</span><span className="match-game-meta">{list.length}</span></h2>
      <p className="player-label unresolved-hint">{hint}</p>
      {list.length === 0 ? <p className="match-empty">{t("Nothing here.", "Пусто.")}</p> : list.map((m) => (
        <Link className="unresolved-row" to={`/match/${m.id}`} key={m.id}>
          <span className="gitv-date">{date(m.created_at)}</span>
          <span className="player-ellipsis">{m.tournament}</span>
          <span className="player-ellipsis">{m.sides.join(" vs ")}</span>
          <span className="unresolved-reason">{t(...REASONS[m.reason])}</span>
        </Link>
      ))}
    </section>
  );

  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="player-content match-content">
            {!ready ? null
              : !editor ? <p className="player-box player-message">{t("Only organizers and admins see this page.", "Эта страница только для организаторов и админов.")}</p>
              : error ? <p className="player-box player-message">{error}</p>
              : !rows ? <p className="player-box player-message">{t("Loading matches…", "Загрузка матчей…")}</p>
              : <>
                {staff && <StreamNames />}
                {section(t("Need a winner set by hand", "Нужно задать победителя вручную"),
                  t("Open the match and set its winner.", "Откройте матч и задайте победителя."), rows.filter((m) => !m.waiting))}
                {section(t("Still waiting", "Ещё ждут"),
                  t("These may get their result by themselves once the bracket is filled in or the tournament ends.",
                    "Эти могут разрешиться сами, когда заполнят сетку или турнир закончится."), rows.filter((m) => m.waiting))}
              </>}
          </div>
        </div>
      </div>
    </main>
  );
}
