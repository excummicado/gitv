import { Brand } from "../components/Brand";
import { Navbar } from "../components/Navbar";
import { useLang } from "../i18n";
import "./privacy.css";

// What the site keeps about its visitors and members, in plain words. Keep it in step with the API:
// models.User, services/analytics.py, security.SESSION_COOKIE, the gitv-lang cookie and auth/client.ts.
export function PrivacyPage() {
  const { t } = useLang();
  const sections: [string, string[]][] = [
    [t("Visitors", "Посетители"), [
      t("Page views are counted without cookies and without storing your IP address: a visitor is a hash of the address and browser, salted with a random value replaced every day, so visits on different days can't be linked. Rows are deleted after 90 days.",
        "Просмотры страниц считаются без cookie и без хранения IP-адреса: посетитель — это хеш адреса и браузера с солью, которая меняется каждый день, поэтому визиты в разные дни не связать. Записи удаляются через 90 дней."),
      t("Browsers that send Do Not Track or Global Privacy Control aren't counted at all, and neither are bots.",
        "Браузеры с Do Not Track или Global Privacy Control не учитываются вовсе, как и боты."),
    ]],
    [t("Members", "Участники"), [
      t("Signing in uses Discord, which shares only your account id and username with GITV: no email. GITV keeps those two, the nickname you chose and your role on the site.",
        "Вход — через Discord, который передаёт GITV только id аккаунта и имя пользователя, без почты. GITV хранит их, выбранный ник и роль на сайте."),
    ]],
    [t("Cookies and storage", "Cookie и хранилище"), [
      t("gitv_session — keeps you signed in (only after you sign in; scripts on the page can't read it).",
        "gitv_session — держит вас в аккаунте (только после входа; скрипты страницы его не видят)."),
      t("discord_oauth_state — protects the Discord sign-in, for 10 minutes.", "discord_oauth_state — защищает вход через Discord, 10 минут."),
      t("gitv-lang — the site's language, once you choose it; until then the site follows your browser's language.", "gitv-lang — язык сайта, когда вы его выбрали; до этого сайт следует языку браузера."),
      t("Your browser's local storage keeps your nickname and role, to show them before the page loads.",
        "Локальное хранилище браузера держит ваш ник и роль, чтобы показать их до загрузки страницы."),
    ]],
    [t("Tournament data", "Данные турниров"), [
      t("Players' nicknames, matches and results come from public tournament pages (abyss.darte.gg, Challonge, tournament channels). GITV keeps no real names or birthdays of players.",
        "Ники игроков, матчи и результаты взяты из открытых страниц турниров (abyss.darte.gg, Challonge, каналы турниров). Настоящих имён и дней рождения игроков GITV не хранит."),
      t("Nothing is sold or shared with advertisers. There are no ads and no third-party trackers; fonts load from Google Fonts.",
        "Ничего не продаётся и не передаётся рекламодателям. Рекламы и сторонних трекеров нет; шрифты загружаются с Google Fonts."),
    ]],
    [t("Removing your data", "Удаление данных"), [
      t("Ask the site's admins to delete your account.", "Попросите админов сайта удалить ваш аккаунт."),
    ]],
  ];
  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <article className="player-box privacy">
            <h1 className="player-nickname">{t("Privacy", "Конфиденциальность")}</h1>
            {sections.map(([title, lines]) => (
              <section key={title}>
                <h2 className="player-box-title">{title}</h2>
                {lines.map((line) => <p key={line}>{line}</p>)}
              </section>
            ))}
          </article>
        </div>
      </div>
    </main>
  );
}
