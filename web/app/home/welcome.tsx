import { useEffect, useState, type ReactNode } from "react";
import "./home.css";

import { Link } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { fetchChampions, fetchElClasico, type Champion, type ElClasico } from "../player/api";
import { fetchLiveTournaments, fetchPopularCharacters, fetchTopPick, type LiveTournament, type PopularCharacters, type TopPick } from "../match/api";
import { listScheduled, localDay, type ScheduledMatch } from "../schedule/api";
import { fetchFeaturedTournament, fetchTournamentList, type FeaturedTournament, type TournamentRow } from "../tournament/api";
import { useCurrentUser } from "../auth/useCurrentUser";
import { PLAYER_EDITOR_ROLES } from "../auth/client";
import { useLang } from "../i18n";

const CHAMPIONS = 5;
const NEWS = 6;

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

// Banner of the newest tournament: the one running now, else the latest finished, with its art from the site.
function EventBanner({ item }: { item: FeaturedTournament | null | undefined }) {
  const { t, date, count } = useLang();
  if (!item) return <div className="gitv-image gitv-banner">{item === undefined ? "" : t("No tournaments yet", "Турниров пока нет")}</div>;
  const body = (
    <>
      {item.image && <img src={item.image} alt="" className="gitv-banner-art" />}
      <b className={`gitv-badge live${item.live ? "" : " is-finished"}`}>{item.live ? t("Live", "Идёт") : t("Latest", "Последний")}</b>
      <span className="gitv-banner-text">
        <strong>{item.title}</strong>
        <small>
          {item.date && date(item.date)}
          {item.players > 0 && ` · ${count(item.players, ["player", "players"], ["игрок", "игрока", "игроков"])}`}
          {item.organizer && ` · ${t("by", "орг.")} ${item.organizer.name}`}
        </small>
        {item.winner && <small className="gitv-banner-winner">{t("Winner", "Победитель")}: <b>{item.winner.name}</b></small>}
      </span>
    </>
  );
  return item.imported
    ? <Link to={`/tournament/${item.id}`} className="gitv-banner gitv-banner-event">{body}</Link>
    : <div className="gitv-banner gitv-banner-event">{body}</div>;
}

// The links under the banner: sections of the banner's tournament page ("Results" falls back to the table
// when the tournament has no Challonge bracket).
const EVENT_LINKS: { label: [string, string]; tab: string }[] = [
  { label: ["Overview", "Обзор"], tab: "" },
  { label: ["Matches", "Матчи"], tab: "matches" },
  { label: ["Results", "Результаты"], tab: "bracket" },
  { label: ["Stats", "Статистика"], tab: "stats" },
];

function EventSection() {
  const [item, setItem] = useState<FeaturedTournament | null | undefined>(undefined);
  const { t } = useLang();

  useEffect(() => {
    const controller = new AbortController();
    fetchFeaturedTournament(controller.signal).then(setItem).catch(() => { if (!controller.signal.aborted) setItem(null); });
    return () => controller.abort();
  }, []);

  return (
    <>
      <EventBanner item={item} />
      <nav className="gitv-tabs" aria-label={t("Tournament sections", "Разделы турнира")}>
        {EVENT_LINKS.map(({ label, tab }) => item?.imported
          ? <Link key={tab} to={`/tournament/${item.id}${tab ? `?tab=${tab}` : ""}`}>{t(...label)}</Link>
          // A running tournament with no finished match yet has no page to open.
          : <span key={tab} className="is-disabled" aria-disabled="true">{t(...label)}</span>)}
      </nav>
    </>
  );
}

