import { Link, useLocation } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { useLang } from "../i18n";
import "./not-found.css";

const LINKS: { to: string; label: [string, string] }[] = [
  { to: "/", label: ["Home", "Главная"] },
  { to: "/players", label: ["Players", "Игроки"] },
  { to: "/tournaments", label: ["Tournaments", "Турниры"] },
  { to: "/matches", label: ["Matches", "Матчи"] },
];

// Shown for any address the site doesn't have (status 404), and by the root error boundary when a page fails
// (status given, e.g. 500): the site's frame, what went wrong, and the main sections to go on from.
export function NotFoundPage({ status = 404 }: { status?: number }) {
  const { t } = useLang();
  const { pathname } = useLocation();
  const missing = status === 404;
  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="player-content match-content">
            <section className="player-box not-found">
              <p className="not-found-code" aria-hidden="true">{status}</p>
              <h1 className="not-found-title">{missing ? t("This page doesn't exist", "Такой страницы нет") : t("Something went wrong", "Что-то пошло не так")}</h1>
              <p className="not-found-text">
                {missing
                  ? <>{t("Nothing lives at ", "По адресу ")}<code>{pathname}</code>{t(". The link may be old or mistyped.", " ничего нет. Возможно, ссылка устарела или в ней опечатка.")}</>
                  : t("The page couldn't be shown. Try again in a moment.", "Страницу не удалось показать. Попробуйте ещё раз чуть позже.")}
              </p>
              <nav className="not-found-links" aria-label={t("Where to go", "Куда перейти")}>
                {LINKS.map((l) => <Link key={l.to} to={l.to} className="not-found-link">{t(...l.label)}</Link>)}
              </nav>
              {missing && <p className="not-found-hint player-label">{t("Looking for a player or a tournament? Use the search at the top.", "Ищете игрока или турнир? Воспользуйтесь поиском вверху.")}</p>}
            </section>
          </div>
        </div>
      </div>
    </main>
  );
}
