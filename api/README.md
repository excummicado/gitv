# API backend

FastAPI backend for the React Router app, with SQLModel for database access.
The database is SQLite (`gitv.db`) only for the time being; set `DATABASE_URL`
to switch to another database.

Discord is the only way to sign in; there are no passwords. On the first
Discord sign-in the user chooses a nickname, and that creates the account.

## Structure

```text
api/
├── app/
│   ├── config.py        # Settings from environment variables and .env
│   ├── database.py      # Engine, session dependency
│   ├── models.py        # User table and API models
│   ├── security.py      # JWT access tokens
│   ├── dependencies.py  # Current user from the Bearer token
│   ├── rate_limit.py    # Request limits for sign-in and member writes
│   ├── messages.py      # Russian versions of the API's error messages
│   ├── routers/         # health, users (/users/me), discord (sign-in), matches, players, ...
│   ├── services/        # Business logic; stats/ is the player and tournament statistics
│   └── main.py          # FastAPI app and ASGI entry point
├── migrations/          # Alembic: every change to the database's tables
├── tests/               # pytest; an in-memory database, never gitv.db
├── .env.example         # Copy to .env and fill in
├── requirements.txt
└── requirements-dev.txt # + pytest
```

## Run

From inside `api/`:

```bash
cp .env.example .env   # then fill in SECRET_KEY and the Discord keys
venv/bin/pip install -r requirements.txt
venv/bin/alembic upgrade head
venv/bin/fastapi dev app/main.py
```

Tests: `venv/bin/pip install -r requirements-dev.txt`, then `venv/bin/python -m pytest`.

## Migrations

Tables are made and changed only by Alembic, never when the API or a command starts. Run
`venv/bin/alembic upgrade head` on a new database and after pulling new migrations; without it the API and the
commands fail on missing tables or columns.

After changing `app/models.py`:

```bash
venv/bin/alembic revision --autogenerate -m "what changed"   # read the file it writes: a rename comes out as drop + add
venv/bin/alembic upgrade head
venv/bin/alembic check                                       # the database matches the models
```

Commit the migration with the model. A database made before migrations has its tables already: it's marked with the
baseline (`venv/bin/alembic stamp f48c93de158c`) and then upgraded as usual.

Error messages come in the site's language: the API reads the `gitv-lang` cookie (or `Accept-Language`) and
answers in Russian from `app/messages.py`. Sign-in, sign-up, news imports, matches of the day
and nickname changes are rate limited per client address or member (`app/rate_limit.py`, in memory; a
blocked request gets 429 with `Retry-After`). Behind a reverse proxy set `TRUST_FORWARDED_FOR=true` so
clients are told apart by `X-Forwarded-For`.

Register `http://localhost:5173/api/v1/auth/discord/callback` as a redirect in
the Discord Developer Portal (your app > OAuth2 > Redirects).

## Endpoints

