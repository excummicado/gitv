import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { banUser, clearSession, NICKNAME_HINT, NICKNAME_HINT_RU, NICKNAME_PATTERN, ROLE_LABELS, ROLE_LABELS_RU, setRole, unbanUser, updateNickname, type AssignableRole, type Role } from "../auth/client";
import { useLang } from "../i18n";
import { useAuth } from "../auth/useCurrentUser";
import { Navbar } from "../components/Navbar";
import { SignOutIcon } from "../components/SignOutIcon";
import { Brand } from "../components/Brand";
import { SuggestionBansForm, SuggestionsQueue } from "../suggestions/ReviewPanels";
import "./profile.css";

function PenIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 20h4L18.5 9.5a2.83 2.83 0 0 0-4-4L4 16v4" />
      <path d="M13.5 6.5l4 4" />
    </svg>
  );
}

function useProfileText() {
  const { t, lang } = useLang();
  return {
    t,
    hint: t(NICKNAME_HINT, NICKNAME_HINT_RU),
    role: (role: Role) => (lang === "ru" ? ROLE_LABELS_RU : ROLE_LABELS)[role],
  };
}

function NicknameEditor({ current, onDone }: { current: string; onDone: () => void }) {
  const { t, hint } = useProfileText();
  const [value, setValue] = useState(current);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const chosen = value.trim();
    if (chosen === current) return onDone();
    if (!NICKNAME_PATTERN.test(chosen)) return setError(`${t("Use", "Используйте")} ${hint}`);
    setSaving(true);
    try {
      await updateNickname(chosen);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Couldn't save the nickname. Try again.", "Не удалось сохранить ник. Попробуйте ещё раз."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="profile-edit" onSubmit={handleSubmit} noValidate>
      <div className="profile-edit-row">
        <input
          className="profile-edit-input"
          aria-label={t("Nickname", "Ник")}
          value={value}
          onChange={(event) => { setValue(event.target.value); setError(""); }}
          onKeyDown={(event) => { if (event.key === "Escape") onDone(); }}
          maxLength={32}
          autoFocus
        />
        <button type="submit" className="profile-action" disabled={saving}>{saving ? t("Saving…", "Сохранение…") : t("Save", "Сохранить")}</button>
        <button type="button" className="profile-action profile-action--quiet" onClick={onDone} disabled={saving}>{t("Cancel", "Отмена")}</button>
      </div>
      <div className={error ? "profile-edit-error" : "profile-edit-hint"} role={error ? "alert" : undefined}>{error || hint}</div>
    </form>
  );
}

type Message = { text: string; ok: boolean } | null;

// Shared by the staff boxes: nickname field, its result line, and a runner that reports success or the API's error.
function useNicknameAction(onEdit?: () => void) {
  const { t } = useLang();
  const [nickname, setNickname] = useState("");
  const [message, setMessage] = useState<Message>(null);
  const [saving, setSaving] = useState(false);

  async function run(action: (nickname: string) => Promise<string>) {
    const target = nickname.trim();
    if (!target) return setMessage({ text: t("Enter a nickname.", "Введите ник."), ok: false });
    setSaving(true);
    try {
      setMessage({ text: await action(target), ok: true });
      setNickname("");
    } catch (err) {
      setMessage({ text: err instanceof Error ? err.message : t("Couldn't save the change. Try again.", "Не удалось сохранить изменение. Попробуйте ещё раз."), ok: false });
    } finally {
      setSaving(false);
    }
  }

  const field = (
    <input
      className="profile-edit-input profile-edit-input--small"
      aria-label={t("Nickname", "Ник")}
      placeholder={t("Nickname", "Ник")}
      value={nickname}
      onChange={(event) => { setNickname(event.target.value); setMessage(null); onEdit?.(); }}
      maxLength={32}
    />
  );
  const result = message && <div className={message.ok ? "profile-edit-success" : "profile-edit-error"} role="status">{message.text}</div>;
  return { run, saving, field, result, nickname: nickname.trim(), setMessage };
}

// Mirrors the API: admins move people between member, writer and event organizer; super admins can also give admin.
const ASSIGNABLE: Record<"admin" | "super_admin", AssignableRole[]> = {
  admin: ["user", "writer", "event_organizer"],
  super_admin: ["user", "writer", "event_organizer", "admin"],
};

