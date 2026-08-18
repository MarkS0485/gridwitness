# GridWitness architecture

Three decoupled components. The CSV staging directory is the only contract between the ingest server and the GDA lake, so nothing else couples them.

1. **Home Assistant integration** (`custom_components/gridwitness/`). Discovers entities, gathers consent, captures readings, disciplines the clock via NTP, buffers, and pushes to the server.
2. **Ingest server** (`server/`). Self-hosted by the owner on a fixed IP. Validates, authenticates, rate-limits, enforces consent, deduplicates, and appends to CSV. A private SQLite database holds tokens and postcodes and is never staged.
3. **GDA acquirer** (`gda_acquirer/`). Deployed into the GDA lake later and independently. Reads the CSV files into hive-partitioned parquet, then fuses into `frequency_all_srcs` for GridSim.

## Data flow

1. Discover. The integration buckets the user's sensor entities by `device_class` into channels (frequency, voltage, current, power, weather) and infers L1/L2/L3 phase.
2. Consent. Per channel and per location tier, following the earn-the-ask matrix. The server is the enforcement point, so a row carrying an un-consented channel is rejected rather than staged.
3. Capture. Event-driven via `async_track_state_change_event`, stamped with the NTP-corrected host clock (see below).
4. Buffer and push. Batches every 30 seconds. On failure it spills to a disk buffer and drains oldest-first on reconnect, so gaps self-heal and stay visible because rows keep their original timestamps.
5. Ingest. The server validates, deduplicates on `(node_id, ts_utc, phase)`, projects each row through an allow-list (the privacy boundary), and appends to hourly CSV.
6. Land. The GDA acquirer reads CSV into hive `year=/week=` parquet with atomic writes and a non-null MERGE, clamped behind real time by `ingest_cutoff`, then fuses into `frequency_all_srcs`.

## Time and clock discipline

Everything is UTC. The `ts_utc` and `time` fields are ISO-8601 with a `Z` suffix, Home Assistant's `last_updated` is UTC-aware, NTP returns true UTC, and GDA and GridSim are UTC throughout. We deliberately avoid Europe/London local time, because a local stamp is ambiguous across the BST to GMT change while UTC never is.

Correction happens in layers, following the stamp-early principle in DESIGN section 5:

1. NTP node-clock discipline (`ntp.py`). The coordinator queries several NTP servers, takes the median offset for robustness against one bad server, refreshes every 6 hours, and applies the offset when stamping `ha_receive` samples. Device and GPS stamps are already true time and are never offset. The result is surfaced as the NTP clock offset sensor.
2. Transport offset. Every batch response echoes `server_receive_ts`, and a time-echo round trip gives an independent transport estimate, surfaced as the transport clock offset sensor.
3. NESO self-sync, on the lake side and later. Cross-correlate each node's frequency against NESO 1 second data for per-node offset, drift, and quality. Stored as calibration and never overwriting raw.

Two clocks coexist on purpose. The give-back card reads the node's live local values. GridSim's historical estimator only ingests data at least 7 days and 1 hour old via its forward-inference guard, which the acquirer honours through `ingest_cutoff`. Live on the card and historical in the model therefore never collide, and the card never reads the horizon-guarded lake.

## Privacy boundary

The server's SQLite database holds the only private data: hashed tokens, the node-to-contributor link, the raw postcode, and the IP-derived region. CSV staging rows are built from an explicit allow-list, so postcode, latitude, longitude, token, and identity cannot reach a staging file. This is proven by `test_postcode_never_reaches_staging` and by the end-to-end `test_loop`. Only derived coarse keys travel with the data: `loc_ref` (GSP group or substation) and `cell_id` (a 0.25 degree grid cell).

## What runs where

| Concern | Component |
|---|---|
| Entity discovery, consent UI, capture, NTP, buffering, give-back | HA integration |
| Auth, rate-limit, validation, consent enforcement, dedupe, CSV, postcode to loc_ref, IP to region | Ingest server |
| CSV to parquet, hive partitioning, MERGE, horizon clamp, schema gate, frequency_all_srcs, calibration | GDA acquirer (later) |