- `GET /api/v1/health`
- `GET /api/v1/auth/discord/login` — redirects to Discord (`prompt=none` skips Discord's approval screen for returning members)
- `GET /api/v1/auth/discord/callback` — Discord redirects back here; issues the GITV token, or a 10-minute sign-up token for a new user
- `POST /api/v1/auth/discord/register` — sign-up token + chosen nickname → creates the account, returns the GITV token
- `GET /api/v1/users/me` — the signed-in user (Bearer token)

## Roles

| Role | Signed in for | Can |
| --- | --- | --- |
| `user` (member) | 30 days | Edit their own nickname |
| `writer` | 30 days | Nothing extra yet (meant for news) |
| `event_organizer` | 30 days | Nothing extra yet (meant for tournaments and events) |
| `admin` | 60 minutes | Ban and unban members, writers and event organizers; switch people between those three roles |
| `super_admin` | 60 minutes | Everything an admin can, plus ban admins and give or take away admin |

Staff tokens are short because they are worth more if stolen. A token is tied to
the role it was issued for, so after any role change the user signs in again.
A banned user is signed out at once and can't sign in with Discord until unbanned.
Nobody can ban themselves or a super admin.

Staff endpoints (also available as boxes on the profile page):

- `PUT /api/v1/admin/users/{nickname}/role` with `{"role": "user" | "writer" | "event_organizer" | "admin"}`: admins can set `user`, `writer` or `event_organizer` on anyone who isn't staff; super admins can also set or remove `admin`. Nobody can change their own role or a super admin's.
- `POST /api/v1/admin/bans` with `{"nickname": "…"}` and `DELETE /api/v1/admin/bans/{nickname}`: admin and super admin

Super admins can only be set from the command line, inside `api/`:

```bash
venv/bin/python -m app.cli set-role <nickname> super_admin
venv/bin/python -m app.cli set-role <nickname> user   # also removes super admin
```

## Importing matches from the tournament site

Downloads every match from the URLs in a text file (one matches API URL per line, `#` for comments),
with `limit=100000000000`, and stores only **finished** matches (every draft `FINISHED`) in the database.
Running it again replaces matches that are already there, so it never duplicates them.

```bash
venv/bin/python -m app.cli import-matches ../references/tournament_urls_limit.txt
```

The matches list is public, so no cookie is needed. Matches come 100 per request (the site's cap) until
the list's `count` is reached. If the site locks the list again, pass a signed-in browser's `Cookie` header
(DevTools > Network > a request to the API > Request Headers) through the environment:
`ABYSS_COOKIE="$(pbpaste)" venv/bin/python -m app.cli import-matches ...`; it is never saved. Saved API responses
can be imported without downloading: `venv/bin/python -m app.cli import-matches --json page1.json page2.json`.

Tables:

| Table | One row per | Main columns |
| --- | --- | --- |
| `tournament` | tournament | `id`, `title` |
| `match` | match | `tournament_id`, `created_at`, `system_title`, `mode`, `free_restarts`, `paid_restarts`, `raw` (the full API JSON) |
| `matchdraft` | draft (game) in a match | `match_id`, `game_no`, `status`, `first_pick_slot` |
| `matchplayer` | player in a draft | `draft_id`, `match_id`, `slot`, `user_id`, `full_name`, `restarts`, `clear_time`, `clear_points`, `prebans` |
| `matchpick` | character + weapon in a player's team (stored as `agent_*` / `engine_*`, the site's own names) | `player_id`, `draft_id`, `position`, `agent_id`, `agent_mindscape`, `engine_id`, `engine_refinement` |

Every game of one player, in order:

```sql
SELECT m.created_at, t.title, d.game_no, p.clear_time, p.restarts
FROM matchplayer p
JOIN matchdraft d ON d.id = p.draft_id
JOIN match m ON m.id = p.match_id
JOIN tournament t ON t.id = m.tournament_id
WHERE p.full_name = 'DzeN'
ORDER BY m.created_at, d.game_no;
```

### Exporting to Excel

```bash
venv/bin/python -m app.cli export-xlsx matches.xlsx
```

One workbook, a sheet per view: players (winrates, times, restarts, favourite characters), every game of
every player in order, games, matches, head-to-head, each player's characters, characters, weapons, every
pick, and tournaments. A game goes to the lower time after restart penalties (restarts beyond
`free_restarts` cost `paid_restarts[k]` seconds), a match to the lower total; raw times are there too.

### Keeping up with the site

```bash
venv/bin/python -m app.cli sync                 # once
venv/bin/python -m app.cli sync --watch 3600    # every hour until Ctrl+C
```

Reads the site's public list of finished tournaments and imports the ones that aren't in the database yet,
then fetches their draft links, drafts and details, so no URLs file is needed. Tournaments in
`ignoredtournament` are skipped; `delete-tournaments` adds the ones it deletes. Matches already in the
database are kept as they are, with their draft links and drafts.

On a server, set `SYNC_INTERVAL=3600` in `.env`: the API then syncs in the background by itself (0 = off;
run a single worker). A lock file (`.sync.lock`) keeps two syncs from running at once, so a manual `sync`
during a background one is skipped.

With background syncing on, the API also polls running tournaments every five minutes (`LIVE_INTERVAL`):
it asks for the matches of each tournament on the running list and imports the ones that finished since, with
their draft links, drafts and rosters, so statistics and the tournament page follow a tournament while it's
played. A tournament gets its details from the running list when its first match comes in, marked not
finished; the hourly sync imports its last matches, details and Challonge bracket once it ends. The poll
shares the sync lock (it's skipped while a sync runs) and keeps its time in `.sync-state.json`.

While a tournament runs it has no places, winner or champion anywhere (standings, the tournament list, news,
players' pages). The live poll also reads its Challonge bracket (the participants list only the first time),
and once the final there has a winner the tournament counts as finished: its places and winner show, it leaves
the home page's running tournaments and the banner moves on to it as the latest. A tournament without a
Challonge bracket stays live until the site marks it finished (the hourly sync).

The live poll also keeps the running tournaments' unfinished matches, not started ones included, in
`livematch`, apart from `match` so no statistic counts them: the two players and each game's status and
spectator link on the site (asked for once per match). `GET /api/v1/matches/live-matches?tournament=` lists
them, those being drafted or played first; the tournament page shows them while it runs and the home page's
running tournaments show the games under way, each opening its draft on abyss.darte.gg. A match leaves
`livematch` once it's finished (it's in `match` then) or its tournament stops running.

Apart from the live poll's match lists (and the links and drafts of the matches it brings), nothing
automatic asks the site for anything more often than once an hour (`MIN_INTERVAL`): lower
`SYNC_INTERVAL` or `--watch` values are raised to 3600, the time of the last request is kept in
`.sync-state.json` so API restarts don't reset it, and a failed request also waits an hour. The home page's
running tournaments (`GET /api/v1/matches/live-tournaments`) come from the site's list cached the same way,
so they can be up to an hour old, and so can the live poll's idea of which tournaments are running: a new one
is picked up within an hour of starting, then followed every five minutes.

### News

The home page's right column shows short news (`newsitem`, `routers/news.py`): plain text up to 500 characters,
links in it shown as links. Writers, event organizers and admins write one right there; its author or an admin
removes it. `GET /api/v1/news?limit=&before=` lists them newest first (`before`: the next page), `POST` adds one,
`DELETE /api/v1/news/{id}` removes it.

Tournament registrations come in by themselves (`services/registrations.py`): the stream poll reads Abyss Cup's and
House of the Hearth's channels every minute anyway, and a post that opens registration («Открываем регистрацию на …»,
«Регистрация открыта до …», «Ссылка на подачу регистрации») becomes an item: «Открыта регистрация на <tournament>»,
the dates and deadline, the Google form when the post links one, and the post. Closed registrations, reminders,
announcements of a later opening and other games' tournaments are left out; in Abyss Cup's channel the post must be
about the Abyss. Only posts from the last 7 days whose deadline hasn't passed count, each once (`newsitem.source_url`);
such an item shows its channel as the author, and only an admin removes it, which hides it for good.

### Articles

Articles (`newspost`, `routers/articles.py`) are written by people, never added automatically: a writer, event
organizer or admin opens `/articles` and imports a Word document (.docx, up to 100 MB) or a Google document shared as "anyone with the link can view" (Google
exports it as .docx). `services/news.py` turns it into HTML with mammoth (headings, paragraphs, lists, bold and
italics, links, tables, pictures) and cleans it with nh3, so a post holds only that formatting: no scripts,
styles or event handlers, links only to the web or mail. Its pictures (PNG, JPEG, GIF, WebP, checked by their bytes)
are saved as files under `media/news` and removed with the post. A reverse proxy in front of the API must let
100 MB requests through (nginx: `client_max_body_size 100m;`). The title is the one given, else the document's first
heading or line. `GET /api/v1/articles` lists them; the author or an admin removes one. The site's old `/news`
addresses redirect to `/articles`.

Each article counts its reads (`reads`): the page reports one with `POST /api/v1/articles/{id}/read` once a reader
has had it open for 30 seconds with the tab in view, once per browser. The same address counts once per article a
day; addresses are only held in memory for that, never stored.

### Translating articles

An article can carry a translation into the other language (English <-> Russian): its importer or an admin uploads
the translated document (.docx or a Google Docs link) on the article's page, or `app.cli set-news-translation <article id>
<file.docx>`. It's cleaned like any document; the page shows the article in the reader's language with a "show the
original" switch. `glossary.json` lists the game terms as the Russian version of the game says them, for whoever
translates.

### The stream

The home page's matches of the day show the matches played on stream, from the stream's Telegram channel
(`STREAM_TELEGRAM_CHANNEL`, `abysscup` by default), read from its public page `t.me/s/<channel>` with no
Telegram keys: the day's post ("Матчи на сегодня: A vs B …", posted as the stream starts, with the casters and
the Twitch link), each match's post when it goes on air and its results post (who won). With background syncing
on the API reads it every minute (`STREAM_INTERVAL`) into `streammatch`; `GET /api/v1/schedule/stream?from=&to=` gives a day's matches, with
whether each is on air and whether the stream is. A results post of a match the day's post didn't announce
(played off stream) is left out.

House of the Hearth's stream is read the same way, from `HOTH_TELEGRAM_CHANNEL` (`hoth_abyss`) and
`HOTH_TWITCH_CHANNEL` (`abyss_hoth`). Its posts differ: the morning post lists each match with its time and casters
("💰 A VS B — 17:00 МСК", "Комментаторы: X & Y"; "TBD VS TBD" for a match whose players come later), "Игра A VS B
переносится на 17:30 МСК" moves one, and "Результат матча A VS B" ends it (it names no winner). A TBD match gets
its players when its time comes, from the Challonge bracket the post links ("Сетка турнира"): the open match that
follows the day's matches; failing that, from its results post. Each match's stage (final, semifinal, lower
bracket round, group, ...) is read from that bracket too and shown with it.

### HotH Hub timers

House of the Hearth runs its stream from HotH Hub (hoth-hub.site), which records each match's timers: per game each
side's three room times, penalty and restarts, and who played each half. With `HOTH_HUB_KEY` (its integration key) in
`.env`, every sync reads them (or `app.cli import-hoth-hub`, `services/hoth_hub.py`); only the timers, not the
characters. A confirmed match the site's House of the Hearth tournament has (the same day, a player of each team,
by name or by the site's ties between names) gets the hub's times where it has none; one it doesn't have is added to
it as `hothhub-<id>`, one player a side as the site keeps team events. An added match the tournament site gets later
is dropped. Test matches (not confirmed) are left out, and so is a hub tournament with no site tournament. A match counts as on air from its time until its result, while the stream is live. The
endpoint gives one entry per stream with matches that day.

Whether the stream is live comes from Twitch (`TWITCH_CHANNEL`, `abyss__cup`) when an app's keys are set:
create an application at dev.twitch.tv (any OAuth redirect, e.g. `http://localhost`) and put its client id and
a new secret in `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET`; the poll then also stores the stream's status,
title and viewers in `streamstatus`. Without the keys a match counts as on air from its post until its result
(three hours at most). To read both once by hand:

```bash
venv/bin/python -m app.cli poll-stream
```

### Draft links

```bash
venv/bin/python -m app.cli fetch-draft-links            # --refresh to fetch again for every match
```

The matches list has no links to the drafts, so this asks `GET /api/abyss/draft_sets/<match id>` for
each imported match (no cookie needed) and stores every draft's spectator link in `draftlink`
(`draft_id`, `match_id`, `spectator_key`, `url`). Only matches without links are fetched. Run it after
`import-matches`; `export-xlsx` puts the links on the «Ссылки на драфты» sheet, one row per game.

### Draft bans and picks

```bash
venv/bin/python -m app.cli fetch-draft-actions          # after fetch-draft-links; --refresh to fetch again
venv/bin/python -m app.cli refresh-times                # games whose times changed on the site since they were stored
```

Opens each draft's socket (socket.io v4 at `wss://abyss.darte.gg/socket.io/draft/`, namespace `/draft`,
`session_id` = draft id, `session_key` = spectator key) and stores the `init` event it sends:

