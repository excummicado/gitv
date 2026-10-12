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
- `GET /api/v1/auth/discord/login` — redirects to Discord (`prompt=none` skips Discord's approval screen for returning players)
- `GET /api/v1/auth/discord/callback` — Discord redirects back here; issues the GITV token, or a 10-minute sign-up token for a new user
- `POST /api/v1/auth/discord/register` — sign-up token + chosen nickname → creates the account, returns the GITV token
- `GET /api/v1/users/me` — the signed-in user (Bearer token)

## Roles

Every account is a `user` (signed in for 30 days) or an `admin` (signed in for
60 minutes, since an admin token is worth more if stolen). Change a role from
inside `api/`:

```bash
venv/bin/python -m app.cli set-role <nickname> admin
```

The user has to sign in again afterwards; their old token stops working.
