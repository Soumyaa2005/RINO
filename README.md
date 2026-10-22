# Rino

Rino connects to GitHub, runs the tests and static checks already in a Python repo, triages what it finds with fixed rules, raises critical bugs as GitHub Issues, and suggests a fix that a developer approves before Rino opens a draft pull request.

It's being built in steps. Done so far:

**Step 1:** foundation
- docker-compose with frontend, backend, worker, Postgres and Redis; database migrations
- Login with GitHub; Admin and Developer roles, enforced on every backend endpoint
- Settings → Users & roles (invite, change role, deactivate) and the audit log

**Step 2:** connect repositories
- Install the GitHub App from Rino and choose which repos it can see; repos sync automatically
- Repository Setup: per repo, choose **where tests run** (GitHub Actions, a dev instance, or the Rino sandbox) and check that it's set up correctly
- Signed GitHub webhooks keep the repo list current (repos added or removed, app suspended or uninstalled)
- Repo and branch picker in the top bar for everyone; Developers only see repos an Admin enabled

## Run it locally (macOS)

You need **Docker Desktop** running.

### 1. Create the GitHub App

GitHub → **Settings → Developer settings → GitHub Apps → New GitHub App**:

| Field | Value |
|---|---|
| GitHub App name | anything unique, e.g. `rino-local-yourname` |
| Homepage URL | `http://localhost:3000` |
| Callback URL | `http://localhost:3000/api/auth/github/callback` |
| Request user authorization (OAuth) during installation | unchecked |
| Setup URL (under *Post installation*) | `http://localhost:3000/api/github/setup` |
| Redirect on update | **checked** |
| Webhook → Active | checked if you set up ngrok (below), otherwise unchecked |
| Webhook URL | `https://<your-ngrok-domain>/api/webhooks/github` |
| Webhook secret | a random string (also goes in `.env`) |

**Repository permissions:**

| Permission | Access | Why |
|---|---|---|
| Contents | Read-only | read code, workflows and config files |
| Metadata | Read-only | required by GitHub |

Later steps add more (Issues, Pull requests and Actions write access, Contents write). GitHub asks the installer to approve the new permissions when that happens.

**Subscribe to events:** none needed. Installation events are always sent to GitHub Apps.

**Where can this GitHub App be installed?** "Only on this account" is fine for local work.

After creating it, on the app's page:
1. Copy the **App ID** and **Client ID**, and note the **slug**: the last part of the app's public URL, `github.com/apps/<slug>`.
2. **Generate a new client secret** and copy it.
3. **Generate a private key**. A `.pem` file downloads. Save it as `secrets/github-app.pem` in this repo. The `secrets/` folder is git-ignored.

### 2. Configure

```zsh
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # SESSION_SECRET
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # GITHUB_WEBHOOK_SECRET
```

In `.env`, set:

- `SESSION_SECRET`
- `BOOTSTRAP_ADMIN_GITHUB_LOGIN`: **your** GitHub username (you become the first Admin)
- `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`
- `GITHUB_APP_ID`, `GITHUB_APP_SLUG`
- `GITHUB_APP_PRIVATE_KEY_PATH=/secrets/github-app.pem` (already the default)
- `GITHUB_WEBHOOK_SECRET`: the same value you typed into the app's webhook secret field

### 3. Start

```zsh
docker compose up --build
```

Open http://localhost:3000 and click **Login with GitHub**. Migrations run automatically when the backend starts.

### 4. Connect repositories

1. As Admin, open **Repository Setup** → **Install GitHub App**.
2. On GitHub, pick the account and the repositories Rino may access, then **Install**.
3. GitHub sends you back to Rino and the repos appear.
4. For each repo, click **Set up**, choose where its tests run, then **Save & check**.

A repo must show **Ready** before analysis can run on it (analysis arrives in step 3).

### Webhooks while developing locally (optional)

GitHub can't reach `localhost`. To receive webhooks, expose port 3000 with [ngrok](https://ngrok.com/):

```zsh
brew install ngrok
ngrok http 3000
```

Copy the `https://….ngrok-free.app` address into the app's **Webhook URL** as `https://….ngrok-free.app/api/webhooks/github`, and set **Active**. Without webhooks everything still works: use **Sync repos** on Repository Setup after changing repo access on GitHub.

### Trying roles without a second GitHub account

