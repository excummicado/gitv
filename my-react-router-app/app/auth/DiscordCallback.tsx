import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { ApiError, completeDiscordSignup, loginWithToken, NICKNAME_HINT, NICKNAME_HINT_RU, NICKNAME_PATTERN } from "./client";
import { useLang } from "../i18n";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import "../login/login.css";

const messages: Record<string, [string, string]> = {
  cancelled: ["Discord sign-in was cancelled.", "Вход через Discord отменён."],
  expired: ["This sign-in link expired or was replaced by a newer one. Start again from the sign-in page.", "Ссылка для входа устарела или заменена новой. Начните заново со страницы входа."],
  discord: ["Discord didn't accept the sign-in. Try again.", "Discord не принял вход. Попробуйте ещё раз."],
  unverified_email: ["Verify your email in Discord, then try again.", "Подтвердите почту в Discord и попробуйте ещё раз."],
  email_taken: ["Another GITV account already uses this Discord email.", "Эта почта Discord уже используется другим аккаунтом GITV."],
  banned: ["This account is banned.", "Этот аккаунт забанен."],
};


export function DiscordCallback() {
  const navigate = useNavigate();
  const { t } = useLang();
  const hint = t(NICKNAME_HINT, NICKNAME_HINT_RU);
  const [error, setError] = useState("");
  const [signupToken, setSignupToken] = useState("");
  const [nickname, setNickname] = useState("");
  const [nicknameError, setNicknameError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    // Drop the tokens from the address bar and history.
    window.history.replaceState(null, "", window.location.pathname);

    const signup = params.get("signup_token");
    if (signup) {
      setSignupToken(signup);
      setNickname(params.get("nickname") ?? "");
      return;
    }
    const token = params.get("access_token");
    if (!token) {
      setError(t(...(messages[params.get("error") ?? ""] ?? messages.discord)));
      return;
    }
    loginWithToken(token)
      .then(() => navigate("/", { replace: true }))
      .catch(() => setError(t(...messages.discord)));
  }, [navigate]);

  async function handleSignup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const chosen = nickname.trim();
    if (!NICKNAME_PATTERN.test(chosen)) {
      setNicknameError(`${t("Use", "Используйте")} ${hint}`);
      return;
    }
    setNicknameError("");
    setSubmitting(true);
    try {
      await completeDiscordSignup(signupToken, chosen);
      navigate("/", { replace: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : t(...messages.discord);
      // An expired sign-up can't be retried from this page; anything else is about the nickname.
      if (err instanceof ApiError && err.status === 401) {
        setSignupToken("");
        setError(message);
      } else {
        setNicknameError(message);
      }
    } finally {
      setSubmitting(false);
    }
  }

  const choosing = Boolean(signupToken) && !error;
  const title = choosing ? t("Choose your nickname", "Выберите ник") : error ? t("Discord sign-in failed", "Не удалось войти через Discord") : t("Signing in with Discord…", "Вход через Discord…");

  return (
    <main className="gitv-page">
      <div className="gitv-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="login-wrapper">
            <div className="login-card">
              <div className="login-header">
                <h1 className="login-title">{title}</h1>
                {choosing && <div className="login-subtitle">{t("This is how other members will see you on GITV.", "Так вас будут видеть другие участники GITV.")}</div>}
              </div>

              {choosing && (
                <form onSubmit={handleSignup} noValidate>
                  <div className="login-field">
                    <label className="login-label" htmlFor="signup-nickname">{t("Nickname", "Ник")}</label>
                    <input
                      id="signup-nickname"
                      className="login-input"
                      value={nickname}
                      onChange={(event) => { setNickname(event.target.value); setNicknameError(""); }}
                      autoComplete="username"
                      autoFocus
                      maxLength={32}
                      required
                    />
                    {nicknameError
                      ? <div className="login-field-error" role="alert">{nicknameError}</div>
                      : <div className="login-field-hint">{hint}</div>}
                  </div>
                  <button type="submit" className="login-btn" disabled={submitting}>{submitting ? t("Creating profile…", "Создание профиля…") : t("Create profile", "Создать профиль")}</button>
                </form>
              )}

              {error && <div className="login-error" role="alert">{error}</div>}
              <div className="login-footer">
                {error && <Link to="/login" className="login-link">{t("Back to sign in", "Вернуться ко входу")}</Link>}
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
