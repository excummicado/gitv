# GITV — Abyss tournament statistics

GITV collects the results of community Abyss tournaments run on [darte.gg](https://abyss.darte.gg) and turns them
into a stats site: player profiles, head-to-head comparisons, character pick and ban rates, tournament brackets
and standings. The site is bilingual (English and Russian).

## Features

- **Players** — profile with records, top-4 finishes, streaks, times, most frequent opponents, every match and
  tournament played, and every character ever in their roster with constellation history.
- **Compare** — two players side by side (optionally major tournaments only) with their full head-to-head record.
- **Tournaments** — list with winners and prize pools; per tournament: standings, the Challonge bracket, matches
  and draft statistics.
- **Characters** — pick rate, ban rate, presence and winrate for every character, split by constellation, with
  filters by organizer, date, major tournaments and prize winners.
- **Matches** — every game with team compositions, room times, draft order and technical-defeat detection.
- **Spiral Abyss** — floor 12 of every Abyss phase since 1.0 (enemies, HP, resistances, moon blessings, boss
  mechanics; data from alioth.wiki), and on each tournament page the Abyss it was played on.
- **Community** — Discord sign-in; writers post news and articles;
  event organizers schedule matches of the day.

## How it works

```text
darte.gg public API ──┐                       ┌─> FastAPI (api/) ──> React Router SSR (web/)
draft websocket ──────┼─> importer / sync ──> SQLite
Challonge embed page ─┘     (api/app/services)
```

- `api/` imports finished tournaments, their drafts (bans, picks, room times, rosters) and Challonge brackets,
  then serves statistics computed in memory and rebuilt when the data changes.
- Match results follow one rule everywhere (site, statistics, Excel export): the Challonge bracket first, then
  technical defeats, then total adjusted time — see `api/app/services/match_checks.py`.
- `web/` is a server-rendered React Router app that only talks to the API.

## Data and privacy

- **Visitors.** No third-party analytics, trackers or ads, and no cookies for counting. The site counts page
  views itself (`api/app/services/analytics.py`): the page path, the referring site, and a visitor hash salted
  with a random value that is replaced every day, so no IP address is stored and the same person can't be
  followed across days. Bots and browsers sending Do Not Track or Global Privacy Control aren't counted; only
  admins see the totals. Besides the site itself, the browser loads fonts from Google Fonts and character art
  and tournament banners from darte.gg's image server. Cookies: `gitv-lang` (site language), a 10-minute
  `discord_oauth_state` during sign-in and `gitv_session` once signed in. The site says all this to visitors at
  `/privacy`.
- **Accounts.** Sign-in is Discord only, no passwords. Discord is asked only for `identify` (no email scope).
  Stored: Discord id and username, the chosen nickname and the role. Discord's access token is used once to read the profile and is not
  stored. The site token lives in the httpOnly cookie `gitv_session` (path `/api`, SameSite=Lax, Secure on https),
  out of reach of the page's scripts; the browser's local storage keeps only the nickname and role to show.
- **Players.** Only what tournaments publish: nicknames, matches and results. No real names, birthdays or
  avatars are kept.
- **Outbound requests.** The server only calls the darte.gg public API and draft websocket, Challonge's public
  embed pages, alioth.wiki's Spiral Abyss pages (at most once a day) and Discord OAuth. Automatic syncing runs
  once an hour, except that the matches and Challonge brackets of tournaments running now are polled every five
  minutes, and it never bypasses bot protection.
- **Hardening.** Rate limits on sign-in and every write, role checks on each request, parametrized SQL.
  Requests that change something with the session cookie must carry the `X-GITV: 1` header the site's scripts
  send (another site can't, so no CSRF). Pages are sent with a Content-Security-Policy (scripts only from the site,
  React Router's inline ones by a per-request nonce), `X-Frame-Options: DENY`, `nosniff` and, on https, HSTS
  (`web/app/entry.server.tsx`, production only); the API adds `nosniff` and `DENY` to its answers and hides its
  `/docs` unless `FRONTEND_URL` is localhost. Secrets live in `.env`, which is not committed.

## Running in production

- A push to `main` deploys by itself once CI passes (`.github/workflows/ci.yml`, secrets `DEPLOY_SSH_KEY` and
  `DEPLOY_KNOWN_HOSTS`): the server takes the build through `tools/deploy/gitv-deploy`, which is all that key can run,
  and puts the previous version back if the site doesn't come up. A change to that script is installed by hand.
- New migrations and dependencies stop the deploy. Do them by hand first: with the API stopped and a copy of the
  database made, run `venv/bin/alembic upgrade head` in `api/` before starting it.
- One API process (`fastapi run app/main.py`, no extra workers): syncing, the stream poll and the rate limits
  live in it. Behind a proxy, set `TRUST_FORWARDED_FOR=true`; the proxy sends `/api/*` to the API (allow 100 MB
  bodies for news imports) and the rest to the web server.
- The web server (`npm run build`, then `npm run start` with `NODE_ENV=production`) asks the API for link previews
  and the sitemap at `API_URL` (default `http://127.0.0.1:8000`). It renders each page's title and description
  for Discord, Telegram and search engines (`web/app/preview.server.ts`, `GET /api/v1/preview`), and serves
  `/robots.txt` and `/sitemap.xml`; it uses `X-Forwarded-Proto`/`X-Forwarded-Host` for the site's address.
- Python dependencies are pinned in `api/requirements*.txt`: upgrade one on purpose and run the tests.

## Tech stack

Python 3.12+, FastAPI, SQLModel/SQLite, pytest, ruff · TypeScript, React 19, React Router 8 (SSR), Vite.

## Getting started

API (from `api/`):

```bash
python3 -m venv venv
venv/bin/pip install -r requirements-dev.txt
cp .env.example .env            # fill in SECRET_KEY and the Discord app keys
venv/bin/alembic upgrade head   # creates the tables
venv/bin/fastapi dev app/main.py
```

Web (from `web/`), with the API running on port 8000:

```bash
npm install
npm run dev                     # http://localhost:5173, /api is proxied to the API
```

Importing data, syncing and the other maintenance commands are described in [`api/README.md`](api/README.md).

## Tests and checks

```bash
cd api && venv/bin/python -m pytest && venv/bin/ruff check app tests
cd web && npm run typecheck
```

The same checks run on every push (`.github/workflows/ci.yml`).

## Layout

```text
api/    FastAPI app, importers, statistics and tests
web/    React Router frontend
tools/  draft-stats: the original standalone statistics script
```
