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
- **Community** — Discord sign-in; members suggest players' real names, birthdays and avatars, admins review them;
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

- **Visitors.** No analytics, trackers or ads. Besides the site itself, the browser loads fonts from Google
  Fonts and character art and tournament banners from darte.gg's image server.
  Cookies: `gitv-lang` (site language) and a 10-minute `discord_oauth_state` during sign-in.
- **Accounts.** Sign-in is Discord only, no passwords. Stored: Discord id and username, the verified email Discord
  returns, the chosen nickname and the role. Discord's access token is used once to read the profile and is not
  stored. The site token is kept in the browser's local storage.
- **Players.** Tournament data is public on darte.gg. Real names, birthdays and avatars appear only after an admin
  accepts a member's suggestion; every change is logged with who made it.
- **Outbound requests.** The server only calls the darte.gg public API and draft websocket, Challonge's public
  embed pages and Discord OAuth. Automatic syncing never runs more than once an hour and never bypasses bot
  protection.
- **Hardening.** Rate limits on sign-in and every write, role checks on each request, uploads checked by their
  file signature, parametrized SQL. Secrets live in `.env`, which is not committed.

## Tech stack

Python 3.12+, FastAPI, SQLModel/SQLite, pytest, ruff · TypeScript, React 19, React Router 8 (SSR), Vite.

## Getting started

API (from `api/`):

```bash
python3 -m venv venv
venv/bin/pip install -r requirements-dev.txt
cp .env.example .env            # fill in SECRET_KEY and the Discord app keys
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