| Table | One row per | Main columns |
| --- | --- | --- |
| `draftstate` | draft | `draft_id`, `started_at`, `finished_at`, `rooms`, `bosses`, `raw` (the full init JSON) |
| `draftaction` | ban or pick, in order | `draft_id`, `seq`, `slot`, `type`, `agent_id` (null: move skipped), `at`, `pick_ms_left`, `reserve_ms_left` |

Moves come from `actualActions` (undone moves removed); the judge's UNDO/PAUSE/CONTINUE are only in `raw`.
`player0` in the site's moves is whoever picks first (`players[pIndex[0]]`), so `slot` is mapped through
`pIndex` to match `matchplayer.slot`.

The room times in `raw` (`players[].clearTimeRoom1..3`) show games left unfinished after a technical
defeat: marked FINISHED, but a room is missing, all three are 300 s, or the rooms don't add up to the
total. They keep their result but are left out of average and best times, and are listed as «Неполная
игра (тех. поражение)» on the Аномалии sheet and in check-matches. An IMMUNE_PICK character is open to both players: it lands in the team
of whoever takes it with the later IMMUNE move. `export-xlsx` adds the Баны, Баны игроков and Ходы драфтов
sheets.

### Player rosters

```bash
venv/bin/python -m app.cli build-rosters        # after fetch-draft-actions; sync runs it by itself
```

