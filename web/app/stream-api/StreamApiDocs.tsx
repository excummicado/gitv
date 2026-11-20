import { useState, type ReactNode } from "react";
import { Brand } from "../components/Brand";
import { Navbar } from "../components/Navbar";
import { useLang } from "../i18n";
import { EXAMPLES } from "./examples";
import "./stream-api-docs.css";

// The stream API's documentation, for the people a super admin gave a key (profile page). Keep it in step with
// api/app/routers/stream_api.py; the example answers are real ones (examples.ts).

const BASE = "https://gitv.xyz/api/v1/stream-api";

type Pair = [en: string, ru: string];
type Param = { name: string; where: "path" | "query"; type: string; def?: string; text: Pair };
type Field = [name: string, en: string, ru: string];
type Endpoint = {
  id: string;
  path: string;
  title: Pair;
  about: Pair;
  params: Param[];
  example: string; // the request in the example, after BASE
  response: keyof typeof EXAMPLES;
  fields?: Field[];
};

const PLAYER: Param = {
  name: "player", where: "path", type: "string",
  text: ["The player's id on the site or any nickname they're known under (case and punctuation don't matter).",
    "id игрока на сайте или любой ник, под которым он известен (регистр и знаки не важны)."],
};
const P1: Param = { ...PLAYER, name: "p1", text: ["First player: id or nickname. Numbers in pairs come from their side first.", "Первый игрок: id или ник. В парах чисел его значение идёт первым."] };
const P2: Param = { ...PLAYER, name: "p2", text: ["Second player: id or nickname.", "Второй игрок: id или ник."] };
const limit = (def: number, max = 100): Param => ({
  name: "limit", where: "query", type: `1–${max}`, def: String(def), text: ["How many rows to return.", "Сколько строк вернуть."],
});

