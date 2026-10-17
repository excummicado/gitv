import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { useAuth } from "../auth/useCurrentUser";
import { PLAYER_EDITOR_ROLES, STAFF_ROLES } from "../auth/client";
import { editProfile, mySuggestions, suggest, type MySuggestions, type PlayerInfo, type ProfileChange } from "./api";
import "./suggestions.css";
import { useLang } from "../i18n";

const MAX_AVATAR = 2 * 1024 * 1024;
const AVATAR_TYPES = ["image/png", "image/jpeg", "image/webp"];
const FIELD_LABELS: Record<ProfileChange["field"], [string, string]> = { real_name: ["name", "имя"], birth_date: ["birthday", "дату рождения"], avatar: ["avatar", "аватар"] };

// The API's youngest allowed age is 8.
function latestBirthday() {
  const d = new Date();
  d.setFullYear(d.getFullYear() - 8);
  return d.toISOString().slice(0, 10);
}

function showValue(l: ReturnType<typeof useLang>, field: ProfileChange["field"], value: string | null) {
  if (value == null) return l.t("nothing", "пусто");
  return field === "birth_date" ? l.date(value) : `«${value}»`;
}

// Every change leaves a trace: who made it, when, from what to what, and whose suggestion it was.
function History({ history }: { history: ProfileChange[] }) {
  const l = useLang();
  const { t } = l;
  if (!history.length) return null;
  return (
    <div className="suggest-history">
      <h3 className="suggest-history-title">{t("Changes", "Изменения")}</h3>
      <ul>
        {history.map((h, i) => (
          <li key={i}>
            <span className="gitv-date">{l.date(h.created_at)}</span>{" "}
            <strong>{h.changed_by}</strong>{" "}
            {h.field === "avatar"
              ? t("changed the avatar", "сменил(а) аватар")
              : `${t("set the", "изменил(а)")} ${t(...FIELD_LABELS[h.field])} ${t("to", "на")} ${showValue(l, h.field, h.new_value)}`}
            {h.field !== "avatar" && h.old_value != null && <span className="suggest-was"> ({t("was", "было")} {showValue(l, h.field, h.old_value)})</span>}
            {h.suggested_by && <span className="suggest-was"> · {t("suggested by", "предложил(а)")} {h.suggested_by}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

// Event organizers and admins: write the name and birthday directly. Only changed fields are sent.
function EditForm({ playerId, profile, onEdited }: { playerId: string; profile: PlayerInfo | null; onEdited: () => void }) {
  const [name, setName] = useState(profile?.real_name ?? "");
  const [birthday, setBirthday] = useState(profile?.birth_date ?? "");
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const [saving, setSaving] = useState(false);
  const { t } = useLang();

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const changes: { real_name?: string | null; birth_date?: string | null } = {};
    if (name.trim() !== (profile?.real_name ?? "")) changes.real_name = name.trim() || null;
    if (birthday !== (profile?.birth_date ?? "")) changes.birth_date = birthday || null;
    if (!Object.keys(changes).length) return setMessage({ text: t("Nothing changed.", "Ничего не изменилось."), ok: false });
    setSaving(true);
    try {
      await editProfile(playerId, changes);
      setMessage({ text: t("Saved.", "Сохранено."), ok: true });
      onEdited();
    } catch (err) {
      setMessage({ text: err instanceof Error ? err.message : t("Couldn't save. Try again.", "Не удалось сохранить. Попробуйте ещё раз."), ok: false });
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="suggest-form" onSubmit={save} noValidate>
      <label className="suggest-field">
        <span className="player-label">{t("Real name", "Настоящее имя")}</span>
        <input className="suggest-input" value={name} maxLength={80} placeholder={t("First and last name", "Имя и фамилия")} onChange={(e) => { setName(e.target.value); setMessage(null); }} />
      </label>
      <label className="suggest-field">
        <span className="player-label">{t("Birthday", "Дата рождения")}</span>
        <input className="suggest-input" type="date" min="1950-01-01" max={latestBirthday()} value={birthday} onChange={(e) => { setBirthday(e.target.value); setMessage(null); }} />
      </label>
      <div className="suggest-field suggest-field--end">
        <button type="submit" className="suggest-button" disabled={saving}>{saving ? t("Saving…", "Сохранение…") : t("Save", "Сохранить")}</button>
      </div>
      {message && <p className={message.ok ? "suggest-ok suggest-message" : "suggest-error"} role="status">{message.text}</p>}
      <p className="suggest-note">{t("Leave a field empty to clear it. Your nickname is recorded with every change.", "Пустое поле очищает значение. Ваш ник записывается с каждым изменением.")}</p>
    </form>
  );
}

// Everyone else: suggest a name, birthday or avatar for an admin to review.
function SuggestForm({ playerId, playerName }: { playerId: string; playerName: string }) {
  const [status, setStatus] = useState<MySuggestions | null>(null);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [birthday, setBirthday] = useState("");
  const [avatar, setAvatar] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const [saving, setSaving] = useState(false);
  const { t } = useLang();

  useEffect(() => {
    mySuggestions().then(setStatus).catch(() => setStatus(null));
  }, []);

  useEffect(() => {
    if (!avatar) return setPreview(null);
    const url = URL.createObjectURL(avatar);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [avatar]);

  function pickAvatar(file: File | null) {
    setError("");
    if (file && !AVATAR_TYPES.includes(file.type)) return setError(t("The avatar must be a PNG, JPEG or WebP image.", "Аватар должен быть картинкой PNG, JPEG или WebP."));
    if (file && file.size > MAX_AVATAR) return setError(t("The avatar must be 2 MB or smaller.", "Аватар должен весить не больше 2 МБ."));
    setAvatar(file);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() && !birthday && !avatar) return setError(t("Fill in at least one field.", "Заполните хотя бы одно поле."));
    const form = new FormData();
    if (name.trim()) form.set("real_name", name.trim());
    if (birthday) form.set("birth_date", birthday);
    if (avatar) form.set("avatar", avatar);
    setSaving(true);
    setError("");
    try {
      await suggest(playerId, form);
      setSent(true);
      setOpen(false);
      setName("");
      setBirthday("");
      setAvatar(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Couldn't send the suggestion. Try again.", "Не удалось отправить предложение. Попробуйте ещё раз."));
    } finally {
      setSaving(false);
    }
  }

  if (status?.banned) return <p className="suggest-text">{t("You can't make suggestions.", "Вам запрещено делать предложения.")}</p>;
  if (sent && !open) return <p className="suggest-text suggest-ok" role="status">{t("Thanks! An admin will review your suggestion.", "Спасибо! Админ проверит ваше предложение.")}</p>;
  if (!open) {
    return (
      <div className="suggest-row">
        <p className="suggest-text">{t(`Know ${playerName}'s real name, birthday or have a better avatar?`, `Знаете настоящее имя или дату рождения ${playerName} или есть аватар получше?`)}</p>
        <button type="button" className="suggest-button" onClick={() => setOpen(true)}>{t("Suggest", "Предложить")}</button>
      </div>
    );
  }
  return (
    <form className="suggest-form" onSubmit={submit} noValidate>
      <label className="suggest-field">
        <span className="player-label">{t("Real name", "Настоящее имя")}</span>
        <input className="suggest-input" value={name} maxLength={80} placeholder={t("First and last name", "Имя и фамилия")} onChange={(e) => { setName(e.target.value); setError(""); }} />
      </label>
      <label className="suggest-field">
        <span className="player-label">{t("Birthday", "Дата рождения")}</span>
        <input className="suggest-input" type="date" min="1950-01-01" max={latestBirthday()} value={birthday} onChange={(e) => { setBirthday(e.target.value); setError(""); }} />
      </label>
      <label className="suggest-field">
        <span className="player-label">{t("Avatar (PNG, JPEG or WebP, up to 2 MB)", "Аватар (PNG, JPEG или WebP, до 2 МБ)")}</span>
        <span className="suggest-avatar">
          {preview && <img src={preview} alt="" width={48} height={48} />}
          <input className="suggest-input" type="file" accept={AVATAR_TYPES.join(",")} onChange={(e) => pickAvatar(e.target.files?.[0] ?? null)} />
        </span>
      </label>
      {error && <p className="suggest-error" role="alert">{error}</p>}
      <div className="suggest-actions">
        <button type="submit" className="suggest-button" disabled={saving}>{saving ? t("Sending…", "Отправка…") : t("Send suggestion", "Отправить")}</button>
        <button type="button" className="suggest-button suggest-quiet" onClick={() => { setOpen(false); setError(""); }}>{t("Cancel", "Отмена")}</button>
        {status && <span className="player-label suggest-limit">{t(`${status.pending} of ${status.max_pending} suggestions waiting for review`, `На проверке: ${status.pending} из ${status.max_pending}`)}</span>}
      </div>
    </form>
  );
}

// Bottom of a player page: their real name, birthday and avatar. Members suggest; event organizers and
// admins write directly (admins also review suggestions on their profile); the change log is public.
export function SuggestBox({ playerId, playerName, profile, history, onEdited }: {
  playerId: string; playerName: string; profile: PlayerInfo | null; history: ProfileChange[]; onEdited: () => void;
}) {
  const { user, ready } = useAuth();
  const { t } = useLang();
  if (!ready) return null;
  const editor = user ? PLAYER_EDITOR_ROLES.includes(user.role) : false;
  const staff = user ? STAFF_ROLES.includes(user.role) : false;

  let body;
  if (!user) {
    body = <p className="suggest-text">{t(`Know who ${playerName} is?`, `Знаете, кто такой ${playerName}?`)} <Link to="/login" className="suggest-link">{t("Sign in", "Войдите")}</Link>{t(" to suggest their real name, birthday or avatar.", ", чтобы предложить настоящее имя, дату рождения или аватар.")}</p>;
  } else if (editor) {
    body = (
      <>
        {/* Keyed on the saved values, so the form shows them again after a save elsewhere. */}
        <EditForm key={`${profile?.real_name}|${profile?.birth_date}`} playerId={playerId} profile={profile} onEdited={onEdited} />
        {staff && <p className="suggest-note">{t("Members' suggestions, avatars included, are reviewed on ", "Предложения пользователей, включая аватары, проверяются в ")}<Link to="/profile" className="suggest-link">{t("your profile", "вашем профиле")}</Link>.</p>}
      </>
    );
  } else {
    body = <SuggestForm playerId={playerId} playerName={playerName} />;
  }

  return (
    <section className="player-box suggest-box">
      <h2 className="player-box-title">{editor ? t("Edit player info", "Редактировать данные игрока") : t("Suggest player info", "Предложить данные игрока")}</h2>
      <div className="suggest-body">
        {body}
        <History history={history} />
      </div>
    </section>
  );
}
