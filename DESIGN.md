# GridWitness — crowd-sourced GB grid measurement via Home Assistant

**Working title (provisional).** A citizen-science network that turns the metering hardware Home
Assistant users already own — smart plugs, 3-phase energy meters, inverters, and (for the keen) DIY
GPS PMUs — into a distributed, UTC-timestamped measurement fabric for the GB grid. Feeds the GDA lake
as a new distributed source and gives GridSim real ground truth for frequency, voltage, and (fused with
the model) phase-angle dynamics.

**North star:** *breadth the professional networks don't have.* Four gridradar PMUs cost £thousands;
four hundred amateur nodes cost nothing and cover the whole island. We don't replace PMUs — we build the
thing nobody has: geographic density.

---

## 0. What we learned upstream (the design is downstream of these)

- **Frequency is global, voltage/angle are local.** Frequency (and its self-sync value) works from any
  node; voltage/current/angle only mean something once you know *where on the network* the node sits.
- **Clock *offset* is correctable, *jitter* is not.** You can only fix latency that happens *after* the
  first timestamp — so stamp as close to the sensor as possible, then correct transport offset, then
  self-sync against a shared reference.
- **The grid frequency signal IS a free distributed clock.** Cross-correlate any node's frequency against
  NESO's public 1s national trace (already in the lake); the lag that aligns them is that node's clock
  error. Self-syncs the whole fleet with no GPS.
- **Model = DC, crowd = AC, one anchor kills the offset.** The load-flow model supplies the standing angle
  field; distributed frequency supplies the dynamics; a single GPS-referenced node collapses the absolute
  offset for everyone. So the network needs *many cheap nodes + one good anchor*, not many good nodes.
- **Privacy is the uptake lever, not an afterthought.** Frequency + voltage are low-sensitivity; current +
  power reveal household load. Consent is therefore *per-channel*, and location is *tiered*.

---

## 1. Node tiers (what a contributor can be)

| Tier | Hardware (examples) | Gives us | Sync quality |
|---|---|---|---|
| **T1 — Frequency node** | Any freq-capable meter (Shelly, Tasmota/ESPHome w/ ADE7953, some inverters) | system frequency @1–5s | self-sync vs NESO 1s |
| **T2 — Rich node (3-phase)** | Shelly Pro 3EM, Emporia Vue 3φ, ESPHome CT banks, Modbus industrial meters | per-phase V, I, P, PF, freq | self-sync; feeder-located if DATA-SHARE |
| **T3 — PMU node (anchor)** | DIY GPS PMU (OpenPMU / Red Pitaya / Teensy+GPS-PPS) | phase angle vs UTC, RoCoF, V, I | GPS-PPS, <1µs — the timing anchor |

3-phase support is first-class (many target users are on 3φ supplies or industrial sites). T3 is the
premium/anchor tier; even a handful of T3 nodes anchor the whole T1/T2 fleet.

---

## 2. Data model (what we collect)

Per node, per sample (long/tidy, one row per phase where applicable):

```
node_id            stable anonymous id (random, not derived from anything personal)
ts_utc             UTC timestamp — source-stamped if the device provides it, else HA receive time
ts_source          "device" | "ha_receive" | "gps"   (quality flag — how trustworthy the time is)
phase              "L1" | "L2" | "L3" | "1p"          (single-phase collapses to 1p)
voltage_v          RMS volts                          (low privacy)
current_a          RMS amps                           (opt-in — reveals load)
power_w            real power                         (opt-in — reveals load)
power_factor       -                                  (opt-in)
frequency_hz       system frequency (node-global, not per phase)
phase_angle_deg    T3 only — synchrophasor angle vs UTC reference
device_type        e.g. "shelly_pro3em", "openpmu", "esphome_ade7953"
firmware / chip    for calibration cohorts
cadence_ms         nominal reporting interval
loc_tier           "anon" | "region" | "data_share"
loc_ref            derived location key (GSP group / primary substation / feeder id) — NEVER the postcode
```

