import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { isPlayerEditor } from "../auth/client";
import { useAuth } from "../auth/useCurrentUser";
import { useLang } from "../i18n";
import { fetchUnresolved, type UnresolvedMatch, type UnresolvedReason } from "./api";
import "./unresolved.css";

const REASONS: Record<UnresolvedReason, [string, string]> = {
  bracket: ["Waiting for the Challonge bracket", "Ждёт сетку Challonge"],
  tournament_end: ["Technical defeat held until the tournament ends", "Тех. поражение ждёт конца турнира"],
  both_technical: ["Both players took a technical defeat", "Тех. поражение у обоих"],
  no_time: ["A time wasn't entered", "Не внесено время"],
  unclear: ["Technical defeat, loser unclear", "Тех. поражение, проигравший неясен"],
};

// Matches of the organizer's tournaments (all of them for event organizers and admins) that have no result: the
// ones only a winner set by hand settles first, then those still waiting for their bracket or the tournament's end.
export function UnresolvedPage() {
  const { user, ready } = useAuth();
  const editor = isPlayerEditor(user);
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
