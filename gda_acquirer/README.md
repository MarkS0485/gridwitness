# GDA acquirer for GridWitness

The bridge from the ingest server's CSV staging into the GDA lake. **Designed here, deployed into GDA
later and independently** — the ingest server writes CSV regardless of whether this ever runs, and
this reads CSV without ever calling the server. The CSV staging directory is the only contract.

## Files

| File | Purpose |
|---|---|
| `gridwitness_acquire.py` | The acquirer. Faithful to `Ingest/gridradar/gridradar_acquire.py`. |
| `config.example.json` | Copy to `config.json`; set `staging_dir`. |
| `DataSchema.entries.json` | Two dataset objects to append to GDA's `DataSchema.json`. |
| `lake_paths.patch.md` | Every GDA-side edit (lake_paths.py, DataSchema.json, lake_unify.py, scheduling). |

## What it does

Reads `staging/electrical/dt=…/HH.csv` and `staging/weather/dt=…/HH.csv`, lands two hive `year=/week=`
parquet datasets with atomic writes and non-null MERGE (`combine_first`), clamps to
`Scripts.horizon.ingest_cutoff` so the lake stays behind real time (the give-back card is live and
unaffected), and best-effort-checks each write against the schema gate.

## Verify without touching the lake

```bash
python gridwitness_acquire.py --selftest      # offline CSV->parquet->read-back + idempotent MERGE
```

It auto-discovers the GDA root (or pass `--gda-root D:/Work/GDA/v1` / set `GDA_ROOT`) and uses the
real `Scripts.parquet_partitioning` helpers, writing only to a temp dir.

## Deploy (when ready)

1. Apply every edit in `lake_paths.patch.md`.
2. Copy `gridwitness_acquire.py` to `D:\Work\GDA\v1\Ingest\gridwitness\`.
3. `cp config.example.json config.json` and set `staging_dir`.
4. `python gridwitness_acquire.py --selftest`, then a real run.
5. Register the `GDA_GridWitness` scheduled job (lock port 47830).

## Run

```bash
python gridwitness_acquire.py                 # reads config.json staging_dir, lands to the lake
python gridwitness_acquire.py --no-horizon    # ingest right up to now (testing only)
```
