import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { useAuth } from "../auth/useCurrentUser";
import { PLAYER_EDITOR_ROLES, STAFF_ROLES } from "../auth/client";
import { fetchPlayers, type PlayerSummary } from "../player/api";
import { useLang } from "../i18n";
import { addScheduled, deleteScheduled, listScheduled, localDay, scheduleTournaments, type ScheduledMatch } from "./api";
import "./schedule.css";

const DAYS_SHOWN = 31;
const OTHER = "__other__";

// The local time a datetime-local input means, as an ISO string with the offset (the API stores UTC).
function toIso(local: string) {
  return new Date(local).toISOString();
}

// Event organizers and admins announce matches: tournament, two players, start time, up to 60 days ahead.
export function SchedulePage() {
  const { user, ready } = useAuth();
  const l = useLang();
  const { t } = l;
  const editor = user ? PLAYER_EDITOR_ROLES.includes(user.role) : false;
  const staff = user ? STAFF_ROLES.includes(user.role) : false;

  const [tournaments, setTournaments] = useState<{ id: string; title: string }[]>([]);
  const [players, setPlayers] = useState<PlayerSummary[]>([]);
  const [tournament, setTournament] = useState(OTHER);
  const [tournamentTitle, setTournamentTitle] = useState("");
  const [player1, setPlayer1] = useState("");
  const [player2, setPlayer2] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const [saving, setSaving] = useState(false);
  const [upcoming, setUpcoming] = useState<ScheduledMatch[] | null>(null);

  const byName = useMemo(() => new Map(players.map((p) => [p.name.toLowerCase(), p])), [players]);

  function loadUpcoming() {
    const [today] = localDay();
    const end = new Date(today.getFullYear(), today.getMonth(), today.getDate() + DAYS_SHOWN);
    listScheduled(today, end).then(setUpcoming).catch(() => setUpcoming([]));
  }

  useEffect(() => {
    if (!editor) return;
    scheduleTournaments().then((list) => { setTournaments(list); if (list.length) setTournament(list[0].id); }).catch(() => {});
    fetchPlayers().then(setPlayers).catch(() => {});
    loadUpcoming();
  }, [editor]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const picked = tournaments.find((x) => x.id === tournament);
    const title = picked ? picked.title : tournamentTitle.trim();
    if (!title) return setMessage({ text: t("Pick or type the tournament.", "Выберите или впишите турнир."), ok: false });
    if (!player1.trim() || !player2.trim()) return setMessage({ text: t("Enter both players.", "Укажите обоих игроков."), ok: false });
    if (!startsAt) return setMessage({ text: t("Pick the date and time.", "Укажите дату и время."), ok: false });
    const p = (name: string) => ({ id: byName.get(name.trim().toLowerCase())?.id ?? null, name: name.trim() });
    setSaving(true);
    try {
      await addScheduled({ tournament_id: picked?.id ?? null, tournament_title: title, player1: p(player1), player2: p(player2), starts_at: toIso(startsAt) });
      setMessage({ text: t("Added.", "Добавлено."), ok: true });
      setPlayer1("");
      setPlayer2("");
      loadUpcoming();
    } catch (err) {
      setMessage({ text: err instanceof Error ? err.message : t("Couldn't add the match. Try again.", "Не удалось добавить матч. Попробуйте ещё раз."), ok: false });
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: number) {
    try {
      await deleteScheduled(id);
      setUpcoming((list) => list?.filter((m) => m.id !== id) ?? null);
    } catch (err) {
      setMessage({ text: err instanceof Error ? err.message : t("Couldn't remove it.", "Не удалось удалить."), ok: false });
    }
  }

  const time = (iso: string) => new Date(iso).toLocaleTimeString(l.locale, { hour: "2-digit", minute: "2-digit" });
  const day = (iso: string) => new Date(iso).toLocaleDateString(l.locale, { weekday: "short", day: "2-digit", month: "2-digit" });
  const groups = useMemo(() => {
    const out: [string, ScheduledMatch[]][] = [];
    for (const m of upcoming ?? []) {
      const key = day(m.starts_at);
      const last = out[out.length - 1];
      if (last && last[0] === key) last[1].push(m);
      else out.push([key, [m]]);
    }
    return out;
  }, [upcoming, l.locale]);

  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="player-content match-content">
            {!ready ? null : !editor ? (
              <p className="player-box match-empty">{t("Only event organizers and admins can schedule matches.", "Назначать матчи могут только организаторы и админы.")}</p>
            ) : (
              <>
                <section className="player-box">
                  <h2 className="player-box-title">{t("Schedule a match", "Назначить матч")}</h2>
                  <form className="schedule-form" onSubmit={submit} noValidate>
                    <label className="schedule-field schedule-field--wide">
                      <span className="player-label">{t("Tournament", "Турнир")}</span>
                      <span className="schedule-row">
                        <select className="match-input" value={tournament} onChange={(e) => { setTournament(e.target.value); setMessage(null); }}>
                          {tournaments.map((x) => <option value={x.id} key={x.id}>{x.title}</option>)}
                          <option value={OTHER}>{tournaments.length ? t("Other (type the name)", "Другой (впишите название)") : t("Type the name", "Впишите название")}</option>
                        </select>
                        {tournament === OTHER && (
                          <input className="match-input" value={tournamentTitle} maxLength={120} placeholder={t("Tournament name", "Название турнира")}
                            onChange={(e) => { setTournamentTitle(e.target.value); setMessage(null); }} />
                        )}
                      </span>
                      {!tournaments.length && <span className="schedule-hint">{t("No running or upcoming tournaments on the site right now (checked at most hourly).", "Сейчас на сайте нет идущих или предстоящих турниров (проверяется не чаще раза в час).")}</span>}
                    </label>
                    {[["1", player1, setPlayer1], ["2", player2, setPlayer2]].map(([n, value, set]) => (
                      <label className="schedule-field" key={n as string}>
                        <span className="player-label">{t(`Player ${n}`, `Игрок ${n}`)}</span>
                        <input className="match-input" list="schedule-players" value={value as string} maxLength={64} placeholder={t("Nickname", "Ник")}
                          onChange={(e) => { (set as (v: string) => void)(e.target.value); setMessage(null); }} />
                      </label>
                    ))}
                    <datalist id="schedule-players">{players.map((p) => <option value={p.name} key={p.id} />)}</datalist>
                    <label className="schedule-field">
                      <span className="player-label">{t("Starts at (your time)", "Начало (ваше время)")}</span>
                      <input className="match-input" type="datetime-local" value={startsAt} onChange={(e) => { setStartsAt(e.target.value); setMessage(null); }} />
                    </label>
                    <div className="schedule-actions">
                      <button type="submit" className="suggest-button" disabled={saving}>{saving ? t("Adding…", "Добавление…") : t("Add match", "Добавить матч")}</button>
                      {message && <span className={message.ok ? "suggest-ok" : "suggest-error"} role="status">{message.text}</span>}
                    </div>
                  </form>
                </section>

                <section className="player-box">
                  <h2 className="player-box-title">{t("Upcoming matches", "Предстоящие матчи")}</h2>
                  {!upcoming ? <p className="match-empty">{t("Loading…", "Загрузка…")}</p>
                    : !upcoming.length ? <p className="match-empty">{t("Nothing scheduled yet.", "Пока ничего не назначено.")}</p>
                    : groups.map(([label, matches]) => (
                        <div key={label}>
                          <div className="schedule-day">{label}</div>
                          {matches.map((m) => (
                            <div className="schedule-item" key={m.id}>
                              <span className="schedule-time">{time(m.starts_at)}</span>
                              <span className="player-ellipsis">
                                {m.player1.id ? <Link className="player-match-link" to={`/player/${m.player1.id}`}>{m.player1.name}</Link> : m.player1.name}
                                {" vs "}
                                {m.player2.id ? <Link className="player-match-link" to={`/player/${m.player2.id}`}>{m.player2.name}</Link> : m.player2.name}
                              </span>
                              <span className="player-label player-ellipsis">{m.tournament_title} · {t("by", "добавил(а)")} {m.added_by}</span>
                              {(staff || m.added_by === user?.nickname)
                                ? <button type="button" className="player-control" onClick={() => remove(m.id)}>{t("Remove", "Удалить")}</button>
                                : <span />}
                            </div>
                          ))}
                        </div>
                      ))}
                </section>
              </>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
