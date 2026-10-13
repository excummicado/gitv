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
│   ├── routers/         # health, users (/users/me), discord (sign-in)
│   ├── services/        # Business logic modules
│   └── main.py          # FastAPI app and ASGI entry point
├── .env.example         # Copy to .env and fill in
└── requirements.txt
```

## Run

From inside `api/`:

```bash
cp .env.example .env   # then fill in SECRET_KEY and the Discord keys
venv/bin/pip install -r requirements.txt
venv/bin/fastapi dev app/main.py
```

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

It asks for the site's `Cookie` header (DevTools > Network > a request to the API > Request Headers),
hidden as you type, or reads it from `ABYSS_COOKIE`. On macOS a pasted value longer than about
1000 characters doesn't fit in the prompt (Enter is swallowed and it seems to hang), so copy the cookie
and run `ABYSS_COOKIE="$(pbpaste)" venv/bin/python -m app.cli import-matches ...` instead. The cookie is never saved. Saved API responses
can be imported without downloading: `venv/bin/python -m app.cli import-matches --json page1.json page2.json`.

Tables:

| Table | One row per | Main columns |
| --- | --- | --- |
| `tournament` | tournament | `id`, `title` |
| `match` | match | `tournament_id`, `created_at`, `system_title`, `mode`, `free_restarts`, `paid_restarts`, `raw` (the full API JSON) |
| `matchdraft` | draft (game) in a match | `match_id`, `game_no`, `status`, `first_pick_slot` |
| `matchplayer` | player in a draft | `draft_id`, `match_id`, `slot`, `user_id`, `full_name`, `restarts`, `clear_time`, `clear_points`, `prebans` |
| `matchpick` | agent + engine in a player's team | `player_id`, `draft_id`, `position`, `agent_id`, `agent_mindscape`, `engine_id`, `engine_refinement` |

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

One workbook, a sheet per view: players (winrates, times, restarts, favourite agents), every game of
every player in order, games, matches, head-to-head, each player's agents, agents, engines, every
pick, and tournaments. A game goes to the lower time after restart penalties (restarts beyond
`free_restarts` cost `paid_restarts[k]` seconds), a match to the lower total; raw times are there too.
