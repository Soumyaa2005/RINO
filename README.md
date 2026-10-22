# Rino

Rino connects to GitHub, runs the tests and static checks already in a Python repo, triages what it finds with fixed rules, raises critical bugs as GitHub Issues, and suggests a fix that a developer approves before Rino opens a draft pull request.

This repo is being built in steps. **Step 1 (this version)** sets up the foundation:

- docker-compose with frontend, backend, worker, Postgres and Redis
- Database migrations (orgs, users, audit log)
- Login with GitHub
- Admin and Developer roles, enforced on every backend endpoint
- Settings → Users & roles (invite, change role, deactivate) and the audit log
- App shell with role-aware navigation; later screens show where they arrive

## Run it locally (macOS)

You need **Docker Desktop** running.

### 1. Create the GitHub App (login part only for now)

1. GitHub → **Settings → Developer settings → GitHub Apps → New GitHub App**
2. **GitHub App name:** anything unique, e.g. `rino-local-yourname`
3. **Homepage URL:** `http://localhost:3000`
4. **Callback URL:** `http://localhost:3000/api/auth/github/callback`
5. Leave **"Request user authorization (OAuth) during installation"** unchecked
6. **Webhook:** uncheck **Active** for now (step 2 turns it on)
7. **Permissions:** none needed yet (step 2 adds them)
8. **Where can this GitHub App be installed?** "Only on this account" is fine for local work
9. Create the app, then on its page copy the **Client ID** and click **Generate a new client secret**

### 2. Configure

```zsh
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # paste as SESSION_SECRET
```

In `.env`, set:

- `SESSION_SECRET` to the value above
- `BOOTSTRAP_ADMIN_GITHUB_LOGIN` to **your** GitHub username (you become the first Admin)
- `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` from step 1

### 3. Start

```zsh
docker compose up --build
```

Open http://localhost:3000 and click **Login with GitHub**. The first login by `BOOTSTRAP_ADMIN_GITHUB_LOGIN` creates your Admin account. Everyone else needs an invite from **Settings → Users & roles**; uninvited people see "ask your Admin for access".

Database migrations run automatically when the backend container starts.

### Trying roles without a second GitHub account

Set `DEV_LOGIN_ENABLED=true` in `.env` and restart. The login page then shows a **Dev login** box where you can sign in as any invited user by username, no GitHub needed. It is refused when `APP_ENV=production`; keep it off anywhere but your own machine.

## Run the backend tests

```zsh
cd backend
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
pytest -q
```

Tests use a temporary SQLite database by default. To run them against Postgres, set `DATABASE_URL` to an empty Postgres database first.

## How it fits together

```
browser ──► frontend (Next.js, :3000) ──/api/*──► backend (FastAPI, :8000) ──► Postgres
                                                        │
                                                        └──► Redis ◄── worker (RQ)
```

- The browser only talks to the frontend. `frontend/app/api/[...path]/route.ts` forwards `/api/*` to the backend, so session cookies stay first-party and the backend needs no CORS.
- Sessions are signed, HttpOnly cookies. Each request reloads the user, so a role change or deactivation applies on the next click.
- State-changing requests must carry the `X-Rino-CSRF: 1` header, which other sites can't add to a cross-site request.
- Rino never stores the user's GitHub token: it's used once at login to read who you are, then dropped.
- Rino always keeps at least one active Admin; the API refuses to demote or deactivate the last one.

```
backend/
  app/main.py            FastAPI app, CSRF check, health endpoint
  app/config.py          settings from env (refuses unsafe production config)
  app/models.py          orgs, users, audit_log
  app/security.py        session cookie, role guards
  app/services.py        login resolution (invite / bootstrap admin), audit helper
  app/github_oauth.py    GitHub OAuth calls
  app/routers/auth.py    login, callback, logout, /me, dev login
  app/routers/admin.py   users & roles, audit log (Admin only)
  alembic/               migrations
  tests/                 auth, roles, CSRF and OAuth tests
frontend/
  app/login              login page
  app/(app)/...          signed-in screens (dashboard, settings, placeholders)
  components/AppShell    sidebar, top bar, role-aware nav
  lib/api.ts             API client
```

## What's next

| Step | Adds |
|---|---|
| 2 | GitHub App install, repo list, Repository Setup screen |
| 3 | Sandbox runner: clone, install, pytest, parse JUnit XML |
| 4 | pylint + bandit, triage with `rules.yaml`, Repository Dashboard |
| 5 | AI root-cause explanations, GitHub Issue confirm flow |
| 6 | Fix suggestions, safety checks, Code Review screen |
| 7 | Approve → draft PR, Testing Dashboard |
| 8 | GitHub Actions / dev instance runner |
| 9 | Performance Dashboard, triage rules editor, fix limits |
