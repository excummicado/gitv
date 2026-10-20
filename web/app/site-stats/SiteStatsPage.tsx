import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { STAFF_ROLES } from "../auth/client";
import { useCurrentUser } from "../auth/useCurrentUser";
import { useLang } from "../i18n";
import { fetchAnalytics, type Analytics } from "./api";
import "./site-stats.css";

const PERIODS = [7, 30, 90];

// Pages with ids grouped in the summary; readable names for them.
const SECTION_NAMES: Record<string, [string, string]> = {
  "/": ["Home", "Главная"], "/players": ["Players", "Игроки"], "/player/:id": ["Player pages", "Профили игроков"],
  "/player/:id/compare": ["Comparisons", "Сравнения"], "/matches": ["Matches", "Матчи"], "/match/:id": ["Match pages", "Страницы матчей"],
  "/tournaments": ["Tournaments", "Турниры"], "/tournament/:id": ["Tournament pages", "Страницы турниров"],
  "/characters": ["Characters", "Персонажи"], "/schedule": ["Schedule", "Расписание"], "/profile": ["Profile", "Профиль"],
  "/login": ["Sign in", "Вход"],
};

function DailyChart({ data }: { data: Analytics }) {
  const { t, locale } = useLang();
  const most = Math.max(1, ...data.days.map((d) => d.views));
  return (
    <div className="stats-chart" role="img" aria-label={t("Views and visitors per day", "Просмотры и посетители по дням")}>
      {data.days.map((d) => (
        <div className="stats-bar" key={d.day}
          title={`${new Date(d.day).toLocaleDateString(locale, { day: "2-digit", month: "short" })}: ${d.views} ${t("views", "просмотров")}, ${d.visitors} ${t("visitors", "посетителей")}`}>
          <span className="stats-bar-views" style={{ height: `${(d.views / most) * 100}%` }} />
          <span className="stats-bar-visitors" style={{ height: `${(d.visitors / most) * 100}%` }} />
        </div>
      ))}
    </div>
  );
}

function Table({ title, rows, empty }: { title: string; rows: { label: React.ReactNode; value: number }[]; empty: string }) {
  const most = Math.max(1, ...rows.map((r) => r.value));
  return (
    <section className="player-box">
      <h2 className="player-box-title">{title}</h2>
      {rows.length === 0 ? <p className="player-message">{empty}</p> : rows.map((r, i) => (
        <div className="stats-row" key={i}>
          <span className="stats-row-fill" style={{ width: `${(r.value / most) * 100}%` }} aria-hidden />
          <span className="player-ellipsis">{r.label}</span>
          <b>{r.value}</b>
        </div>
      ))}
    </section>
  );
}

export function SiteStatsPage() {
  const user = useCurrentUser();
  const staff = user ? STAFF_ROLES.includes(user.role) : false;
  const { t } = useLang();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<Analytics | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!staff) return;
    setError("");
    fetchAnalytics(days).then(setData).catch((err) => setError(err instanceof Error ? err.message : t("Couldn't load the analytics.", "Не удалось загрузить аналитику.")));
  }, [staff, days]);

  const sectionName = (path: string) => (SECTION_NAMES[path] ? t(...SECTION_NAMES[path]) : path);
  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="player-content match-content">
            {!staff ? <p className="player-box player-message">{t("Only admins can see the analytics.", "Аналитика доступна только админам.")}</p>
              : error ? <p className="player-box player-message">{error}</p>
              : !data ? <p className="player-box player-message">{t("Loading analytics…", "Загрузка аналитики…")}</p>
              : <>
                <div className="stats-head">
                  <span className="player-segment">
                    {PERIODS.map((p) => (
                      <button type="button" key={p} className={`player-control${days === p ? " active" : ""}`} onClick={() => setDays(p)}>
                        {t(`${p} days`, `${p} дн.`)}
                      </button>
                    ))}
                  </span>
                  <span className="player-label stats-note">{t("No cookies or IP addresses are stored; bots and Do Not Track are left out.",
                    "Cookies и IP-адреса не хранятся; боты и Do Not Track не учитываются.")}</span>
                </div>
                <div className="player-records stats-records">
                  <div className="player-record"><span className="player-label">{t("On the site now", "Сейчас на сайте")}</span><span className="player-value stats-live">{data.active_now}</span></div>
                  <div className="player-record"><span className="player-label">{t("Today: views", "Сегодня: просмотры")}</span><span className="player-value">{data.today.views}</span></div>
                  <div className="player-record"><span className="player-label">{t("Today: visitors", "Сегодня: посетители")}</span><span className="player-value">{data.today.visitors}</span></div>
                  <div className="player-record"><span className="player-label">{t(`Views, ${days} days`, `Просмотры за ${days} дн.`)}</span><span className="player-value">{data.views}</span></div>
                  <div className="player-record" title={t("Daily visitors added up: someone who came on two days counts twice",
                    "Сумма посетителей по дням: кто заходил в два разных дня, считается дважды")}>
                    <span className="player-label">{t(`Visitors, ${days} days`, `Посетители за ${days} дн.`)}</span><span className="player-value">{data.visitors}</span>
                  </div>
                </div>
                <section className="player-box">
                  <h2 className="player-box-title stats-chart-title">
                    <span>{t("Per day", "По дням")}</span>
                    <span className="stats-legend"><i className="views" />{t("views", "просмотры")} <i className="visitors" />{t("visitors", "посетители")}</span>
                  </h2>
                  <DailyChart data={data} />
                </section>
                <div className="stats-columns">
                  <Table title={t("Sections", "Разделы")} empty={t("No views yet.", "Просмотров пока нет.")}
                    rows={data.top_sections.map((s) => ({ label: sectionName(s.path), value: s.views }))} />
                  <Table title={t("Pages", "Страницы")} empty={t("No views yet.", "Просмотров пока нет.")}
                    rows={data.top_pages.map((p) => ({ label: <Link className="player-match-link" to={p.path}>{p.path}</Link>, value: p.views }))} />
                  <Table title={t("Came from", "Откуда пришли")} empty={t("No visits from other sites yet.", "Переходов с других сайтов пока нет.")}
                    rows={data.top_referrers.map((r) => ({ label: r.host, value: r.visits }))} />
                </div>
              </>}
          </div>
        </div>
      </div>
    </main>
  );
}
