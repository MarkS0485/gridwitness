# GridWitness ingest API (v1)

The HTTP contract between any client and the standalone ingest server. Versioned under `/v1`. All
bodies are JSON. All timestamps are UTC ISO-8601 with `Z`.

> Building your own submitter? The machine-readable contract lives in [`schema/`](../schema/)
> (JSON Schema + channel catalogue + OpenAPI), and the step-by-step guide is
> [`submitters.md`](submitters.md). This page is the human-readable companion; the schema files win on
> any discrepancy.

Base URL: `http(s)://<host>:<port>` — IP-only during testing; `https://<hostname>` before public
launch (see `server/deploy/README.md`).

## Auth

Every endpoint except `/v1/register` and `/v1/health` requires a per-node bearer token:

```
Authorization: Bearer <token>
```

The token is issued once at registration and stored **hashed** (sha256) server-side. It is sent with
every batch. The `node_id` in the body must match the token's node.

---

## POST /v1/register

Issue a node identity + token. Called once by the config flow.

Request:
```json
{
  "channels": ["frequency_hz", "voltage_v"],
  "loc_tier": "anon",
  "region": null,                 // required iff loc_tier == "region" (DNO/GSP-group key)
  "postcode": null,               // required iff loc_tier == "data_share"; never stored in staging
  "device_type": "shelly_pro3em",
  "firmware": "1.4.2",
  "cadence_ms": 1000
}
```

Response `201`:
```json
{ "node_id": "b1e9…", "token": "…", "loc_ref": "GSP_SOUTH_WEST", "cell_id": "cell_51.375_-2.625" }
```

The server resolves `postcode`→`loc_ref`/`cell_id` (DATA-SHARE) or source-IP→region (ANON) at this
point, stores only the **derived** keys, and discards the postcode-to-identity link's raw location
from any published surface (it stays in the private SQLite DB).

---

## POST /v1/samples

Push a batch. Called every ~30 s by the coordinator; also used to drain the offline buffer.

Request:
```json
{
  "node_id": "b1e9…",
  "client_send_ts": "2026-07-16T14:32:35.010Z",
  "electrical": [ { "ts_utc": "…", "ts_source": "device", "phase": "1p", "frequency_hz": 49.998, … } ],
  "weather":    [ { "time": "…",   "ts_source": "ha_receive", "temp": 14.2, "rhum": 81, … } ]
}
```

Both `electrical` and `weather` are optional arrays. Rows are validated against
[`data-model.md`](data-model.md). **A row carrying a channel not in the node's consent set is
rejected** (server is the enforcement point). Dedupe is on `(node_id, ts_utc, phase)` for electrical
and `(node_id, time)` for weather within a recent window.

Response `200`:
```json
{
  "server_receive_ts": "2026-07-16T14:32:35.120Z",   // for NTP-style offset correction
  "accepted": 12,
  "duplicates": 0,
  "rejected": [ { "index": 3, "reason": "channel 'power_w' not consented" } ]
}
```

`server_receive_ts` paired with the client's `client_send_ts` and receive-of-response time gives the
client an NTP-style transport-offset estimate.

Backpressure: on overload the server returns `503` with `Retry-After`; the client buffers and
backfills. Rate abuse returns `429`.

---

## POST /v1/time-echo

Lightweight offset probe (no data).

Request: `{ "client_send": "…Z" }` → Response: `{ "client_send": "…Z", "server_receive": "…Z" }`

---

## GET /v1/health

Unauthenticated. `{ "status": "ok", "db_ok": true, "staging_lag_s": 0.2, "version": "0.1.0" }`

---

## PATCH /v1/node  (revoke / change consent)

Bearer. `{ "channels": ["frequency_hz"], "loc_tier": "anon" }` → `200 { "loc_ref": "…" }`.
Takes effect immediately; the server rejects newly-de-consented channels on the next batch.

## DELETE /v1/node  (GDPR erasure)

Bearer. Deletes the node's private record + token and writes a **tombstone** the later GDA acquirer
honours to drop already-landed lake rows. `200 { "deleted": true, "tombstoned": true }`.

---

## Error shape

All errors: `{ "error": "<machine_code>", "detail": "<human message>" }` with the matching HTTP
status (`400` validation, `401` auth, `404` unknown node, `409` conflict, `429` rate, `503` backpressure).
