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
