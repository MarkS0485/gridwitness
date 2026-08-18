# GridWitness survey ingester

Out-of-band worker that drains the survey-file upload inbox the ingest server fills, extracts **only
frequency and voltage** from each file, and appends them to the CSV staging tree the GDA acquirer
reads. It is the survey sibling of `gda_acquirer/`: scheduled, single-instance, file-based, and it
never touches the parquet lake itself.

```
staging/surveys/inbox/<node_id>/    <- POST /v1/survey/upload drops raw files + manifest here
        │
        ▼   survey_ingest.py
staging/electrical/dt=…/HH.csv       <- projected frequency+voltage rows (acquirer picks these up)
staging/surveys/archive/<node_id>/   <- raw originals moved here + extracted_*.csv (for user export)
```

## What it does per survey

1. Load the survey node from the private DB. **If it's gone (withdrawn), purge inbox + archive and
   stage nothing** — this honours GDPR erasure.
2. Parse each file (`parsers.py`):
   - **CSV / TXT / TSV**: fuzzy-match the timestamp, voltage and frequency columns; **ignore every
     other column**. That whitelist is where "only frequency and voltage leave" is enforced.
   - **PQDIF** (`.pqd/.pqdif`): convert to CSV first via the `pqdif2csv` tool (see `../tools/pqdif2csv`).
3. Project each row through the server's privacy allow-list (`project_electrical`) and append to
   staging. Out-of-band values (freq outside 40–70 Hz, implausible voltage) are dropped and counted.
4. Write `extracted_*.csv` next to the archived originals, so the account's data export is complete
   without any lake read.
5. Move originals to `archive/`, mark the manifest `processed`.

## Configuration (environment)

Reuses the ingest server's settings, so paths line up automatically:

| var | meaning | default |
|-----|---------|---------|
| `GW_DATA_DIR` / `GW_STAGING_DIR` / `GW_DB_PATH` | same as the server | server defaults |
| `GW_SERVER_PATH` | where the `gridwitness_server` package lives | `../server` |
| `GW_PQDIF2CSV` | path to the `pqdif2csv` tool (else looked up on PATH) | unset → PQDIF skipped |

If `pqdif2csv` is not available, CSV/TXT files still process normally; PQDIF files are marked rejected
in the manifest with a reason (never a crash).

## Run

```bash
python survey_ingest.py             # drain the inbox once
python survey_ingest.py --selftest  # offline round-trip in a temp dir, no real data
python -m pytest                    # unit + end-to-end pipeline tests
```

## Schedule

Register it on the same cadence as the acquirer, staggered so it runs *before* the acquisition
cycle (surveys land in staging, then the acquirer lands them in the lake). Single-instance lock is a
localhost socket on **:47832** (gridradar 47829 / gw_acquire 47830 / powergridfreq 47831 / survey
47832), so overlapping schedules are safe — a second copy exits immediately.

Example (Windows Task Scheduler, every 15 min):

```
schtasks /Create /TN GDA_GridWitness_Survey /SC MINUTE /MO 15 ^
  /TR "python D:\apps\gridwitness\survey_ingest\survey_ingest.py"
```

In the Docker deploy this runs as a small scheduled sidecar sharing the ingest server's `/data`
volume; see the repo `compose.yml`.