Every draft's socket data carries both players' rosters (the characters and weapons they entered, with levels,
constellations and refinements) and the site's hash of it. This rebuilds, per player and tournament, one
version per distinct roster with the games it was used in: usually one, more when the roster changed
mid-tournament (common in playoffs, where players swap characters between rounds).

| Table | One row per | Main columns |
| --- | --- | --- |
| `playerroster` | roster version of a player in a tournament | `player_id`, `tournament_id`, `hash`, `version`, `first_draft_id`, `last_draft_id`, `first_seen`, `last_seen`, `games`, `characters`, `weapons` |
| `rostercharacter` | character in a version | `roster_id`, `agent_id`, `level`, `constellation` |
| `rosterweapon` | weapon (per level and refinement) in a version | `roster_id`, `engine_id`, `level`, `refinement`, `count` |

Each tournament's page (its Stats tab, and `pool` in `GET /api/v1/tournaments/{id}`) shows its character pool: for
every character, how many of the players with draft data had it and at which constellation (C0-C6), each player
counted once with their last roster of the tournament (`roster_stats.tournament_pool`; a stage of qualifier groups
over all its groups). Players without drafts aren't in it, so the rates are of those who have. In a running
tournament, players who haven't finished a game yet count too, with the roster of their draft to come: the live
poll reads both players' rosters from each unfinished match's next draft over the draft socket (at most once an
hour per match, `LIVE_ROSTER_INTERVAL`) into `liveroster`, dropped with the match.