Server-side only (never published, never in the dataset rows): the raw postcode/lat-lon (DATA-SHARE), the
node↔contributor mapping, and the auth token. Published/lake data carries only the *derived* `loc_ref`.

---

## 3. Privacy modes (contributor sets these)

Consent is **per-channel** (share freq only / +voltage / +current+power) **and** location is **tiered**:

- **ANON-MODE** — no GPS, no postcode. Rough region from **IP geolocation** → GSP region / DNO area only.
  Node id random+stable. *Fully useful for frequency* (location-independent); voltage/current usable as
  anonymous distribution samples but **unpinnable to a feeder**. "Still useful, somewhat limited."
- **REGION-MODE** (optional middle) — user *picks* their DNO/GSP region from a list. Better than IP, no
  address. Good for regional frequency/voltage mapping.
- **DATA-SHARE MODE** — user enters **postcode** (or precise location). Backend maps postcode → GSP group →
  primary substation → **feeder** using public data (postcode↔GSP lookup, DNO network/boundary data,
  Embedded Capacity Registers). Unlocks **feeder-level pinning** — the thing that makes voltage and angle
  data scientifically valuable (you know *where on the network* it is). Postcode stays server-side private;
  only the derived feeder/GSP id ever leaves.

Default = ANON + frequency-only. Everything above it is an explicit, revocable opt-in.

---

## 4. The Home Assistant module

**Form:** a **HACS custom integration** (Python, `domain: gridwitness`) — works on *all* HA installs
(Core / Container / OS), unlike an add-on. Optional companion **add-on** later for T3 nodes that need
local DSP (synchrophasor math) or high-rate handling.

**What it does, end to end:**
1. **Config flow (UI):** contributor installs from HACS, opens the integration. It **auto-discovers**
   entities by `device_class` (`voltage`, `current`, `frequency`, `power`, `power_factor`) and proposes a
   mapping (L1/L2/L3 V·I·P·PF + system frequency). Manual override + templates for odd setups.
2. **Consent screen:** pick channels to share (freq / +V / +I·P) and location tier (anon / region /
   data-share + postcode). Plain-English, revocable, links to the privacy statement.
3. **Extraction:** subscribe to `state_changed` for the mapped entities (event-driven, not polling) →
   capture value + `last_updated` (UTC) + source timestamp if the device exposes one.
4. **Batch + buffer:** accumulate locally, push every N s (default ~30 s) to the ingest API over HTTPS with
   the node token. **Buffer to disk when offline; backfill on reconnect** (gaps self-heal, stay detectable).
5. **Give-back dashboard:** a local Lovelace card — "your node vs the grid," your frequency trace over the
   national one, your contribution stats, event catches ("you saw the 14:32 dip 400 ms before London").
   Retention is a feature.

**T3 / PMU path:** a GPS-synced node timestamps at source and can push straight to the API as a `pmu`
node type (`phase_angle_deg` + `ts_source=gps`), or via the add-on if it wants HA to broker it. We accept
a simple `{ts_utc, phase_angle_deg, freq_hz, v, i}` schema *and* can ingest C37.118-style streams later.

---

## 5. Time & sync (the pipeline that makes it coherent)

1. **Stamp early.** Prefer device/source timestamps. For flashable devices (ESPHome/Tasmota) we can ship a
   config that stamps at sample time via SNTP — moves the first timestamp *before* HA buffering.
2. **Correct transport offset.** The ingest protocol carries client-send + server-receive timestamps →
   NTP-style estimate of each node's clock offset, corrected server-side.
3. **Self-sync against NESO.** Calibration service cross-correlates each node's frequency against the lake's
   NESO 1s trace in a rolling window → per-node clock offset *and* drift, without GPS. Tens-of-ms alignment
   in quiet periods.
4. **GPS anchors (T3).** PMU nodes carry UTC-true time and become the fleet's absolute timing references;
   everything else is self-synced relative to them + NESO.

Honest ceiling: this gives an excellent **frequency map** and event **detection/ordering**; clean
**propagation delays** still want T3 GPS nodes — which is exactly why T3 exists.

---

## 6. Backend & ingest → GDA lake

