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
│   ├── database.py      # Engine, table creation, session dependency
│   ├── models.py        # User table and API models
│   ├── security.py      # JWT access tokens
│   ├── dependencies.py  # Current user from the Bearer token
│   ├── rate_limit.py    # Request limits for sign-in and member writes
│   ├── messages.py      # Russian versions of the API's error messages
│   ├── routers/         # health, users (/users/me), discord (sign-in), matches, players, ...
│   ├── services/        # Business logic; stats/ is the player and tournament statistics
│   └── main.py          # FastAPI app and ASGI entry point
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
venv/bin/fastapi dev app/main.py
```

Tests: `venv/bin/pip install -r requirements-dev.txt`, then `venv/bin/python -m pytest`.

Error messages come in the site's language: the API reads the `gitv-lang` cookie (or `Accept-Language`) and
answers in Russian from `app/messages.py`. Sign-in, sign-up, suggestions, profile edits, matches of the day
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
then fetches their draft links, drafts and details, so no URLs file is needed. Running tournaments aren't
imported; they come in after they finish. Tournaments in `ignoredtournament` are skipped;
`delete-tournaments` adds the ones it deletes.

On a server, set `SYNC_INTERVAL=3600` in `.env`: the API then syncs in the background by itself (0 = off;
run a single worker). A lock file (`.sync.lock`) keeps two syncs from running at once, so a manual `sync`
during a background one is skipped.

Nothing automatic asks the site for anything more often than once an hour (`MIN_INTERVAL`): lower
`SYNC_INTERVAL` or `--watch` values are raised to 3600, the time of the last request is kept in
`.sync-state.json` so API restarts don't reset it, and a failed request also waits an hour. The home page's
running tournaments (`GET /api/v1/matches/live-tournaments`) come from the site's list cached the same way,
so they can be up to an hour old.

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

### Tournament organizers

```bash
venv/bin/python -m app.cli fetch-tournaments
```

Stores, for each imported tournament, who organized it (the site user who created it and their profile
name), its system, prize and finish date in `tournamentinfo`, from the public tournaments list and
`/users/profile/<id>`. The site shows the organizer next to the tournament name; one who also played
links to their player page. Run it after importing new tournaments.

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

Who won a match is decided in one place, `match_checks.match_outcome`, for the site, the player statistics
and export-xlsx alike: the match on the Challonge bracket first, then a technical defeat, then the total
adjusted time. Places: the final's winner and loser, the third-place match if played, then everyone by the
round they were knocked out in (5–8, 9–16, …; double elimination by losers'-bracket round). The player page
marks places worked out without Challonge with «≈».

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
`match_checks.py`.

### Player info: real name, birthday, avatar

Shown under the nickname on the player page (real name, age, avatar), from `playerprofile`.

| Who | Can |
| --- | --- |
| members, writers | suggest a name, birthday and/or avatar (bottom of the player page) |
| event organizers | write the name and birthday directly; no suggesting, no reviewing |
| admins, super admins | write directly, accept or reject suggestions (their profile page), stop a member from suggesting |

Every change leaves a trace in `playerprofilechange`: the field, old and new value, who made it, when, and
the suggestion it came from (so its author too). The player page lists these changes publicly.

| Table | Holds |
| --- | --- |
| `playerprofile` | what the player page shows |
| `playerprofilechange` | every change to it |
| `playersuggestion` | every suggestion: the filled-in fields, author, status (pending, accepted, rejected), reviewer |
| `suggestionban` | members who may not suggest |

A member has at most one pending suggestion per player and 10 in all. Names are letters (any alphabet)
with spaces, hyphens, apostrophes and dots, up to 80 characters; birthdays from 1950 up to 8 years ago.
Avatars are PNG, JPEG or WebP up to 2 MB, recognised by their bytes rather than the file name, stored
under `media/avatars` (not in git) and served at `/api/v1/media/`. Rejected and replaced avatars are deleted.

Endpoints: `POST /api/v1/players/{id}/suggestions` (multipart: `real_name`, `birth_date`, `avatar`),
`GET /api/v1/suggestions/me`, `PUT /api/v1/players/{id}/profile` (editors; JSON, only the fields sent change,
null clears); staff: `GET /api/v1/admin/suggestions?status=pending`, `POST /api/v1/admin/suggestions/{id}/accept|reject`,
`GET|POST /api/v1/admin/suggestion-bans`, `DELETE /api/v1/admin/suggestion-bans/{nickname}`.

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
