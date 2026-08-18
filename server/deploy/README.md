# Deploying the GridWitness ingest server (self-hosted at home)

The server is a single FastAPI app. It writes CSV staging files and a private SQLite database under `server_data/` (override with `GW_DATA_DIR`). It has no dependencies beyond the Python packages in `pyproject.toml`.

## Quick start (local or LAN testing, IP only)

```bash
cd server
python -m venv .venv && . .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e .[dev]
python -m gridwitness_server.main                  # binds 0.0.0.0:8000
curl http://localhost:8000/v1/health
```

Environment variables:

| var | default | meaning |
|---|---|---|
| `GW_HOST` | `0.0.0.0` | bind address |
| `GW_PORT` | `8000` | bind port |
| `GW_DATA_DIR` | `server/server_data` | root for SQLite DB and CSV staging |
| `GW_DB_PATH` | `<data>/gridwitness.db` | private SQLite DB |
| `GW_STAGING_DIR` | `<data>/staging` | CSV staging tree |
| `GW_RATE_ROWS_PER_MIN` | `6000` | per-node rate cap |
| `GW_GEOIP_MMDB` | unset | optional MaxMind GeoLite2 db for the anon tier (P1) |

## Home box, fixed IP, current posture (IP only)

For early testing you can forward ports 443 and 8000 from the router to the box and point Home Assistant nodes at `http://<fixed-ip>:8000`. On a trusted LAN, plain HTTP is acceptable. This is a testing posture, not a launch posture. See the TLS gate below.

## Pre-launch gate: real TLS before any public contributor

Contributor tokens must never cross the internet in cleartext. Before onboarding anyone outside the LAN:

1. Point a DNS A record for `ingest.twinscrollgridbalancer.co.uk` at the fixed IP.
2. Front uvicorn with Caddy for an automatic Let's Encrypt certificate. A ready-to-use `Caddyfile` is in this folder. Run `caddy run` (or install Caddy as a service). Caddy fetches and auto-renews the certificate. uvicorn stays bound to `127.0.0.1:8000`, Caddy terminates TLS. The Home Assistant client then trusts the server through the normal public CA chain, with no custom certificate handling in the integration.
3. Set the integration's server URL to `https://ingest.twinscrollgridbalancer.co.uk` (and turn off "allow insecure").

## Running as a service

On Linux, use a systemd unit running `python -m gridwitness_server.main` with `Restart=always`, `WorkingDirectory` set to the `server/` directory, and an `EnvironmentFile` for the variables above. On Windows, run under [NSSM](https://nssm.cc/) pointing at `python.exe -m gridwitness_server.main`, or a Scheduled Task at logon with restart on failure.

## Backups and privacy hygiene

`gridwitness.db` holds the only private data (hashed tokens, node-to-contributor link, raw postcodes). Back it up encrypted, and encrypt it at rest with full-disk encryption or an encrypted volume. The CSV staging tree contains no private fields by construction (the allow-list projection), so it is safe to hand to the GDA acquirer. For GDPR erasure, `DELETE /v1/node` removes the private record and token and writes a tombstone the acquirer honours to drop already-landed lake rows.