```
HA module ──HTTPS(token)──▶ Ingest API ──▶ staging store ──▶ GDA ingester ──▶ lake
                                │                                  │
                          rate-limit, auth,                 calibration service
                          validate, dedupe                (freq×NESO, δ×P regression)
```

- **Ingest API:** small authed HTTPS service. Per-node token (issued at registration). Validates schema,
  rate-limits per node, dedupes on `(node_id, ts_utc, phase)`, lands raw into a staging store. Echoes
  timestamps for offset correction.
- **GDA ingester:** batches staging → lake dataset **`Community/gridwitness`**, following GDA conventions
  (parquet hive `year=/week=`, atomic `tmp + os.replace`, MERGE preferring non-null, `check_written` schema
  gate, single-instance, `SOURCE_DATASETS` + `DataSchema.json` registration — same pattern as the existing
  gridradar/eirgrid acquirers).
- **Calibration service:** per node — (a) frequency bias/offset/drift vs NESO 1s; (b) for DATA-SHARE nodes
  that share power, regress `δ` (or voltage) against their *own* known P/Q → back out connection impedance
  / grid strength and the sensor phase error; (c) per-node quality score + outlier rejection. Calibration
  state is stored and applied, never silently overwriting raw.

---

## 7. Calibration & QA (why the data is trustworthy)

- **Frequency:** trivially trued against NESO 1s.
- **Voltage/phase self-calibration:** a node that shares its own P/Q is self-calibrating — regress the
  measured angle/voltage against known injected power over a week; the slope is the local network impedance,
  the residual is the instrument error. (Nodes at weak radial ends have *large* dδ/dP → strongest signal.)
- **Cohort calibration:** group by chip/firmware to model systematic per-device biases.
- **Quality score** per node (sync confidence, cadence stability, agreement with neighbours) → downstream
  consumers can weight or filter.

---

## 8. Consent, legal, trust

- **Opt-in, revocable, minimal.** Default anon + frequency-only. Every escalation is explicit.
- **GDPR:** postcode/precise location is personal data → stored server-side, encrypted, never published;
  only derived feeder/GSP ids leave. Current/power reveal household load → per-channel consent, coarsening
  options. Clear privacy statement + data-deletion path. Likely legitimate-interest + explicit-consent basis.
- **Transparency:** open about what's collected, why, and what's shared. Open-source the module (trust +
  contributions). This is the difference between people leaving it running and uninstalling it.

---

## 9. Roadmap (phased, MVP-first)

- **P0 — Frequency MVP:** HA integration (T1), anon-mode, ingest API, `Community/gridwitness` frequency
  dataset, NESO self-sync, basic give-back card. Proves the loop end to end with the easy tier.
- **P1 — Rich + location:** T2 3-phase channels, REGION + DATA-SHARE modes, postcode→feeder mapping,
  δ-vs-P self-calibration, quality scoring.
- **P2 — Anchor tier:** T3 PMU node spec (fork OpenPMU), GPS-stamped ingest, propagation/observatory
  analysis, fusion with the GridSim model (crowd AC + model DC + T3 anchor).
- **P3 — Scale & community:** onboarding, dashboards, recruitment page, contributor leaderboard, event
  catalogue ("the fleet saw event X propagate thus").

---

## 10. Open decisions (need answers before P0 code)

1. **Hosting** for the ingest API + staging (self-host on your infra vs a small cloud service). Affects auth,
   scale, cost.
2. **Name** (GridWitness is a placeholder) — matters for the HACS `domain` and public identity.
3. **postcode→feeder** data source: which public dataset(s) for the mapping, and how precise we can honestly
   get (GSP group is easy; true feeder needs DNO LV data — may only be primary-substation granularity).
4. **How much runs in the module vs the backend** — do we push raw and calibrate centrally (simpler module,
   more bandwidth) or pre-aggregate on-device (leaner, but harder to recalibrate retrospectively)? Leaning:
   push near-raw, calibrate centrally, so we can re-derive as methods improve.
5. **T3 reference design**: publish our own OpenPMU-based BOM + firmware, or just define the ingest contract
   and let builders bring their own?
```