### Draft systems and costs

```bash
venv/bin/python -m app.cli fetch-draft-systems  # after fetch-draft-actions; sync runs it by itself
```

Every draft names the draft system it was played under; this stores each system's rules and cost tables
(`GET /api/abyss/draft_systems/<id>`, public) in `draftsystem`, fetching only new ones, one every half second.
A character costs `costs[constellation]` (C0–C6); a weapon `costs[refinement - 1]` (R1–R5; `costs[5]` is the
price when worn off its type), as the site's own code reads them. Each roster version keeps the system of its
first game (`playerroster.system_id`), and the player page shows rosters most expensive first with each item's
cost. The draft's own totals (the site's "character cost" and "weapon cost", e.g. 540 and 153) are
`players[].costAgents` / `costEngines` in `draftstate.raw`.

### Qualifier results

The data has no "qualified" flag, so the player page's Tournaments tab reads it off the next stage of the
same Abyss Cup season (`qualification_results` in `player_stats.py`). A season is the qualifiers played before
an Abyss Cup playoff. A first-stage qualifier (Qualification Stage Group…, Summer Quals Group…) is passed by
playing that season's second stage (Round 2 / 2nd Stage) or its playoff; a second-stage one by playing the
playoff; with no next stage yet it's pending. The tab also opens each tournament's roster
(`GET /api/v1/players/{id}/rosters/{tournament_id}`, one entry per version).

### Character and weapon names

```bash
venv/bin/python -m app.cli import-catalog
```

Saves the site's character and weapon lists (`/api/abyss/agents`, `/api/abyss/engines`, no cookie) to the
`agent` and `engine` tables (the site calls characters agents and weapons engines; so do the column names). `export-xlsx` then shows Russian names instead of ids; an id missing from the list stays an id.
Run it again when new characters come out. Exports and the site say Abyss for the site's `shiyu` mode.
The site lists a Traveler per element (and per twin), all under one name; they're saved as AMC, CMC, DMC, EMC, GMC,
HMC and PMC (Anemo, Cryo, Dendro, Electro, Geo, Hydro, Pyro main character), in both languages. A few other
characters get a name of our own (`NAMES` in `services/catalog.py`, e.g. Sandrone (Starglitter)).

