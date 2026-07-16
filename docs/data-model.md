# GridWitness data model (the row schemas)

This is the single source of truth for the shape of the data. The HA client, the ingest server, and the later GDA acquirer all code to this document. There are two row shapes: electrical and weather.

## Conventions

Timestamps are UTC, ISO-8601 with a `Z` suffix (for example `2026-07-16T14:32:05.250Z`). Milliseconds are allowed. Electrical rows use `ts_utc`. Weather rows use `time`, to match GDA's existing weather subsystem, which keys on `time`.

There is one row per phase where applicable (long and tidy). Single-phase collapses to `phase="1p"`. Frequency is node-global rather than per-phase, so it is carried on one row per node per sample with `phase="1p"` (or on the L1 row for a 3-phase node) and never duplicated across L1, L2, and L3.

Nulls are allowed for any un-shared or unmeasured channel. Downstream MERGE prefers non-null, so a null never overwrites a real stored value.

## Electrical row

| field | type | unit / values | privacy | notes |
|---|---|---|---|---|
| `node_id` | str | random UUID | n/a | stable, not derived from anything personal |
| `ts_utc` | str | ISO-8601 UTC | n/a | source-stamped if the device provides it, else HA receive time |
| `ts_source` | enum | `device`, `ha_receive`, `gps` | n/a | how trustworthy the time is |
| `phase` | enum | `L1`, `L2`, `L3`, `1p` | n/a | |
| `voltage_v` | float? | RMS volts | low | |
| `current_a` | float? | RMS amps | high | opt-in, reveals load |
| `power_w` | float? | real power W | high | opt-in, reveals load |
| `power_factor` | float? | -1 to 1 | high | opt-in |
| `frequency_hz` | float? | Hz (about 49 to 51) | none | node-global |
| `phase_angle_deg` | float? | degrees | low | T3/PMU only, P2 |
| `device_type` | str | for example `shelly_pro3em` | n/a | calibration cohort |
| `firmware` | str? | firmware or chip id | n/a | calibration cohort |
| `cadence_ms` | int? | nominal reporting interval | n/a | |
| `loc_tier` | enum | `anon`, `region`, `data_share` | n/a | |
| `loc_ref` | str? | GSP group or primary-substation id | n/a | derived, never a postcode |

## Weather row

| field | type | unit / values | notes |
|---|---|---|---|
| `node_id` | str | random UUID | same node id space as electrical |
| `time` | str | ISO-8601 UTC | note `time`, not `ts_utc` |
| `ts_source` | enum | `device`, `ha_receive` | |
| `temp` | float? | degrees C | ambient outdoor |
| `rhum` | float? | percent relative humidity | matches GDA Meteostat `rhum` |
| `wspd` | float? | km/h | wind speed (note measurement height, see below) |
| `wdir` | float? | degrees, meteorological "from" (0=N, 90=E) | |
| `pres` | float? | hPa | matches GDA Meteostat `pres` |
| `prcp` | float? | mm | rainfall, matches GDA Meteostat `prcp` |
| `solar_radiation_w_m2` | float? | W/m2 | shortwave irradiance |
| `uv` | float? | UV index | currently absent from GDA, so net-new |
| `device_type` | str | for example `ecowitt_gw2000` | |
| `loc_tier` | enum | `anon`, `region`, `data_share` | |
| `loc_ref` | str? | GSP group or primary-substation id | derived |
| `cell_id` | str? | 0.25 degree grid cell, for example `cell_51.375_-2.625` | derived server-side |

Wind is typically measured at about 2 m or 10 m on home stations, whereas GDA's canonical wind is at 100 m (`Wind_Speed_100m_kph`). The raw measured value is stored as-is with `device_type`, and height normalisation is a downstream concern in the acquirer or a derived dataset, not something the client fakes.

## Server-only fields (never in any published row or CSV staging file)

* raw postcode and latitude/longitude (data-share)
* the node-to-contributor mapping
* the auth token (stored hashed)
* the source IP, used once to derive a coarse region at registration, then discarded

The server projects each incoming row through an explicit allow-list into the CSV, so these fields are structurally incapable of reaching staging.