const GROUPS: { id: string; title: Pair; intro: Pair; endpoints: Endpoint[] }[] = [
  {
    id: "elo",
    title: ["Elo", "Эло"],
    intro: ["The rating the site ranks players by: every decided match moves it, majors the most.",
      "Рейтинг, по которому сайт ранжирует игроков: его двигает каждый сыгранный матч, мейджоры — сильнее всего."],
    endpoints: [
      {
        id: "elo-now", path: "/players/{player}/elo",
        title: ["Elo now", "Текущий Эло"],
        about: ["Rating, peak, place among active players and among everyone, colour tier and the last match's change.",
          "Рейтинг, пик, место среди активных и среди всех, цветной тир и изменение за последний матч."],
        params: [PLAYER], example: "/players/Dzen/elo", response: "elo",
        fields: [
          ["rank", "Place among active players (a match in the last six months); null when inactive.", "Место среди активных (матч за последние полгода); null, если неактивен."],
          ["rank_all", "Place among everyone, inactive players included.", "Место среди всех, включая неактивных."],
          ["tier", "gold, silver, bronze, top10, top30 or null — the colour the site paints the nickname.", "gold, silver, bronze, top10, top30 или null — цвет ника на сайте."],
          ["last_change", "What the latest rated match did to the rating.", "Насколько изменил рейтинг последний матч."],
        ],
      },
      {
        id: "elo-history", path: "/players/{player}/elo/history",
        title: ["Elo changes", "Изменение Эло"],
        about: ["The total change over the last 7, 30 and 90 days, and match by match, newest first, with why it moved that much.",
          "Суммарное изменение за 7, 30 и 90 дней и по матчам, от новых к старым, с тем, почему рейтинг сдвинулся именно так."],
        params: [PLAYER, limit(20)], example: "/players/Dzen/elo/history?limit=2", response: "eloHistory",
        fields: [
          ["change.last_N_days", "Sum of the changes over that many days.", "Сумма изменений за столько дней."],
          ["history[].expected", "The player's chance to win that match by Elo, %, before it.", "Шанс игрока выиграть этот матч по Эло, %, до матча."],
          ["history[].opponent", "id is null for an opponent not on the site (a bracket name).", "id = null у соперника, которого нет на сайте (имя из сетки)."],
        ],
      },
      {
        id: "leaderboard", path: "/leaderboard",
        title: ["Elo leaderboard", "Топ по Эло"],
        about: ["The top of the ranking: active players only, as on the site.", "Верх рейтинга: только активные игроки, как на сайте."],
        params: [limit(10)], example: "/leaderboard?limit=3", response: "leaderboard",
      },
    ],
  },
  {
    id: "stats",
    title: ["Statistics", "Статистика"],
    intro: ["What the site counts for a player: over every tournament or a recent period.",
      "Всё, что сайт считает по игроку: за все турниры или за недавний период."],
    endpoints: [
      {
        id: "stats-all", path: "/players/{player}/stats",
        title: ["Overall statistics", "Общая статистика"],
        about: ["Tournaments, titles and top places, match and game record, streaks, form, times, first/second pick, favourite character and the one banned against them most.",
          "Турниры, титулы и призовые места, матчи и игры, серии, форма, время, первый/второй пик, любимый персонаж и тот, кого против игрока банят чаще всего."],
        params: [PLAYER], example: "/players/Dzen/stats", response: "stats",
        fields: [
          ["form", "Results of the last ten games, newest first: W won, L lost, D draw.", "Результаты последних десяти игр, от новой к старой: W победа, L поражение, D ничья."],
          ["current_winstreak", "Games won in a row up to now.", "Игр выиграно подряд на данный момент."],
          ["finals / top4", "Times in the final (1st or 2nd place) / in the top four.", "Сколько раз в финале (1–2 место) / в топ-4."],
          ["times", "Clear times in seconds; only games with a result, technical ones aside.", "Время прохождения в секундах; только игры с результатом, без технических."],
          ["first_pick / second_pick", "Record in games where the player picked first / second.", "Результаты в играх, где игрок пикал первым / вторым."],
          ["major_titles", "Major tournaments won, newest first.", "Выигранные мейджоры, от новых к старым."],
        ],
      },
      {
        id: "stats-recent", path: "/players/{player}/stats/recent",
        title: ["Last three months", "Статистика за 3 месяца"],
        about: ["The same numbers over the tournaments that started in the last 90 days (or as many as you ask). A player who played none gets zeros, not an error.",
          "Те же числа по турнирам, начавшимся за последние 90 дней (или сколько попросите). Если игрок ничего не играл — нули, а не ошибка."],
        params: [PLAYER, { name: "days", where: "query", type: "1–730", def: "90", text: ["Length of the period in days.", "Длина периода в днях."] }],
        example: "/players/Dzen/stats/recent", response: "recent",
        fields: [["period", "days and since (the first day counted).", "days и since (первый учтённый день)."]],
      },
      {
        id: "characters", path: "/players/{player}/characters",
        title: ["Characters", "Статистика по персонажам"],
        about: ["Every character the player picked, most games first: pick rate, record, times, highest constellation, how often it was banned against them. Plus the five characters opponents ban against the player most.",
          "Все персонажи, которых брал игрок, по числу игр: доля пиков, результаты, время, максимальное созвездие, сколько раз его банили против игрока. И пятёрка персонажей, которых соперники банят против игрока чаще всего."],
        params: [PLAYER, limit(20),
          { name: "min_games", where: "query", type: "1–100", def: "1", text: ["Leave out characters with fewer games.", "Не показывать персонажей с меньшим числом игр."] },
          { name: "days", where: "query", type: "1–730", text: ["Only tournaments of the last this many days.", "Только турниры за последние столько дней."] }],
        example: "/players/Dzen/characters?limit=2", response: "characters",
        fields: [
          ["pick_rate", "% of the player's games with this character.", "% игр игрока с этим персонажем."],
          ["max_constellation", "Highest constellation (C0–C6) they played it at.", "Максимальное созвездие (C0–C6), на котором играл."],
          ["character.icon", "Picture URL, ready for an <img>.", "Ссылка на иконку, готовая для <img>."],
        ],
      },
      {
        id: "matches", path: "/players/{player}/matches",
        title: ["Latest matches", "Последние матчи"],
        about: ["Newest first: opponent, score, result and what each match did to the Elo.", "От новых к старым: соперник, счёт, результат и изменение Эло за матч."],
        params: [PLAYER, limit(10)], example: "/players/Dzen/matches?limit=2", response: "matches",
        fields: [["score", "[games won, games lost].", "[выиграно игр, проиграно игр]."]],
      },
      {
        id: "tournaments", path: "/players/{player}/tournaments",
        title: ["Tournament results", "Результаты на турнирах"],
        about: ["Tournaments played, newest first: place (or the range shared, e.g. 9–16), matches won and lost, qualifier outcome.",
          "Сыгранные турниры, от новых к старым: место (или диапазон, например 9–16), выигранные и проигранные матчи, итог квалификации."],
        params: [PLAYER, limit(10)], example: "/players/Dzen/tournaments?limit=2", response: "tournaments",
        fields: [
          ["kind", "bracket, groups or qualifier.", "bracket (сетка), groups (группы) или qualifier (квалификация)."],
          ["qualification", "Qualifiers only: passed, failed or pending.", "Только квалификации: passed, failed или pending."],
        ],
      },
      {
        id: "rivals", path: "/players/{player}/rivals",
        title: ["Rivals", "Главные соперники"],
        about: ["Who the player met most, with the record against each.", "С кем игрок встречался чаще всего и с каким счётом."],
        params: [PLAYER, limit(5, 20)], example: "/players/Dzen/rivals?limit=2", response: "rivals",
      },
      {
        id: "profile", path: "/players/{player}/profile",
        title: ["Player in short", "Игрок коротко"],
        about: ["For a name plate: name, other nicknames, link to their page, Elo and place, number of major titles, first and last game.",
          "Для плашки с именем: ник, другие ники, ссылка на страницу, Эло и место, число титулов мейджоров, первая и последняя игра."],
        params: [PLAYER], example: "/players/Dzen/profile", response: "profile",
      },
    ],
  },
  {
    id: "h2h",
    title: ["Head to head", "Личные встречи"],
    intro: ["Two players against each other. Numbers in pairs ([1, 2]) are p1's first.", "Два игрока друг против друга. В парах чисел ([1, 2]) первым идёт p1."],
    endpoints: [
      {
        id: "h2h-stats", path: "/head-to-head/{p1}/{p2}",
        title: ["Head-to-head statistics", "Статистика в личных встречах"],
        about: ["Record, who's on a streak against the other, first and last meeting, and for each side: games won, times, first/second pick, characters picked and banned against them in these matches.",
          "Счёт, у кого серия, первая и последняя встреча, и для каждого: выигранные игры, время, первый/второй пик, персонажи, которых брал и которых против него банили в этих матчах."],
        params: [P1, P2], example: "/head-to-head/Dzen/Rer", response: "h2h",
        fields: [
          ["streak", "Who won the latest meetings in a row, and how many; null without a winner yet.", "Кто выиграл последние встречи подряд и сколько; null, если победителя ещё не было."],
          ["sides", "[p1, p2]; a side is null when they never met.", "[p1, p2]; null, если не встречались."],
        ],
      },
      {
        id: "h2h-matches", path: "/head-to-head/{p1}/{p2}/matches",
        title: ["Head-to-head history", "История личных встреч"],
        about: ["Every meeting, newest first, the score from p1's side.", "Все встречи, от новых к старым, счёт со стороны p1."],
        params: [P1, P2, limit(20)], example: "/head-to-head/Dzen/Rer/matches?limit=2", response: "h2hMatches",
        fields: [["result", "From p1's side: W, L, D or — (no result).", "Со стороны p1: W, L, D или — (нет результата)."]],
      },
      {
        id: "prediction", path: "/head-to-head/{p1}/{p2}/prediction",
        title: ["Win prediction", "Прогноз на матч"],
        about: ["Each player's chance to win, %, by Elo alone — the same formula the ratings use. Good for a pre-match graphic.",
          "Шанс каждого на победу, %, только по Эло — по той же формуле, что и сам рейтинг. Для заставки перед матчем."],
        params: [P1, P2], example: "/head-to-head/Dzen/Rer/prediction", response: "prediction",
      },
    ],
  },
  {
    id: "search",
    title: ["Finding players", "Поиск игроков"],
    intro: ["Nicknames work everywhere, but an id never changes: find it once and keep it.", "Ники работают везде, но id не меняется никогда: найдите его один раз и используйте."],
    endpoints: [
      {
        id: "search-players", path: "/players",
        title: ["Search", "Поиск"],
        about: ["Players whose nickname contains q, the exact name first, then by matches played. Up to ten.",
          "Игроки, в нике которых есть q: сначала точное совпадение, потом по числу матчей. До десяти."],
        params: [{ name: "q", where: "query", type: "string", text: ["Part of a nickname.", "Часть ника."] }],
        example: "/players?q=dze", response: "search",
      },
    ],
  },
];

