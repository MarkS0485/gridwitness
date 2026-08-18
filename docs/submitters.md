# Writing your own GridWitness submitter

GridWitness is not tied to Home Assistant. Anyone with grid or weather measurements can submit them:
a data historian, a mobile app, a fleet of meters, a bespoke PMU, or your own script. This page is the
guide for building a submitter against the published, versioned schema.

You do not need to run the server or read its source. Everything is defined by machine-readable
artifacts in [`schema/`](../schema/):

| File | What it is |
|---|---|
| [`gridwitness-ingest.v1.schema.json`](../schema/gridwitness-ingest.v1.schema.json) | JSON Schema (draft 2020-12) for every request and response body. |
| [`channels.v1.json`](../schema/channels.v1.json) | The channel catalogue: every field you may send, with unit, type, and sensitivity. |
| [`openapi.json`](../schema/openapi.json) | OpenAPI 3 spec for the ingest API. Import it into Postman, generate a client, etc. |

The human-readable contract is [`ingest-api.md`](ingest-api.md) and the row shapes are in
[`data-model.md`](data-model.md). Where any of those disagree with the schema files, the schema files
win: they are generated from the server's models.

## Concepts

- **Node.** One measurement point or stream. If you have many sites or devices, register one node per
  site. A node has a random `node_id` and a bearer token, both issued at registration.
- **Channels.** The named quantities you send, listed in `channels.v1.json`. Electrical channels
  (`frequency_hz`, `voltage_v`, `current_a`, `power_w`, `power_factor`, `phase_angle_deg`) and weather
  channels (`temp`, `rhum`, `wspd`, `wdir`, `pres`, `prcp`, `solar_radiation_w_m2`, `uv`).
- **Consent set.** The channels a node is allowed to send, chosen at registration. The server rejects
  any row carrying a channel outside the set, so you cannot accidentally over-submit.
- **Producer.** A string naming your software, for example `acme-energy-app/2.3`. Set it at
  registration so we can attribute and support your data.

## The three steps

### 1. Register a node

`POST /v1/register` with the channels you intend to send, a location tier, and your producer id.

```bash
curl -X POST https://ingest.twinscrollgridbalancer.co.uk/v1/register \
  -H 'content-type: application/json' \
  -d '{
    "channels": ["frequency_hz", "voltage_v"],
    "loc_tier": "region",
    "region": "SOUTH_WEST",
    "device_type": "acme_meter_x1",
    "producer": "acme-energy-app/2.3",
    "schema_version": "1.0"
  }'
```

Response gives you `node_id`, `token`, and the derived `loc_ref`/`cell_id`. Store the token securely;
it is shown once. Location tiers: `anon` (rough region from your IP), `region` (you pass a `region`
key), `data_share` (you pass a `postcode`; it is used server-side to derive a coarse area code and is
never published).

### 2. Send batches

`POST /v1/samples` with a Bearer token. Timestamps are UTC ISO-8601 with a `Z`. Electrical rows use
`ts_utc`; weather rows use `time`. One row per phase where applicable; single phase is `1p`.

```bash
curl -X POST https://ingest.twinscrollgridbalancer.co.uk/v1/samples \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{
    "node_id": "'"$NODE_ID"'",
    "client_send_ts": "2026-07-16T14:32:35.010Z",
    "schema_version": "1.0",
    "electrical": [
      {"ts_utc": "2026-07-16T14:32:05.250Z", "ts_source": "device", "phase": "1p", "frequency_hz": 49.998, "voltage_v": 241.2}
    ]
  }'
```

The response echoes `server_receive_ts` (pair it with your `client_send_ts` and the time you receive
the reply for an NTP-style transport offset), plus `accepted`, `duplicates`, and any `rejected` rows
with reasons.

### 3. Handle the responses

- **Deduplication.** Rows are idempotent on `(node_id, ts_utc, phase)` for electrical and
  `(node_id, time)` for weather. Re-sending the same row is safe; it counts as a duplicate, not an
  error. This is what makes retries and backfill safe.
- **Backpressure.** `503` with `Retry-After` means the server is busy. Buffer and retry later.
- **Rate limit.** `429` means you are sending too fast for this node. Back off.
- **Validation.** `400` with a per-row `rejected` list tells you exactly what was wrong (bad units,
  an un-consented channel, an implausible value).

## Bulk and historical backfill

Rows keep their original timestamps, so you can submit history as well as live data. Send older
`ts_utc`/`time` values freely; a gap in coverage stays visible downstream rather than being papered
over. Chunk large uploads into batches (a few thousand rows each is a good default) and rely on the
dedupe key for safe resumes. Note that data reaches the research lake with a deliberate delay, so
historical backfill is expected and welcome.

## Units and validation

Send values in the exact units in `channels.v1.json` (volts, amps, watts, Hz, degrees C, km/h, hPa,
mm, W/m2). Frequency is validated to a plausible 40 to 70 Hz. Do not pre-scale or normalise; send what
you measured with an accurate `device_type` so calibration can happen centrally.

## Privacy obligations for submitters

If you are submitting on behalf of other people, honour the same deal the HA integration makes:

- Only register the channels the person agreed to share. Current and power reveal household load, so
  they must be an explicit opt-in, never a default.
- Never put personal data in rows. Location is handled at registration only (postcode goes to the
  server, which returns a coarse `loc_ref`; the postcode is never echoed into submitted data).
- Support withdrawal. `PATCH /v1/node` changes a node's consent; `DELETE /v1/node` erases it.

## Versioning

`schema_version` is `1.0`. Send it in both `register` and `samples`. Additive changes (new optional
channels) will not bump the major version. Breaking changes will publish a `v2` schema alongside `v1`;
`v1` submitters keep working until a deprecation window is announced.

## Regenerating the schema

Maintainers regenerate the artifacts from the models with:

```bash
cd server && python -m gridwitness_server.schema_export
```
