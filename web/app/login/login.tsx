import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import "./login.css";
import { useLang } from "../i18n";

export function Login() {
  const { t } = useLang();
  return (
    <main className="gitv-page">
      <div className="gitv-frame">
        {/* Full-width nav matching main page */}
        <Navbar />

        {/* Centered content stripe */}
        <div className="gitv-content">
          <Brand />

          {/* Discord is the only sign-in; the first sign-in creates the account. */}
          <div className="login-wrapper">
            <div className="login-card">
              <div className="login-header">
                <h1 className="login-title">{t("Sign in to GITV", "Вход в GITV")}</h1>
                <div className="login-subtitle">{t("GITV uses your Discord account. Signing in for the first time creates your profile.", "GITV использует ваш аккаунт Discord. При первом входе создаётся профиль.")}</div>
              </div>

              {/* A full page load, not a router Link: the browser leaves the app for Discord. */}
              <a href="/api/v1/auth/discord/login" className="login-btn">{t("Continue with Discord", "Войти через Discord")}</a>

              <div className="login-footer">
                {t("You'll be asked to share your Discord username and email.", "Discord попросит разрешить доступ к имени пользователя и почте.")}
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