const ERRORS: [string, Pair][] = [
  ["401", ["No key, a wrong one or a revoked one.", "Нет ключа, ключ неверный или отозван."]],
  ["404", ["No such player, or no rated matches for an Elo request.", "Нет такого игрока или у него нет матчей с рейтингом (для запросов Эло)."]],
  ["422", ["A parameter out of range, or the same player twice in a pair.", "Параметр вне допустимых значений или один и тот же игрок дважды."]],
  ["429", ["Over 600 requests a minute on one key; Retry-After says when to come back.", "Больше 600 запросов в минуту с одного ключа; Retry-After скажет, когда можно снова."]],
];

const OVERLAY = `<!-- OBS → Source → Browser → Local file. Shows the Elo and form, refreshes every 30 s. -->
<div id="card" style="font: 700 28px sans-serif; color: #fff; text-shadow: 0 2px 6px #000"></div>
<script>
  const KEY = "gitv_…";        // your key
  const PLAYER = "Dzen";       // id or nickname
  const API = "${BASE}";

  async function update() {
    const get = (path) => fetch(API + path, { headers: { "X-API-Key": KEY } }).then((r) => r.json());
    const [elo, stats] = await Promise.all([get(\`/players/\${PLAYER}/elo\`), get(\`/players/\${PLAYER}/stats\`)]);
    document.getElementById("card").textContent =
      \`\${elo.player.name} · Elo \${elo.rating} (#\${elo.rank}) · \${stats.match_winrate}% · \${stats.form}\`;
  }
  update();
  setInterval(update, 30000);
</script>`;