### Tournament organizers

```bash
venv/bin/python -m app.cli fetch-tournaments
```

Stores, for each imported tournament, who organized it (the site user who created it and their profile
name), its system, prize and finish date in `tournamentinfo`, from the public tournaments list and
`/users/profile/<id>`. The site shows the organizer next to the tournament name; one who also played
links to their player page. Run it after importing new tournaments.

### Analytics

The site counts its own page views (`app/services/analytics.py`, `POST /api/v1/analytics/view`): the page,
the referring site and a visitor hash salted with a value replaced every day; no IP address or cookie is kept,
and bots, Do Not Track and Global Privacy Control are left out. Admins see daily views and visitors, the most
viewed pages and sections, referring sites and who is on the site now at `/analytics`
(`GET /api/v1/admin/analytics?days=30`). Visitor rows are deleted after 90 days.

### One person, two accounts

Someone who played from two site accounts is counted as one player with
`venv/bin/python -m app.cli merge-players Raftal1k raftalia` (the first account counts as the second; `--clear`
undoes it). Statistics, rosters, Challonge name matching and match pages all use the merged player, links to the
old account open the merged one, and both accounts share one shown nickname. Stored in `playermerge`, so
re-imports keep it.

### Challonge: results and places first

Organizers run their brackets on Challonge and link them from the tournament on the site. Those brackets
are the first source for who won a match and for every place:

```bash
venv/bin/python -m app.cli fetch-challonge             # after fetch-tournaments, which stores the links
venv/bin/python -m app.cli set-challonge-name Smertik smertikk   # a Challonge name that matches no nickname
```

Only the public embed page (`<bracket>/module`) is read: Challonge's own pages are behind a bot check,
which is not to be got around. Each finished tournament's bracket is fetched once (stored in
`challongebracket`, with the tournament's participants and their Discord names in `tournamentplayer`); `sync`
does it for new tournaments. `--refetch` fetches them all again.

Challonge names are matched to players by any nickname they played under or their Discord name, ignoring
case, spaces and punctuation, and "nick (discord)" by either half; fetch-challonge lists the names it
couldn't match. A name only one player could have but doesn't match is tied by hand with
`set-challonge-name` (`--clear` unties it). An unmatched winner makes the tournament fall back to the rules
below.

A tournament's player count (its page, the tournaments list, the home page banner) is everyone in its Challonge
bracket when it has one, no-shows and players yet to play on the site included; without a bracket, and for team
events (whose brackets list teams), it's who played its games.

