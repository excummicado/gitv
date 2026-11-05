import { Fragment, useEffect, useState, type ReactNode } from "react";
import "./home.css";

import { Link } from "react-router";
import { Navbar } from "../components/Navbar";
import { Brand } from "../components/Brand";
import { fetchChampions, type Champion } from "../player/api";
import { fetchLiveMatches, fetchLiveTournaments, fetchMatches, fetchPopularCharacters, fetchTopPick, type LiveMatch, type LiveTournament, type MatchSummary, type PopularCharacters, type TopPick } from "../match/api";
import { LiveMatchRow } from "../match/LiveMatches";
import { EloBadge } from "../components/EloBadge";
import { excerpt, inLang, listArticles, NEWS_WRITER_ROLES, type Article } from "../articles/api";
import { NewsColumn } from "../news/NewsColumn";
import { fetchLiveStreams, listScheduled, localDay, streamMatches, type LiveStream, type ScheduledMatch, type StreamDay } from "../schedule/api";
import { TwitchPlayer } from "../components/TwitchPlayer";
import { fetchFeaturedTournaments, type FeaturedTournament } from "../tournament/api";
import { useCurrentUser } from "../auth/useCurrentUser";
import { PLAYER_EDITOR_ROLES } from "../auth/client";
import { useLang } from "../i18n";

const CHAMPIONS = 5;
const ARTICLES = 5;
const RECENT_MATCHES = 5;

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
      {/* Opens the tournament's Stats tab, where its picks and bans are. */}
      <Link to={`/tournament/${pick.tournament.id}?tab=stats`} className="gitv-promo gitv-top-pick">
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

// Banner of a tournament: one running now, else the latest finished, with its art from the site.
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
          {item.teams ? ` · ${count(item.teams, ["team", "teams"], ["команда", "команды", "команд"])}`
            : item.players > 0 && ` · ${count(item.players, ["player", "players"], ["игрок", "игрока", "игроков"])}`}
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

// The reader's pick among the running tournaments, kept in this browser (it may be unavailable).
const PICKED_EVENT = "gitv-home-event";

const STAGES: Record<string, [string, string]> = {
  final: ["Final", "Финал"], semifinal: ["Semifinal", "Полуфинал"], quarterfinal: ["Quarterfinal", "Четвертьфинал"],
  grand_final: ["Grand final", "Гранд-финал"], upper_final: ["Upper final", "Финал верхней сетки"],
  upper_semifinal: ["Upper semifinal", "Полуфинал верхней сетки"], lower_final: ["Lower final", "Финал нижней сетки"],
  third_place: ["Third place match", "Матч за 3-е место"],
};

// A stream match's stage from its bracket code (api/app/services/stream.py bracket_stage).
function stageLabel(code: string, t: (en: string, ru: string) => string) {
  if (STAGES[code]) return t(...STAGES[code]);
  const [kind, value] = code.split(":");
  switch (kind) {
    case "of": return t(`Round of ${Number(value) * 2}`, `1/${value} финала`);
    case "upper": return t(`Upper bracket, round ${value}`, `Верхняя сетка, раунд ${value}`);
    case "lower": return t(`Lower bracket, round ${value}`, `Нижняя сетка, раунд ${value}`);
    case "group": return value ? t(`Group ${value}`, `Группа ${value}`) : t("Groups", "Группы");
    case "round": return t(`Round ${value}`, `Раунд ${value}`);
    default: return code;
  }
}

function readPicked() {
  try { return localStorage.getItem(PICKED_EVENT); } catch { return null; }
}

