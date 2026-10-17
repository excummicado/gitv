import { useEffect, useState } from "react";
import { Link } from "react-router";
import { acceptSuggestion, banSuggestions, listSuggestionBans, listSuggestions, rejectSuggestion, unbanSuggestions, type Suggestion } from "./api";
import "./suggestions.css";
import { useLang } from "../i18n";

// One suggested value, with what the player page shows now crossed out next to it when it would change.
function Field({ label, value, was }: { label: string; value: string | null; was: string | null | undefined }) {
  if (value == null) return null;
  return (
    <span>
      <span className="player-label">{label}: </span>{value}
      {was && was !== value && <span className="review-was">{was}</span>}
    </span>
  );
}

// Staff: pending suggestions, oldest first; Accept applies the suggested fields, Reject drops them.
export function SuggestionsQueue() {
  const [items, setItems] = useState<Suggestion[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const l = useLang();
  const { t } = l;

  useEffect(() => {
    listSuggestions().then(setItems).catch((err) => setError(err instanceof Error ? err.message : t("Couldn't load suggestions.", "Не удалось загрузить предложения.")));
  }, []);

  async function decide(id: number, accept: boolean) {
    setBusy(id);
    setError("");
    try {
      await (accept ? acceptSuggestion(id) : rejectSuggestion(id));
      setItems((list) => list?.filter((s) => s.id !== id) ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Couldn't save the decision. Try again.", "Не удалось сохранить решение. Попробуйте ещё раз."));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="player-box profile-panel profile-panel--wide">
      <h2 className="player-box-title">{t("Player suggestions", "Предложения по игрокам")}{items ? ` · ${items.length}` : ""}</h2>
      {error && <p className="profile-edit-error review-empty" role="alert">{error}</p>}
      {!items ? !error && <p className="review-empty">{t("Loading…", "Загрузка…")}</p>
        : !items.length ? <p className="review-empty">{t("No suggestions waiting for review.", "Нет предложений на проверку.")}</p>
        : (
          <div className="review-list">
            {items.map((s) => (
              <div className="review-item" key={s.id}>
                {s.avatar_url ? <img className="review-avatar" src={s.avatar_url} alt={t(`Suggested avatar for ${s.player.name}`, `Предложенный аватар для ${s.player.name}`)} /> : <span className="review-avatar" />}
                <div className="review-main">
                  <Link className="review-player" to={`/player/${s.player.id}`}>{s.player.name}</Link>
                  <span className="review-meta"> · {t("by", "от")} {s.author} · {l.date(s.created_at)}</span>
                  <div className="review-fields">
                    <Field label={t("Name", "Имя")} value={s.real_name} was={s.current?.real_name} />
                    <Field label={t("Birthday", "Дата рождения")} value={s.birth_date && `${l.date(s.birth_date)} (${s.age})`} was={s.current?.birth_date && `${l.date(s.current.birth_date)} (${s.current.age})`} />
                    {s.avatar_url && <span><span className="player-label">{t("Avatar", "Аватар")}: </span>{s.current?.avatar_url ? t("replaces the current one", "заменит текущий") : t("new", "новый")}</span>}
                  </div>
                </div>
                <div className="review-actions">
                  <button type="button" className="profile-action" disabled={busy === s.id} onClick={() => decide(s.id, true)}>{t("Accept", "Принять")}</button>
                  <button type="button" className="profile-action profile-action--danger" disabled={busy === s.id} onClick={() => decide(s.id, false)}>{t("Reject", "Отклонить")}</button>
                </div>
              </div>
            ))}
          </div>
        )}
    </section>
  );
}

// Staff: stop a member from making suggestions, or let them again.
export function SuggestionBansForm() {
  const [nickname, setNickname] = useState("");
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const [banned, setBanned] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const { t } = useLang();

  const refresh = () => listSuggestionBans().then(setBanned).catch(() => {});
  useEffect(() => { refresh(); }, []);

  async function run(ban: boolean) {
    const target = nickname.trim();
    if (!target) return setMessage({ text: t("Enter a nickname.", "Введите ник."), ok: false });
    setSaving(true);
    try {
      const result = await (ban ? banSuggestions(target) : unbanSuggestions(target));
      setMessage({ text: result.banned ? t(`${result.nickname} can't make suggestions now.`, `${result.nickname} больше не может делать предложения.`) : t(`${result.nickname} can make suggestions again.`, `${result.nickname} снова может делать предложения.`), ok: true });
      setNickname("");
      refresh();
    } catch (err) {
      setMessage({ text: err instanceof Error ? err.message : t("Couldn't save the change. Try again.", "Не удалось сохранить изменение. Попробуйте ещё раз."), ok: false });
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="player-box profile-panel">
      <h2 className="player-box-title">{t("Suggestion bans", "Запрет на предложения")}</h2>
      <form className="profile-panel-body" onSubmit={(event) => event.preventDefault()} noValidate>
        <div className="profile-edit-row">
          <input className="profile-edit-input profile-edit-input--small" aria-label={t("Nickname", "Ник")} placeholder={t("Nickname", "Ник")} value={nickname} maxLength={32}
            onChange={(event) => { setNickname(event.target.value); setMessage(null); }} />
          <button type="button" className="profile-action profile-action--danger" disabled={saving} onClick={() => run(true)}>{t("Stop", "Запретить")}</button>
          <button type="button" className="profile-action profile-action--quiet" disabled={saving} onClick={() => run(false)}>{t("Allow", "Разрешить")}</button>
        </div>
        {message && <div className={message.ok ? "profile-edit-success" : "profile-edit-error"} role="status">{message.text}</div>}
        <p className="review-ban-list">{banned.length ? `${t("Can't suggest", "Не могут предлагать")}: ${banned.join(", ")}` : t("Everyone can suggest.", "Предлагать могут все.")}</p>
      </form>
    </section>
  );
}