// The five most popular characters of all time. Bans count as much as picks: a character
// banned all the time is as much on players' minds as one picked all the time.
function PopularCharactersCard() {
  const [data, setData] = useState<PopularCharacters | null | undefined>(undefined);
  const { t, name, count } = useLang();

  useEffect(() => {
    const controller = new AbortController();
    fetchPopularCharacters(5, controller.signal).then(setData).catch(() => { if (!controller.signal.aborted) setData(null); });
    return () => controller.abort();
  }, []);

  if (!data) return <Card><div className="gitv-image gitv-feature">{data === undefined ? "" : t("No draft data yet", "Данных драфтов пока нет")}</div></Card>;
  return (
    <Card>
      <div className="gitv-card-title gitv-popular-title">
        <span>{t("Most popular characters", "Самые популярные персонажи")}</span>
        <Link to="/tournaments" className="gitv-row-link">{t("All time", "За всё время")} · {count(data.tournaments, ["tournament", "tournaments"], ["турнир", "турнира", "турниров"])}</Link>
      </div>
      <div className="gitv-popular">
        {data.characters.map((c, i) => {
          const art = c.character.icon;
          return (
            <div className={`gitv-popular-item rarity-${c.character.rarity ?? 4}`} key={c.character.id}
              title={t(`${c.picks} picks, ${c.bans} bans; in ${c.presence ?? 0}% of games; ${c.pick_winrate ?? "—"}% winrate when picked; average C${c.avg_constellation ?? "—"}`,
                       `${c.picks} пиков, ${c.bans} банов; в ${c.presence ?? 0}% игр; винрейт в пиках ${c.pick_winrate ?? "—"}%; средняя конста C${c.avg_constellation ?? "—"}`)}>
              <div className="gitv-popular-art">
                {art && <img src={art} alt="" loading="lazy" />}
                <b className="gitv-popular-rank">{i + 1}</b>
                {c.avg_constellation != null && (
                  <b className="gitv-popular-cons" title={t("Average constellation when picked", "Средняя конста в пиках")}>C{c.avg_constellation.toFixed(1)}</b>
                )}
              </div>
              <strong className="gitv-popular-name">{name(c.character)}</strong>
              <span className="gitv-popular-presence">{c.presence ?? 0}%</span>
              <small><span className="gitv-popular-pick">{c.picks}P</span> · <span className="gitv-popular-ban">{c.bans}B</span></small>
            </div>
          );
        })}
      </div>
      <div className="gitv-foot">{t(`Picks + bans over ${count(data.games, ["game", "games"], ["игра", "игры", "игр"])}; % is the share of games where the character was picked or banned.`,
        `Пики + баны за ${data.games} игр; % — доля игр, где персонажа пикали или банили.`)}</div>
    </Card>
  );
}

// "3 days ago", in the site's language.
function ago(value: string, locale: string) {
  const days = Math.round((Date.now() - new Date(value).getTime()) / 86400000);
  const format = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (days < 1) return format.format(-Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 3600000)), "hour");
  if (days < 30) return format.format(-days, "day");
  return format.format(-Math.round(days / 30), "month");
}

// News: the latest finished tournaments and who won them.
function News() {
  const [items, setItems] = useState<TournamentRow[] | null>(null);
  const { t, locale, count } = useLang();

  useEffect(() => {
    const controller = new AbortController();
    fetchTournamentList(controller.signal).then((rows) => setItems(rows.slice(0, NEWS))).catch(() => { if (!controller.signal.aborted) setItems([]); });
    return () => controller.abort();
  }, []);

  return (
    <Card>
      {!items ? <Rows count={NEWS}>{(i) => <div className="gitv-row gitv-headline" key={i}><small>…</small></div>}</Rows>
        : !items.length ? <div className="gitv-row"><small>{t("No tournaments yet.", "Турниров пока нет.")}</small></div>
        : items.map((item) => (
            <Link to={`/tournament/${item.id}`} className="gitv-row gitv-row-link gitv-headline" key={item.id}>
              <span className="gitv-champion-text">
                <span>{item.winner
                  ? <><b>{item.winner.name}</b> {t("wins", "побеждает в")} {item.title}</>
                  : <>{item.title} {t("is over", "завершён")}</>}</span>
                <small className="gitv-champion-tournament">
                  {count(item.players, ["player", "players"], ["игрок", "игрока", "игроков"])} · {count(item.matches, ["match", "matches"], ["матч", "матча", "матчей"])}
                  {item.organizer && ` · ${t("by", "орг.")} ${item.organizer.name}`}
                </small>
              </span>
              <small className="push">{item.last_match ? ago(item.last_match, locale) : ""}</small>
            </Link>
          ))}
    </Card>
  );
}