Set `DEV_LOGIN_ENABLED=true` in `.env` and restart. The login page then shows a **Dev login** box where you can sign in as any invited user by username. It is refused when `APP_ENV=production`.

## Where tests run

Each repo picks one test environment on Repository Setup.

| Option | How it works | What Rino checks |
|---|---|---|
| **GitHub Actions** | Rino starts your existing test workflow and reads its results | workflow file exists, has a `workflow_dispatch` trigger, uploads a `rino-junit` artifact |
| **Dev instance** | Same, but the workflow runs on your own server through a [GitHub self-hosted runner](https://docs.github.com/en/actions/hosting-your-own-runners) | the above, plus a job uses `runs-on: self-hosted` |
| **Rino sandbox** | Rino clones the repo into an isolated Docker container and runs pytest | `requirements.txt` exists if the setup command uses it; tests or pytest config present |

For GitHub Actions or a dev instance, the workflow needs these two parts so Rino can start it and read the results:

```yaml
on:
  push:
  workflow_dispatch:        # lets Rino start the workflow

jobs:
  test:
    runs-on: ubuntu-latest  # or: self-hosted, for a dev instance
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: pytest --junitxml=junit.xml
      - uses: actions/upload-artifact@v4
        if: always()        # upload results even when tests fail
        with:
          name: rino-junit
          path: junit.xml
```

If developers also use the dev instance, tick **shared** so Rino runs one job at a time.

## Run the backend tests

```zsh
cd backend
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
pytest -q
```

Tests use a temporary SQLite database and an in-memory fake of the GitHub API. They exercise the real GitHub code: App JWT signing, installation tokens, pagination and file reads. To run against Postgres, set `DATABASE_URL` to an empty Postgres database first.

## How it fits together

```
browser ──► frontend (Next.js, :3000) ──/api/*──► backend (FastAPI, :8000) ──► Postgres
                                                        │        │
GitHub webhooks ──► /api/webhooks/github ───────────────┘        └──► GitHub API (as the App)
                                                        │
                                                        └──► Redis ◄── worker (RQ)
```

- The browser only talks to the frontend; `/api/*` is forwarded to the backend, so cookies stay first-party and the backend needs no CORS.
- Sessions are signed HttpOnly cookies, and each request reloads the user, so role changes apply immediately. State-changing requests need the `X-Rino-CSRF: 1` header.
- Webhooks are accepted only with a valid `X-Hub-Signature-256`, never unsigned.
- A new GitHub installation is only linked to Rino when an Admin started the install from Rino. A one-time state value proves it.
- Installation tokens last one hour, are cached in memory, and are never logged or stored. The user's own GitHub token from login is used once to read who they are, then dropped.
- All GitHub calls go through `app/git_providers/`, behind a provider-neutral interface, so Bitbucket or Azure DevOps can be added later without touching the rest.

```
backend/app/
  main.py                 FastAPI app, CSRF check, health endpoint
  config.py               settings from env (refuses unsafe production config)
  models.py               orgs, users, audit_log, github_installations, repos, repo_test_configs
  security.py             session cookie, role guards
  services.py             login resolution, audit helper
  github_oauth.py         GitHub login (OAuth)
  git_providers/base.py   provider-neutral interface
  git_providers/github.py GitHub App implementation
  repo_sync.py            keep repos in step with the installation
  repo_checks.py          validate and check a repo's test environment
  routers/auth.py         login, callback, logout, /me, dev login
  routers/admin.py        users & roles, audit log
  routers/github.py       install flow, webhooks, repo setup (Admin)
  routers/repos.py        repo and branch picker (everyone)
frontend/
  app/login               login page
  app/(app)/repositories  Repository Setup
  app/(app)/settings      users & roles, audit log
  components/AppShell     sidebar, top bar, role-aware nav
  components/RepoSelection repo and branch picker
```

## What's next

| Step | Adds |
|---|---|
| 3 | Sandbox runner: clone, install, pytest, parse JUnit XML |
| 4 | pylint + bandit, triage with `rules.yaml`, Repository Dashboard |
| 5 | AI root-cause explanations, GitHub Issue confirm flow |
| 6 | Fix suggestions, safety checks, Code Review screen |
| 7 | Approve → draft PR, Testing Dashboard |
| 8 | GitHub Actions / dev instance runner |
| 9 | Performance Dashboard, triage rules editor, fix limits |