Who won a match is decided in one place, `match_checks.match_outcome`, for the site, the player statistics
and export-xlsx alike: the match on the Challonge bracket first, then a technical defeat, then the total
adjusted time. Places: the final's winner and loser, the third-place match if played, then everyone by the
round they were knocked out in (5–8, 9–16, …; double elimination by losers'-bracket round). The player page
marks places worked out without Challonge with «≈».

Group stages on a Challonge bracket (round robin groups before the playoff) are read too: their results decide
the site's matches like the bracket's, but give no places.

A site tournament without a Challonge link on the site gets one by hand; fetch-tournaments keeps it while the
site has none:

```bash
venv/bin/python -m app.cli set-challonge-url "HotH: Abyss Weekend 6" https://challonge.com/hoth_fast_6   # --clear
```

### Where Challonge and the site disagree

```bash
venv/bin/python -m app.cli check-challonge
```

For every site tournament with a bracket: Challonge names matched to nobody (tie them with set-challonge-name),
site players missing from the bracket, matches on one side only, pairs that met a different number of times
(Challonge's result can't be paired, so the site's games decide), and matches whose Challonge winner differs from
what the site's own games say. The site already follows Challonge for the last ones.

### Tournaments played only on Challonge

```bash
venv/bin/python -m app.cli add-challonge-tournament https://challonge.com/afc_fast_5 "Abyss Fight Club: Abyss Weekend 5" \
    --organizer "Astro Liber"            # --date 2025-07-01 (--ended 2025-07-03), --team for a team event
```

Events played before the site (or beside it) have only their bracket. Such a tournament is stored as
`challonge-<slug>` with its bracket and a `challongetournament` row; its decided matches (bracket and group
stage) count for players' match records, head-to-heads, tournaments and places, not for games, times or
characters, which need drafts. A forfeit or a 0:0 result counts as a technical defeat. Its names are matched to
the site's players like any bracket's; people who aren't on the site appear in its table and bracket without a
link. Match pages (`/match/ch-<Challonge match id>`) show the result only. The embed page has no dates, so unless
`--date` is given the date is estimated from the bracket's Challonge id against site tournaments' brackets (shown
with «≈»). Team events are kept for their page and bracket only.

A site tournament's bracket counts the same way for its matches the site has none of (a no-show's technical loss
nobody drafted for, a game played elsewhere): they count for match records, head-to-heads and Elo, timed between
the tournament's first and last stored match. Only matches with a player who has a stored match there are added,
group matches only when one of the stored matches is a group match, and a bracket shared by several site
tournaments (a qualifier's groups) adds nothing.

### Tournaments from a picture of their bracket

A tournament with neither drafts nor a Challonge bracket (only its published bracket, as a picture) is entered by
hand as a JSON file under `brackets/` and stored like a Challonge-only one, with the id `manual-<slug>` and no link:

```bash
venv/bin/python -m app.cli add-manual-tournament brackets/abyss_cup_minor_1.json
```

The file holds `slug`, `title`, `started` and `ended` (YYYY-MM-DD; the rounds are spread between them), `rounds`
(single elimination, first round first, each match `[player 1, player 2, winner]`), an optional `third_place` match,
and optional `major`, `team` and `organizer`. Running it again replaces the tournament.

### Organizers' names

The site shows who created a tournament on darte.gg. An organizer can be shown under a name of their own (a league
or brand), and two accounts running one series can count as one organizer, on every page, in the organizer filters
and in the export:

```bash
venv/bin/python -m app.cli set-organizer "Astro Liber" --name "House of the Hearth"
venv/bin/python -m app.cli set-organizer Xeity --name "Abyss Cup"
venv/bin/python -m app.cli set-organizer Skiramit --into Xeity        # --clear shows them as on the site again
```

Stored in `organizeralias`, so fetch-tournaments keeps it. The `organizer` of a hand-entered or Challonge-only
tournament can be either name.

### People who never played on the site

Someone known only from bracket-only tournaments (Challonge or a picture) gets a player page once added by hand, with
their bracket names tied to them:

```bash
venv/bin/python -m app.cli add-player Invinsik Invinsik nvnsk     # name, then their names in brackets
```

Stored in `offsiteplayer` (id `offsite-<slug>`); the names are ordinary `set-challonge-name` ties. Their page has
matches, tournaments and places, no games.

### Spiral Abyss

```bash
venv/bin/python -m app.cli fetch-abyss            # --refetch for every phase again; sync runs it daily
```

Tournaments are played on the live Spiral Abyss floor 12, so a match belongs to the phase running on its date
(phases change on the 16th). `fetch-abyss` reads every phase from alioth.wiki (`/en/gi/abyss/<n>`, the data is the
page's embedded Nuxt payload) and keeps floor 12 only in `abyssphase`: dates, moon blessings, Ley Line Disorder,
the HP multiplier, every chamber's waves and monsters (HP, element, resistances, shields) and the bosses'
mechanics. Monster and element icons (© HoYoverse) are downloaded once into `data/abyss/` (not in git) and served
at `/api/v1/abyss-assets/`, so visitors never load them from alioth. Requests are a second apart, and the sync
asks alioth at most once a day; only new phases (and the current one) are fetched.

Russian texts of the bosses' mechanics (moon blessings and Ley Line Disorder stay in English) are in
`app/data/abyss_ru.json`, keyed by the English text; a new
phase shows English until its texts are added there. Names of monsters and moons stay as in the English game.

Endpoints: `GET /api/v1/abyss` (every phase, newest first, with tournament matches), `GET /api/v1/abyss/current`,
`GET /api/v1/abyss/{id}` (floor 12 in full, the tournaments played on it and their median clear time); a
tournament's page data has `abyss`, every phase its matches fall in. The site shows them at `/abyss`,
`/abyss/<id>` and on each tournament page.

### Tournaments in stages

A tournament run in stages (groups, Swiss, main stage) shows as one event: the tournaments list has one row for
it that opens to its stages, and a stage's page switches between them. Abyss Cup seasons group on their own (every
qualifier with the first playoff after it, see `services/events.py`): the groups of one qualifier round (A & B,
C & D, ...) are one stage, «Qualification» (or «Qualification Round 1» and «Round 2» for a season with a second
round), id `quals-<round>-<playoff id>`. Its page has one table of all its groups, group by group, their matches
by group and their statistics together; a group's own address opens its stage. Other events are set by hand,
stages in order, `=` naming a stage:

```bash
venv/bin/python -m app.cli set-tournament-event "Abyss Fight Club 4" challonge-afc_4_1="Group stage 1" \
    challonge-afc_4_2="Group Stage 2" challonge-afc_4_3="Main Stage"     # --clear <tournaments> undoes it
```

Statistics still count each stage as its own tournament.

### Tournament places without Challonge

The first four places of a bracket tournament without a Challonge bracket are worked out from its matches,
the same way on the site and on the «Призёры» sheet: 1st and 2nd are the winner and loser of the last
match (the final); the others rank by how late they were knocked out, the winner first when two share a match
(a third-place match). A final without any result leaves the tournament out, unless its winner is set by hand from the official bracket: `venv/bin/python -m app.cli set-tournament-winner "Abyss Weekend 16" rpyt02 --source challonge.com/hoth_fast_16` (`--clear` removes it; stored in `tournamentwinner`, so re-imports keep it). Group stages, qualifiers and
league rounds (titles with group, quals, qualification or round) get no places. Team events (2x2) have no
places and are left out of all personal statistics; their matches still show in the match lists and match
sheets.

### Major tournaments

`GET /api/v1/players?scope=major` and `/players/{id}?scope=major` (the site's «Adjust for major
tournaments» button) count only Abyss Cup qualifiers and playoffs: tournaments whose own system on the site
is Abyss Cup (from fetch-tournaments) and whose title has Qualification, Quals or Playoff. Fast cups and
other series (New Gen, HotH, Abyss Ascend) are left out. The rule is `MAJOR_SYSTEM` / `MAJOR_TITLE` in
`match_checks.py`. Challonge-only tournaments count when marked major (`add-challonge-tournament --major`): the numbered
Abyss Fight Club events (Abyss Fight Club 2, 3, 4, every stage), not the Abyss Fight Club weekends and fast cups.

### No personal details of players

GITV keeps no real names, birthdays or avatars of players: only what tournaments publish (nicknames, matches,
results). The member suggestions of those details were removed, with their tables (`playerprofile`,
`playerprofilechange`, `playersuggestion`, `suggestionban`).

### Matches of the day

Event organizers, admins and super admins announce upcoming matches on `/schedule` (linked from the home page's
«Today's Matches» for them): the tournament (picked from the site's running/upcoming list, cached hourly, or
typed), two players (known players are linked, new ones are just nicknames) and the start time in their own
time zone, stored in UTC, up to 60 days ahead. The home page shows the viewer's local day. An organizer removes
their own entries, an admin any. Table `scheduledmatch`; endpoints `GET /api/v1/schedule?from=&to=` (public,
at most 31 days), `POST /api/v1/schedule`, `DELETE /api/v1/schedule/{id}`, `GET /api/v1/schedule/tournaments`.

### Checking the data

```bash
venv/bin/python -m app.cli check-matches            # --examples 20 for more per kind
```

Lists suspicious data: clear time 0, times far below or above the tournament's median, clearPoints
filled in, ties, unusual pick or game counts, a character twice in one team, a player against themselves,
players changing between games, out-of-range values and matches that look like duplicates. A game
where either clear time is 0 has no result: no winner, and it is left out of times, winrates and the
match total in the export. Everything found is also on the export's "Аномалии" sheet.

### Removing tournaments

```bash
venv/bin/python -m app.cli list-tournaments                 # numbered, oldest first, with ids
venv/bin/python -m app.cli delete-tournaments --first 2     # the two oldest
venv/bin/python -m app.cli delete-tournaments <id> <id>     # or by id
```

Deletes the tournaments with all their matches, games, players and picks after showing them and
asking for `yes`. Importing their URLs again brings them back, so remove those lines from the URLs file.