// Matches announced for the viewer's local day (event organizers and admins add them on /schedule).
function TodaysMatches() {
  const [items, setItems] = useState<ScheduledMatch[] | null>(null);
  const { t, locale } = useLang();
  const user = useCurrentUser();
  const editor = user ? PLAYER_EDITOR_ROLES.includes(user.role) : false;

  useEffect(() => {
    const controller = new AbortController();
    const [start, end] = localDay();
    listScheduled(start, end, controller.signal).then(setItems).catch(() => { if (!controller.signal.aborted) setItems([]); });
    return () => controller.abort();
  }, []);

  const player = (p: ScheduledMatch["player1"]) =>
    p.id ? <Link to={`/player/${p.id}`} className="gitv-row-link">{p.name}</Link> : <span>{p.name}</span>;
  return (
    <Card><div className="gitv-card-title tinted">{t("Today's Matches", "Матчи дня")}</div>
      {!items ? <div className="gitv-row"><small>…</small></div>
        : !items.length ? <div className="gitv-row"><small>{t("No matches scheduled today.", "На сегодня матчей нет.")}</small></div>
        : items.map((m) => (
            <div className="gitv-row gitv-match" key={m.id}>
              <div className="gitv-matchline"><span><i className="gitv-line" />{player(m.player1)}</span>
                <b>{new Date(m.starts_at).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" })}</b></div>
              <div className="gitv-matchline"><span><i className="gitv-line" />{player(m.player2)}</span></div>
              <small className="gitv-champion-tournament">{m.tournament_title}</small>
            </div>
          ))}
      {editor && <div className="gitv-foot"><Link to="/schedule" className="gitv-row-link">{t("Schedule matches", "Назначить матчи")}</Link></div>}
    </Card>
  );
}

// El Clásico: the rivalry of the scene. Of the pairs who met most, the one with the most even record.
function ElClasicoCard() {
  const [data, setData] = useState<ElClasico | null | undefined>(undefined);
  const { t, date, count, locale } = useLang();

  useEffect(() => {
    const controller = new AbortController();
    fetchElClasico(controller.signal).then(setData).catch(() => { if (!controller.signal.aborted) setData(null); });
    return () => controller.abort();
  }, []);

  if (!data) {
    return <Card><div className="gitv-card-title">El Clásico</div><div className="gitv-row"><small>{data === undefined ? "…" : t("No rivalries yet.", "Противостояний пока нет.")}</small></div></Card>;
  }
  const [a, b] = data.players;
  const [wa, wb] = data.match_wins;
  const share = wa + wb ? (wa / (wa + wb)) * 100 : 50;
  const streak = data.streak ? (data.streak.player === a.id ? a.name : b.name) : null;
  return (
    <Card className="gitv-clasico">
      <div className="gitv-card-title tinted">El Clásico</div>
      <div className="gitv-clasico-score">
        <Link to={`/player/${a.id}`} className="gitv-row-link gitv-clasico-name">{a.name}</Link>
        <b>{wa}<small>–</small>{wb}</b>
        <Link to={`/player/${b.id}`} className="gitv-row-link gitv-clasico-name right">{b.name}</Link>
      </div>
      <div className="gitv-clasico-bar" aria-hidden><span style={{ width: `${share}%` }} /></div>
      <div className="gitv-clasico-meta">
        <small>{count(data.meetings, ["meeting", "meetings"], ["встреча", "встречи", "встреч"])} · {t("games", "игры")} {data.game_wins[0]}–{data.game_wins[1]}</small>
        <small>{count(data.tournaments, ["tournament", "tournaments"], ["турнир", "турнира", "турниров"])}{streak && data.streak ? ` · ${t("streak", "серия")}: ${streak} ×${data.streak.matches}` : ""}</small>
      </div>
      <div className="gitv-clasico-recent">
        {data.recent.map((m) => (
          <Link key={m.match_id} to={`/match/${m.match_id}`} className="gitv-clasico-meeting" title={`${m.tournament.title} · ${date(m.date)}`}>
            <span className={m.result === "W" ? "is-win" : m.result === "L" ? "is-loss" : ""}>{m.games_won}–{m.games_lost}</span>
            <small>{new Date(m.date).toLocaleDateString(locale, { day: "2-digit", month: "2-digit" })}</small>
          </Link>
        ))}
      </div>
      <div className="gitv-foot"><Link to={`/player/${a.id}/compare/${b.id}`} className="gitv-row-link">{t("Full head to head", "Все личные встречи")}</Link></div>
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

function HomeLayout() {
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
            <EventSection />
            <PopularCharactersCard />
            <div className="gitv-section-label">{t("News", "Новости")}</div>
            <News />
          </main>
          <aside>
            <TodaysMatches />
            <ElClasicoCard />
          </aside>
        </div>
      </div>
    </div>
  );
}

export function Welcome() {
  return <main className="gitv-page"><HomeLayout /></main>;
}