function RolesForm({ actorRole }: { actorRole: "admin" | "super_admin" }) {
  const { t, role: roleLabel } = useProfileText();
  // Set role only asks; the change is sent after Confirm. Editing the nickname or role drops the question.
  const [confirming, setConfirming] = useState(false);
  const { run, saving, field, result, nickname, setMessage } = useNicknameAction(() => setConfirming(false));
  const [role, setRoleChoice] = useState<AssignableRole>("writer");
  const options = ASSIGNABLE[actorRole];

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!nickname) return setMessage({ text: t("Enter a nickname.", "Введите ник."), ok: false });
    setMessage(null);
    setConfirming(true);
  }

  function confirm() {
    setConfirming(false);
    run(async (target) => {
      const user = await setRole(target, role);
      return t(`${user.nickname} is now ${ROLE_LABELS[user.role].toLowerCase()}. They need to sign in again.`,
               `${user.nickname} теперь ${ROLE_LABELS_RU[user.role].toLowerCase()}. Ему нужно войти заново.`);
    });
  }

  return (
    <section className="player-box profile-panel">
      <h2 className="player-box-title">{t("Roles", "Роли")}</h2>
      <form className="profile-panel-body" onSubmit={handleSubmit} noValidate>
        <div className="profile-edit-row">
          {field}
          <select className="profile-select" aria-label={t("Role", "Роль")} value={role} onChange={(event) => { setRoleChoice(event.target.value as AssignableRole); setConfirming(false); }}>
            {options.map((option) => <option key={option} value={option}>{roleLabel(option)}</option>)}
          </select>
          <button type="submit" className="profile-action" disabled={saving || confirming}>{t("Set role", "Назначить")}</button>
        </div>
        {confirming && (
          <div className="profile-confirm" role="alertdialog" aria-label={t("Confirm role change", "Подтвердите смену роли")}>
            <span>{t("Make", "Сделать")} <strong>{nickname}</strong> {roleLabel(role).toLowerCase()}?</span>
            <button type="button" className="profile-action" onClick={confirm} autoFocus>{t("Confirm", "Подтвердить")}</button>
            <button type="button" className="profile-action profile-action--quiet" onClick={() => setConfirming(false)}>{t("Cancel", "Отмена")}</button>
          </div>
        )}
        {result}
      </form>
    </section>
  );
}

function BansForm() {
  const { t } = useLang();
  const { run, saving, field, result } = useNicknameAction();

  return (
    <section className="player-box profile-panel">
      <h2 className="player-box-title">{t("Bans", "Баны")}</h2>
      {/* No submit on Enter: banning always needs the explicit button. */}
      <form className="profile-panel-body" onSubmit={(event) => event.preventDefault()} noValidate>
        <div className="profile-edit-row">
          {field}
          <button type="button" className="profile-action profile-action--danger" disabled={saving}
            onClick={() => run(async (nickname) => { const n = (await banUser(nickname)).nickname; return t(`${n} is banned and signed out.`, `${n} забанен и выкинут из аккаунта.`); })}>{t("Ban", "Забанить")}</button>
          <button type="button" className="profile-action profile-action--quiet" disabled={saving}
            onClick={() => run(async (nickname) => { const n = (await unbanUser(nickname)).nickname; return t(`${n} is no longer banned.`, `${n} разбанен.`); })}>{t("Unban", "Разбанить")}</button>
        </div>
        {result}
      </form>
    </section>
  );
}

export function ProfilePage() {
  const { user, ready } = useAuth();
  const { t, role: roleLabel } = useProfileText();
  const [editing, setEditing] = useState(false);

  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="player-content">
            {!ready ? null : user ? (
              <section className="player-box player-header">
                <div className="profile-top">
                  <div className="profile-name">
                    {editing ? (
                      <NicknameEditor current={user.nickname} onDone={() => setEditing(false)} />
                    ) : (
                      <div className="profile-name-row">
                        <div className="player-nickname">{user.nickname}</div>
                        <button type="button" className="profile-pen" onClick={() => setEditing(true)} aria-label={t("Change nickname", "Сменить ник")} title={t("Change nickname", "Сменить ник")}>
                          <PenIcon />
                        </button>
                      </div>
                    )}
                    {user.discord_username && <div className="profile-discord">@{user.discord_username}</div>}
                  </div>
                  {user.role !== "user" && <span className="profile-badge">{roleLabel(user.role)}</span>}
                </div>
                <button type="button" className="profile-signout" onClick={() => clearSession()}><SignOutIcon />{t("Sign out", "Выйти")}</button>
              </section>
            ) : null}
            {ready && (user?.role === "admin" || user?.role === "super_admin") && (
              <div className="profile-panels">
                <RolesForm actorRole={user.role} />
                <BansForm />
                <SuggestionBansForm />
                <SuggestionsQueue />
              </div>
            )}
            {!ready || user ? null : (
              <section className="player-box player-header">
                <div className="player-nickname">{t("Your profile", "Ваш профиль")}</div>
                <div className="player-fullname">{t("Sign in with Discord to see your profile.", "Войдите через Discord, чтобы увидеть профиль.")}</div>
                <Link to="/login" className="profile-signin">{t("Sign in", "Войти")}</Link>
              </section>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
