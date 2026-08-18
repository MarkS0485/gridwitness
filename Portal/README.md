# GridWitness Portal

The human-facing front door for GridWitness, in the TSGBWebsite house style. It provides accounts,
self-service API keys, per-channel consent, and GDPR data-subject actions — while the Python ingest
server (`../server`) remains the machine ingest engine. One domain
(`ingest.twinscrollgridbalancer.co.uk`), path-routed: `/v1/*` → ingest, everything else → portal.

ASP.NET Core 10 MVC + Identity (SQLite) + Tailwind v4 (standalone CLI, no Node).

## What it does

- **Marketing / trust pages** — home, how it works (node & privacy tiers), privacy statement, data
  schema, submitter/API guide.
- **Accounts** — email + password sign-up, login, email confirmation (ASP.NET Identity default UI,
  restyled via `Areas/Identity/Pages/_Layout.cshtml`).
- **Dashboard** — issue an API key (registers a node on the ingest server, populating
  `contributor_ref` = the Identity user id), shown once. List, manage, and erase your nodes.
- **GDPR gate** — anyone can register and contribute without confirming their email, but **altering
  consent or erasing data requires a confirmed email** (proof the account is yours). Enforced
  server-side in `DashboardController`, not just in the UI.

The portal stores **only accounts** (Identity tables). Nodes and tokens live in the ingest server;
the portal reads/creates/alters them through the internal admin API. No token is ever persisted here.

## Architecture

```
browser ──► Portal (this app) ──HTTP + X-GW-Internal──► ingest server /v1/register, /v1/admin/*
                 │                                            │
            accounts SQLite                          nodes/tokens SQLite + CSV staging ──► GDA lake
```

`contributor_ref` (the Identity user id) is the account↔node link that makes ownership provable and
GDPR erasure honourable. The internal credential (`GW_INTERNAL_KEY`) is shared with the ingest server
over the private network only.

## Run locally

Bring up the Python ingest server first (with an internal key), then the portal pointed at it:

```bash
# terminal 1 — ingest server
cd ../server && pip install -e .[dev]
GW_INTERNAL_KEY=devsecret python -m gridwitness_server.main      # :8000

# terminal 2 — portal
GW_INTERNAL_KEY=devsecret GW_INGEST_BASE=http://localhost:8000 \
ASPNETCORE_URLS=http://localhost:5080 dotnet run                  # :5080
```

With no SMTP configured, email-confirmation links are logged to stdout instead of sent.

## Configuration

| Setting | Env var | Meaning |
|---|---|---|
| Ingest base URL | `GW_INGEST_BASE` / `Ingest:BaseUrl` | Where the Python server lives (`http://ingest:8000` in compose). |
| Internal secret | `GW_INTERNAL_KEY` / `Ingest:InternalKey` | Shared with the ingest server; gates `/v1/admin/*`. |
| Public ingest URL | `Ingest__PublicUrl` | Shown in copy-paste snippets (default `https://ingest.twinscrollgridbalancer.co.uk`). |
| Accounts DB | `ConnectionStrings__DefaultConnection` | SQLite (`App_Data/portal.db`). |
| SMTP | `Smtp__*` | Confirmation email; blank host = log links to stdout. |

## Deploy

Both services + Caddy TLS are wired in `../compose.yml` (see `../.env.example`):

```bash
cd .. && cp .env.example .env      # set a strong GW_INTERNAL_KEY
docker compose up -d --build
```
