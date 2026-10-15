import { useEffect, useState, type ReactNode } from "react";
import "./gitv-preview.css";

import { Link } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { fetchChampions, type Champion } from "../player/api";
import { fetchLiveTournaments, fetchTopPick, type LiveTournament, type TopPick } from "../match/api";
import { useLang } from "../i18n";

const CHAMPIONS = 5;
const headlines = [1, 2, 3, 4, 5, 6];
const matches = [1, 2, 3, 4, 5];

function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`gitv-card ${className}`}>{children}</section>;
}

function Rows({ count, children }: { count: number; children: (index: number) => ReactNode }) {
  return <>{Array.from({ length: count }, (_, index) => children(index))}</>;
}

// Promo: the most picked character of the latest tournament, over its splash art.
function TopPickPromo() {
  const [pick, setPick] = useState<TopPick | null | undefined>(undefined);
  const { t, name, count } = useLang();

  useEffect(() => {
    const controller = new AbortController();
    fetchTopPick(controller.signal).then(setPick).catch(() => { if (!controller.signal.aborted) setPick(null); });
    return () => controller.abort();
  }, []);

  if (!pick) return <Card><div className="gitv-image gitv-promo">{pick === undefined ? "" : t("Promo image", "Промо-изображение")}</div></Card>;
  const art = pick.character.splash ?? pick.character.card ?? pick.character.icon;
  return (
    <Card>
      <Link to={`/matches?tournament=${pick.tournament.id}`} className="gitv-promo gitv-top-pick">
        {art && <img src={art} alt="" className="gitv-top-pick-art" />}
        <span className="gitv-top-pick-text">
          <small>{t("Most picked", "Самый частый пик")} · {pick.tournament.title}</small>
          <strong>{name(pick.character)}</strong>
          <small>
            {t(`${pick.picks} of ${pick.games} teams`, `${pick.picks} из ${count(pick.games, ["team", "teams"], ["состава", "составов", "составов"])}`)}
            {pick.pick_rate != null && ` · ${pick.pick_rate}%`}
            {pick.winrate != null && ` · ${t("WR", "ВР")} ${pick.winrate}%`}
          </small>
        </span>
      </Link>
    </Card>
  );
}

// Tournaments running now on the site; their finished matches come in with `app.cli sync`.
function LiveTournaments() {
  const [items, setItems] = useState<LiveTournament[] | null>(null);
  const { t, count } = useLang();

  useEffect(() => {
    const controller = new AbortController();
    const load = () => fetchLiveTournaments(controller.signal).then(setItems).catch(() => { if (!controller.signal.aborted) setItems([]); });
    load();
    // The list is cached for a minute on the API, so checking again every minute is enough.
    const timer = setInterval(load, 60000);
    return () => { controller.abort(); clearInterval(timer); };
  }, []);

  return (
    <Card><div className="gitv-card-title">{t("Live Tournaments", "Идущие турниры")}</div>
      {!items ? <div className="gitv-row"><small>…</small></div>
        : !items.length ? <div className="gitv-row"><small>{t("No tournaments running right now.", "Сейчас турниров нет.")}</small></div>
        : items.map((item) => (
            <div className="gitv-row" key={item.id}>
              {item.image ? <img src={item.image} alt="" className="gitv-square gitv-live-image" /> : <i className="gitv-square" />}
              <span className="gitv-champion-text">
                {item.imported_matches
                  ? <Link to={`/matches?tournament=${item.id}`} className="gitv-row-link">{item.title}</Link>
                  : <span>{item.title}</span>}
                <small className="gitv-champion-tournament">
                  {item.imported_matches ? count(item.imported_matches, ["match played", "matches played"], ["матч сыгран", "матча сыграно", "матчей сыграно"]) : t("No matches finished yet", "Матчей пока нет")}
                </small>
              </span>
              <b className="gitv-badge push">{t("Live", "Идёт")}</b>
            </div>
          ))}
    </Card>
  );
}

// Winners of the latest tournaments, each player once (see GET /api/v1/players/champions).
function RecentChampions() {
  const [champions, setChampions] = useState<Champion[] | null>(null);
  const [failed, setFailed] = useState(false);
  const { t, locale } = useLang();

  useEffect(() => {
    const controller = new AbortController();
    fetchChampions(CHAMPIONS, controller.signal).then(setChampions).catch(() => { if (!controller.signal.aborted) setFailed(true); });
    return () => controller.abort();
  }, []);

  return (
    <Card><div className="gitv-card-title">{t("Recent Champions", "Последние чемпионы")}</div>
      {failed ? <div className="gitv-row"><small>{t("Couldn't load the champions.", "Не удалось загрузить чемпионов.")}</small></div>
        : !champions ? <Rows count={CHAMPIONS}>{(i) => <div className="gitv-row" key={i}><small>{i + 1}.</small><i className="gitv-square" /><small>…</small></div>}</Rows>
        : champions.map((c, i) => (
            <div className="gitv-row gitv-champion" key={c.player.id}>
              <small>{i + 1}.</small>
              <i className="gitv-square" />
              <span className="gitv-champion-text">
                <Link to={`/player/${c.player.id}`} className="gitv-row-link">{c.player.name}</Link>
                <Link to={`/match/${c.final_match_id}`} className="gitv-row-link gitv-champion-tournament">{c.tournament.title}</Link>
              </span>
            </div>
          ))}
      <div className="gitv-foot"><Link to="/players" className="gitv-row-link">{t("All players", "Все игроки")}</Link>{champions?.length ? <><br />{t("Updated", "Обновлено")}: {new Date(champions[0].date).toLocaleDateString(locale, { day: "2-digit", month: "short" })}</> : null}</div>
    </Card>
  );
}

function GitvPreview() {
  const { t } = useLang();
  return (
    <div className="gitv-frame">
      <Navbar />
      <div className="gitv-content">
        <Brand />
        <div className="gitv-columns">
          <aside>
            <TopPickPromo />
            <RecentChampions />
            <LiveTournaments />
          </aside>
          <main>
            <div className="gitv-image gitv-banner">{t("Event banner", "Баннер события")} <b className="gitv-badge live">{t("Live", "Идёт")}</b></div>
            <div className="gitv-tabs"><span>{t("Overview", "Обзор")}</span><span>{t("Matches", "Матчи")}</span><span>{t("Results", "Результаты")}</span><span>{t("Stats", "Статистика")}</span></div>
            <Card><div className="gitv-image gitv-feature">{t("Featured image", "Главное изображение")}</div></Card>
            <div className="gitv-section-label">{t("Today's News", "Новости дня")}</div>
            <Card><Rows count={headlines.length}>{(i) => <div className="gitv-row gitv-headline" key={i}><i className="gitv-line" /><span>{t("Headline text", "Заголовок новости")}</span><small className="push">{t("00 min ago", "00 мин назад")}<br />{t("00 comments", "00 комментариев")}</small></div>}</Rows></Card>
          </main>
          <aside>
            <Card><div className="gitv-card-title tinted">{t("Today's Matches", "Матчи дня")}</div><Rows count={matches.length}>{(i) => <div className="gitv-row gitv-match" key={i}><div className="gitv-matchline"><span><i className="gitv-line" />{t("Player A", "Игрок A")}</span><b>{i < 2 ? "0 (0)" : "00:00"}</b></div><div className="gitv-matchline"><span><i className="gitv-line" />{t("Player B", "Игрок B")}</span>{i < 2 && <b>0 (0)</b>}</div></div>}</Rows></Card>
          </aside>
        </div>
      </div>
    </div>
  );
}

export function Welcome() {
  return <main className="gitv-page"><GitvPreview /></main>;
}