function EventSection() {
  // Running tournaments, the ones weighing most in the Elo rating first (GET /api/v1/tournaments/featured/all); several can be picked from
  const [items, setItems] = useState<FeaturedTournament[] | null | undefined>(undefined);
  const [picked, setPicked] = useState<string | null>(null);
  const { t } = useLang();

  useEffect(() => {
    const controller = new AbortController();
    setPicked(readPicked());
    fetchFeaturedTournaments(controller.signal).then(setItems).catch(() => { if (!controller.signal.aborted) setItems(null); });
    return () => controller.abort();
  }, []);

  const pick = (id: string) => {
    setPicked(id);
    try { localStorage.setItem(PICKED_EVENT, id); } catch { /* not kept */ }
  };
  const item = items === undefined ? undefined : items?.find((i) => i.id === picked) ?? items?.[0] ?? null;

  return (
    <>
      {items && items.length > 1 && (
        <div className="gitv-event-picker" role="group" aria-label={t("Running tournaments", "Идущие турниры")}>
          {items.map((i) => (
            <button type="button" key={i.id} aria-pressed={i.id === item?.id} onClick={() => pick(i.id)} title={i.title}>
              {i.title}
            </button>
          ))}
        </div>
      )}
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

// The five most popular characters of this Abyss, or of the last one until a tournament has been played on this one.
// Bans count as much as picks: a character banned all the time is as much on players' minds as one picked all the time.
function PopularCharactersCard() {
  const [data, setData] = useState<PopularCharacters | null | undefined>(undefined);
  const { t, name, count } = useLang();

  useEffect(() => {
    const controller = new AbortController();
    fetchPopularCharacters(5, controller.signal).then(setData).catch(() => { if (!controller.signal.aborted) setData(null); });
    return () => controller.abort();
  }, []);

  if (!data) return <Card><div className="gitv-image gitv-feature">{data === undefined ? "" : t("No draft data yet", "Данных драфтов пока нет")}</div></Card>;
  const abyss = data.abyss;
  return (
    <Card>
      <div className="gitv-card-title gitv-popular-title">
        <span>{t("Most popular characters", "Самые популярные персонажи")}</span>
        <Link to={abyss ? `/abyss/${abyss.id}` : "/tournaments"} className="gitv-row-link">
          {!abyss ? t("All time", "За всё время")
            : abyss.current ? t(`Abyss ${abyss.version}`, `Бездна ${abyss.version}`)
            : t(`Previous Abyss ${abyss.version}`, `Прошлая бездна ${abyss.version}`)}
          {" · "}{count(data.tournaments, ["tournament", "tournaments"], ["турнир", "турнира", "турниров"])}
        </Link>
      </div>
      <div className="gitv-popular">
        {data.characters.map((c, i) => {
          const art = c.character.icon;
          return (
            // Opens the Characters page with this character's breakdown already open, from this Abyss on.
            <Link to={`/characters?open=${encodeURIComponent(c.character.id)}${abyss ? `&since=${abyss.starts_on}` : ""}`} className={`gitv-popular-item rarity-${c.character.rarity ?? 4}`} key={c.character.id}
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
            </Link>
          );
        })}
      </div>
      <div className="gitv-foot">{t(`Picks + bans over ${count(data.games, ["game", "games"], ["игра", "игры", "игр"])}; % is the share of games where the character was picked or banned.`,
        `Пики + баны за ${data.games} игр; % — доля игр, где персонажа пикали или банили.`)}</div>
    </Card>
  );
}

// Articles: written by writers, event organizers and admins (imported from a document on /articles); nothing is
// added automatically. The latest few, each opening its page.
function Articles() {
  const [items, setItems] = useState<Article[] | null>(null);
  const { t, date, lang } = useLang();
  const user = useCurrentUser();
  const writer = user ? NEWS_WRITER_ROLES.includes(user.role) : false;

  useEffect(() => {
    const controller = new AbortController();
    listArticles(ARTICLES, controller.signal).then(setItems).catch(() => { if (!controller.signal.aborted) setItems([]); });
    return () => controller.abort();
  }, []);

  return (
    <Card>
      {!items ? <div className="gitv-row"><small>…</small></div>
        : !items.length ? <div className="gitv-row"><small>{t("No articles yet.", "Статей пока нет.")}</small></div>
        : items.map((item) => (
            <Link to={`/articles/${item.id}`} className="gitv-row gitv-row-link gitv-headline" key={item.id}>
              <span className="gitv-champion-text">
                <span>{inLang(item, lang).title}</span>
                <small className="gitv-champion-tournament">{excerpt(inLang(item, lang).body, 120)}</small>
              </span>
              <small className="push">{date(item.created_at)}</small>
            </Link>
          ))}
      {(writer || (items && items.length > 0)) && (
        <div className="gitv-foot">
          <Link to="/articles" className="gitv-row-link">{writer ? t("All articles · add", "Все статьи · добавить") : t("All articles", "Все статьи")}</Link>
        </div>
      )}
    </Card>
  );
}

// The same two players, in either order
function samePair(a: [string, string], b: [string, string]) {
  const key = (p: [string, string]) => p.map((n) => n.toLowerCase()).sort().join("|");
  return key(a) === key(b);
}

// Matches for the viewer's local day: the ones on stream (each stream's, announced in its Telegram channel, with
// whether the stream and each match is on) first, then the ones event organizers and admins added on /schedule.
function TodaysMatches() {
  const [items, setItems] = useState<ScheduledMatch[] | null>(null);
  const [streams, setStreams] = useState<StreamDay[]>([]);
  // On air now, for the player under the matches
  const [onAir, setOnAir] = useState<LiveStream[]>([]);
  const { t, locale } = useLang();
  const user = useCurrentUser();
  const editor = user ? PLAYER_EDITOR_ROLES.includes(user.role) : false;

  useEffect(() => {
    const controller = new AbortController();
    const load = () => {
      const [start, end] = localDay();
      listScheduled(start, end, controller.signal).then(setItems).catch(() => { if (!controller.signal.aborted) setItems([]); });
      streamMatches(start, end, controller.signal).then(setStreams).catch(() => {});
      fetchLiveStreams(controller.signal).then(setOnAir).catch(() => {});
    };
    load();
    // The API reads the channels and Twitch every minute
    const timer = window.setInterval(load, 60 * 1000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, []);

  const time = (iso: string) => new Date(iso).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  const player = (p: ScheduledMatch["player1"], won = false) => (
    <>
      {p.id ? <Link to={`/player/${p.id}`} className={`gitv-row-link${won ? " gitv-winner" : ""}`}>{p.name}</Link>
        : <span className={won ? "gitv-winner" : undefined}>{p.name}</span>}
      {p.elo != null && <EloBadge rating={p.elo} rank={p.elo_rank} tier={p.elo_tier} active={p.elo_active} />}
      {!!p.members?.length && (
        <small className="gitv-team-members">
          {p.members.map((m, i) => (
            <Fragment key={i}>
              {i > 0 && " & "}
              {m.id ? <Link to={`/player/${m.id}`} className="gitv-row-link">{m.name}</Link> : m.name}
            </Fragment>
          ))}
        </small>
      )}
    </>
  );
  const onStream = streams.flatMap((s) => s.matches);
  const scheduled = (items ?? []).filter((m) => !onStream.some((s) => samePair([s.player1.name, s.player2.name], [m.player1.name, m.player2.name])));
  return (
    <Card><div className="gitv-card-title tinted">{t("Today's Matches", "Матчи дня")}</div>
      {streams.map((stream) => (
        <Fragment key={stream.url}>
          <div className="gitv-row gitv-stream">
            <a href={stream.url} target="_blank" rel="noreferrer" className="gitv-row-link gitv-stream-link" title={stream.title ?? undefined}>
              {stream.live && <b className="gitv-badge gitv-stream-live">{t("Live", "В эфире")}</b>}
              <span>{stream.name} · Twitch · {stream.url.replace(/^https?:\/\/(www\.)?(twitch\.tv\/)?/, "")}</span>
            </a>
            {stream.live && stream.title && <small className="gitv-stream-title">{stream.title}</small>}
            <small className="gitv-champion-tournament">
              {stream.started_at && `${stream.live ? t("since", "с") : t("starts", "начало")} ${time(stream.started_at)}`}
              {stream.viewers != null && ` · ${stream.viewers} ${t("watching", "зрителей")}`}
              {stream.casters && ` · ${t("casters", "ведут")} ${stream.casters}`}
            </small>
          </div>
          {stream.matches.map((m) => (
            <div className="gitv-row gitv-match" key={`${m.post_url}-${m.player1.name}-${m.player2.name}`}>
              <div className="gitv-matchline"><span>{player(m.player1, m.winner === 0)}</span>
                {m.live ? <b className="gitv-badge gitv-stream-live">{t("On air", "Идёт")}</b>
                  : m.finished_at ? <small>{t("finished", "сыгран")}</small>
                  : <small>{t("on stream", "на стриме")}</small>}</div>
              <div className="gitv-matchline"><span>{player(m.player2, m.winner === 1)}</span>
                {(m.live_at ?? m.starts_at) && <b>{time((m.live_at ?? m.starts_at)!)}</b>}</div>
              <small className="gitv-champion-tournament">
                {m.tournament_title}{m.stage && ` · ${stageLabel(m.stage, t)}`}{m.casters && m.casters !== stream.casters && ` · ${t("casters", "ведут")} ${m.casters}`}
              </small>
            </div>
          ))}
        </Fragment>
      ))}
      {!items ? <div className="gitv-row"><small>…</small></div>
        : !scheduled.length && !onStream.length ? <div className="gitv-row"><small>{t("No matches scheduled today.", "На сегодня матчей нет.")}</small></div>
        : scheduled.map((m) => (
            <div className="gitv-row gitv-match" key={m.id}>
              <div className="gitv-matchline"><span>{player(m.player1)}</span>
                <b>{new Date(m.starts_at).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" })}</b></div>
              <div className="gitv-matchline"><span>{player(m.player2)}</span></div>
              <small className="gitv-champion-tournament">{m.tournament_title}</small>
            </div>
          ))}
      {onAir.length > 0 && <TwitchPlayer streams={onAir} className="gitv-twitch" />}
      {editor && <div className="gitv-foot"><Link to="/schedule" className="gitv-row-link">{t("Schedule matches", "Назначить матчи")}</Link></div>}
    </Card>
  );
}

// The latest stored matches: who played, the score, the tournament and the day, each opening its page.
function RecentMatches() {
  const [items, setItems] = useState<MatchSummary[] | null>(null);
  const [failed, setFailed] = useState(false);
  const { t, date } = useLang();

  useEffect(() => {
    const controller = new AbortController();
    fetchMatches({ limit: RECENT_MATCHES, offset: 0 }, controller.signal)
      .then((page) => setItems(page.items))
      .catch(() => { if (!controller.signal.aborted) setFailed(true); });
    return () => controller.abort();
  }, []);

  return (
    <Card><div className="gitv-card-title">{t("Recent Matches", "Последние матчи")}</div>
      {failed ? <div className="gitv-row"><small>{t("Couldn't load the matches.", "Не удалось загрузить матчи.")}</small></div>
        : !items ? <div className="gitv-row"><small>…</small></div>
        : !items.length ? <div className="gitv-row"><small>{t("No matches yet.", "Матчей пока нет.")}</small></div>
        : items.map((m) => (
            <Link to={`/match/${m.id}`} className="gitv-row gitv-row-link gitv-recent-match" key={m.id}>
              <span className="gitv-recent-players">
                <span className={m.winner === 0 ? "gitv-winner" : undefined}>{m.sides[0]?.name}</span>
                <b>{m.sides[0]?.games_won}–{m.sides[1]?.games_won}</b>
                <span className={m.winner === 1 ? "gitv-winner" : undefined}>{m.sides[1]?.name}</span>
              </span>
              <span className="gitv-recent-meta">
                <small className="gitv-recent-tournament">{m.tournament}</small>
                <small className="gitv-date">{date(m.created_at)}</small>
              </span>
            </Link>
          ))}
      <div className="gitv-foot"><Link to="/matches" className="gitv-row-link">{t("All matches", "Все матчи")}</Link></div>
    </Card>
  );
}

function LiveTournaments() {
  const [items, setItems] = useState<LiveTournament[] | null>(null);
  // Their matches being played now, each game linking to its draft on the tournament site
  const [matches, setMatches] = useState<LiveMatch[]>([]);
  const { t, count } = useLang();

  useEffect(() => {
    const controller = new AbortController();
    const load = () => {
      fetchLiveTournaments(controller.signal).then(setItems).catch(() => { if (!controller.signal.aborted) setItems([]); });
      fetchLiveMatches(undefined, controller.signal).then(setMatches).catch(() => {});
    };
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
            <div key={item.id}>
              <div className="gitv-row">
                <span className="gitv-champion-text">
                  {item.imported_matches
                    ? <Link to={`/tournament/${item.id}`} className="gitv-row-link">{item.title}</Link>
                    : <span>{item.title}</span>}
                  <small className="gitv-champion-tournament">
                    {item.imported_matches ? count(item.imported_matches, ["match played", "matches played"], ["матч сыгран", "матча сыграно", "матчей сыграно"]) : t("No matches finished yet", "Матчей пока нет")}
                  </small>
                </span>
                <b className="gitv-badge push">{t("Live", "Идёт")}</b>
              </div>
              {matches.filter((m) => m.started && m.tournament_id === item.id).map((m) => <LiveMatchRow match={m} onlyLive showTournament key={m.id} />)}
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
        : !champions ? <Rows count={CHAMPIONS}>{(i) => <div className="gitv-row" key={i}><small>{i + 1}.</small><small>…</small></div>}</Rows>
        : champions.map((c, i) => (
            <div className="gitv-row gitv-champion" key={c.player.id}>
              <small>{i + 1}.</small>
              <span className="gitv-champion-text">
                <span className="gitv-champion-name">
                  <Link to={`/player/${c.player.id}`} className="gitv-row-link">{c.player.name}</Link>
                  {c.elo && <EloBadge rating={c.elo.rating} rank={c.elo.rank} tier={c.elo.tier} active={c.elo.active} />}
                </span>
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
            <div className="gitv-section-label">{t("Articles", "Статьи")}</div>
            <Articles />
          </main>
          <aside>
            <TodaysMatches />
            <RecentMatches />
            <NewsColumn />
          </aside>
        </div>
      </div>
    </div>
  );
}

export function Welcome() {
  return <main className="gitv-page"><HomeLayout /></main>;
}