function Copy({ text }: { text: string }) {
  const { t } = useLang();
  const [done, setDone] = useState(false);
  return (
    <button type="button" className="sad-copy" onClick={() => navigator.clipboard?.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); }).catch(() => {})}>
      {done ? t("Copied", "Скопировано") : t("Copy", "Копировать")}
    </button>
  );
}

function Code({ children, label }: { children: string; label?: string }) {
  return (
    <div className="sad-code">
      <div className="sad-code-bar"><span>{label}</span><Copy text={children} /></div>
      <pre><code>{children}</code></pre>
    </div>
  );
}

function Path({ path }: { path: string }) {
  // {placeholders} stand out from the fixed part of the address
  return <code className="sad-path">{path.split(/(\{[^}]+\})/).map((part, i) => (part.startsWith("{") ? <em key={i}>{part}</em> : part))}</code>;
}

function EndpointCard({ e }: { e: Endpoint }) {
  const { t } = useLang();
  const [tab, setTab] = useState<"curl" | "url">("curl");
  const curl = `curl -H "X-API-Key: $GITV_KEY" "${BASE}${e.example}"`;
  const url = `${BASE}${e.example}${e.example.includes("?") ? "&" : "?"}key=gitv_…`;
  return (
    <section className="sad-endpoint" id={e.id}>
      <header className="sad-endpoint-head">
        <span className="sad-method">GET</span>
        <Path path={e.path} />
        <a className="sad-anchor" href={`#${e.id}`} aria-label={t("Link to this section", "Ссылка на раздел")}>#</a>
      </header>
      <h3 className="sad-endpoint-title">{t(...e.title)}</h3>
      <p className="sad-text">{t(...e.about)}</p>
      {e.params.length > 0 && (
        <table className="sad-table">
          <thead><tr><th>{t("Parameter", "Параметр")}</th><th>{t("Where", "Где")}</th><th>{t("Values", "Значения")}</th><th>{t("Meaning", "Что это")}</th></tr></thead>
          <tbody>
            {e.params.map((p) => (
              <tr key={p.name}>
                <td><code>{p.name}</code>{p.where === "path" && <span className="sad-required">{t("required", "обязателен")}</span>}</td>
                <td>{p.where === "path" ? t("path", "путь") : "query"}</td>
                <td><code>{p.type}</code>{p.def && <div className="sad-default">{t("default", "по умолчанию")} {p.def}</div>}</td>
                <td>{t(...p.text)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="sad-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "curl"} className={tab === "curl" ? "is-active" : ""} onClick={() => setTab("curl")}>curl</button>
        <button type="button" role="tab" aria-selected={tab === "url"} className={tab === "url" ? "is-active" : ""} onClick={() => setTab("url")}>{t("Link (OBS)", "Ссылка (OBS)")}</button>
      </div>
      <Code label={t("Request", "Запрос")}>{tab === "curl" ? curl : url}</Code>
      <Code label={t("Response (lists cut to two rows)", "Ответ (списки сокращены до двух строк)")}>{JSON.stringify(EXAMPLES[e.response], null, 2)}</Code>
      {e.fields && (
        <dl className="sad-fields">
          {e.fields.map(([name, en, ru]) => (
            <div key={name}><dt><code>{name}</code></dt><dd>{t(en, ru)}</dd></div>
          ))}
        </dl>
      )}
    </section>
  );
}

function Block({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className="sad-block" id={id}>
      <h2 className="sad-h2">{title}</h2>
      {children}
    </section>
  );
}

export function StreamApiDocs() {
  const { t } = useLang();
  const count = GROUPS.reduce((n, g) => n + g.endpoints.length, 0);
  return (
    <main className="gitv-page">
      <div className="gitv-frame player-frame">
        <Navbar />
        <div className="gitv-content">
          <Brand />
          <div className="sad">
            <nav className="sad-toc" aria-label={t("Contents", "Содержание")}>
              <div className="sad-toc-title">{t("Contents", "Содержание")}</div>
              <a href="#start">{t("Quick start", "Быстрый старт")}</a>
              <a href="#auth">{t("Key", "Ключ")}</a>
              <a href="#rules">{t("Conventions", "Соглашения")}</a>
              {GROUPS.map((g) => (
                <div key={g.id} className="sad-toc-group">
                  <a href={`#${g.id}`} className="sad-toc-head">{t(...g.title)}</a>
                  {g.endpoints.map((e) => <a key={e.id} href={`#${e.id}`} className="sad-toc-sub">{t(...e.title)}</a>)}
                </div>
              ))}
              <a href="#errors">{t("Errors", "Ошибки")}</a>
              <a href="#overlay">{t("Overlay example", "Пример оверлея")}</a>
            </nav>

            <article className="sad-body">
              <header className="sad-hero player-box">
                <div className="sad-kicker">GITV · API</div>
                <h1 className="sad-h1">{t("Stream API", "API для стримов")}</h1>
                <p className="sad-lead">
                  {t("Players' Elo, statistics, characters and head-to-heads straight from GITV, for overlays, bots and graphics on tournament streams.",
                    "Эло игроков, статистика, персонажи и личные встречи прямо с GITV — для оверлеев, ботов и графики на стримах турниров.")}
                </p>
                <div className="sad-badges">
                  <span><b>{count}</b> {t("endpoints", "эндпоинтов")}</span>
                  <span><b>JSON</b> · GET</span>
                  <span><b>600</b> {t("requests / min", "запросов / мин")}</span>
                  <span><b>CORS</b> {t("open", "открыт")}</span>
                </div>
              </header>

              <Block id="start" title={t("Quick start", "Быстрый старт")}>
                <ol className="sad-steps">
                  <li>{t("Get a key from the GITV super admin. It's shown once — save it right away.", "Получите ключ у супер-админа GITV. Он показывается один раз — сразу сохраните его.")}</li>
                  <li>{t("Send it with every request in the X-API-Key header.", "Передавайте его в каждом запросе в заголовке X-API-Key.")}</li>
                  <li>{t("Name players by nickname or id — that's it.", "Называйте игроков ником или id — и всё.")}</li>
                </ol>
                <Code label={t("First request", "Первый запрос")}>{`curl -H "X-API-Key: gitv_…" "${BASE}/players/Dzen/elo"`}</Code>
              </Block>

              <Block id="auth" title={t("Key", "Ключ")}>
                <p className="sad-text">
                  {t("Every request needs a key. A header is the safer way; where headers can't be set (an OBS browser source pointed at a link), add ?key= to the address instead. Keys are issued and revoked only by the GITV super admin; a revoked key stops working at once.",
                    "Каждому запросу нужен ключ. Заголовок — надёжнее; где заголовки не задать (браузерный источник OBS по ссылке), добавьте ?key= в адрес. Ключи выдаёт и отзывает только супер-админ GITV; отозванный ключ перестаёт работать сразу.")}
                </p>
                <div className="sad-two">
                  <Code label={t("Header", "Заголовок")}>{"X-API-Key: gitv_…"}</Code>
                  <Code label={t("In the link", "В ссылке")}>{`${BASE}/leaderboard?key=gitv_…`}</Code>
                </div>
                <p className="sad-note">{t("Keep the key off screen and out of public code: anyone who has it can use it on your behalf.", "Не показывайте ключ на экране и не выкладывайте в открытый код: им сможет пользоваться любой, у кого он есть.")}</p>
              </Block>

              <Block id="rules" title={t("Conventions", "Соглашения")}>
                <ul className="sad-list">
                  <li><b>{t("Address", "Адрес")}</b> — <code>{BASE}</code></li>
                  <li><b>{t("Players", "Игроки")}</b> — {t("by id or any nickname they played under; a nickname two players share isn't accepted — use the id.", "по id или любому нику, под которым играл; ник, который делят двое, не принимается — используйте id.")}</li>
                  <li><b>{t("Times", "Время")}</b> — {t("in seconds (300.5 = 5:00.5).", "в секундах (300.5 = 5:00.5).")}</li>
                  <li><b>{t("Winrates and chances", "Винрейты и шансы")}</b> — {t("percent, 0–100; null when there's nothing to count.", "в процентах, 0–100; null, если считать не из чего.")}</li>
                  <li><b>{t("Dates", "Даты")}</b> — {t("ISO 8601 with a time zone.", "ISO 8601 с часовым поясом.")}</li>
                  <li><b>{t("Freshness", "Свежесть")}</b> — {t("numbers follow the site: a finished match counts within minutes. Answers are never cached, so ask every 15–60 s at most.", "числа такие же, как на сайте: сыгранный матч учитывается за минуты. Ответы не кэшируются, так что опрашивайте не чаще раза в 15–60 с.")}</li>
                </ul>
              </Block>

              {GROUPS.map((g) => (
                <Block key={g.id} id={g.id} title={t(...g.title)}>
                  <p className="sad-text sad-group-intro">{t(...g.intro)}</p>
                  {g.endpoints.map((e) => <EndpointCard key={e.id} e={e} />)}
                </Block>
              ))}

              <Block id="errors" title={t("Errors", "Ошибки")}>
                <p className="sad-text">{t("An error comes as JSON with a detail message, in Russian when the request asks for it (Accept-Language: ru).", "Ошибка приходит JSON-ом с сообщением в detail — по-русски, если запрос просит (Accept-Language: ru).")}</p>
                <table className="sad-table">
                  <tbody>
                    {ERRORS.map(([code, text]) => <tr key={code}><td><span className="sad-status">{code}</span></td><td>{t(...text)}</td></tr>)}
                  </tbody>
                </table>
                <Code label="401">{`{ "detail": "Invalid or revoked API key." }`}</Code>
              </Block>

              <Block id="overlay" title={t("Overlay example", "Пример оверлея")}>
                <p className="sad-text">{t("A whole overlay in one file: save it as .html, put in your key and add it to OBS as a browser source.", "Целый оверлей в одном файле: сохраните как .html, впишите ключ и добавьте в OBS как браузерный источник.")}</p>
                <Code label="overlay.html">{OVERLAY}</Code>
              </Block>
            </article>
          </div>
        </div>
      </div>
    </main>
  );
}
