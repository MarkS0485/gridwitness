# GDA registration edits for GridWitness

Apply these when deploying the acquirer into the GDA lake. All paths are under `D:\Work\GDA\v1`.
None of this runs from the GridWitness repo. It is the record of what to change in GDA.

## 1. `MachineLearning/lake_paths.py`

Add two dir constants near the other `*_PARQUET_DIR` definitions (under `DATA_SOURCES_ROOT`):

```python
GRIDWITNESS_ELECTRICAL_PARQUET_DIR = DATA_SOURCES_ROOT / "GridWitness" / "Parquet" / "gw_electrical"
# hive year=/week=; tidy per-phase crowd electrical (frequency/voltage/current/power) from HA nodes
GRIDWITNESS_WEATHER_PARQUET_DIR = DATA_SOURCES_ROOT / "GridWitness" / "Parquet" / "gw_weather"
# hive year=/week=; Meteostat-shaped crowd weather (temp/rhum/wspd/wdir/pres/prcp/irradiance/uv)
```

Then add two entries to the `SOURCE_DATASETS` dict:

```python
    "gridwitness_electrical": GRIDWITNESS_ELECTRICAL_PARQUET_DIR,
    "gridwitness_weather":    GRIDWITNESS_WEATHER_PARQUET_DIR,
```

## 2. `DataSchema.json`

Append the two objects in `DataSchema.entries.json` (this folder) to the top-level `datasets` array.
Run `python Scripts/validate_data_schema.py` afterwards. Until then the schema gate logs
`uncontracted dataset GridWitness/... - passing` (WARN, never fatal), which is exactly what the
acquirer `--selftest` shows today.

## 3. `Scripts/lake_unify.py`: make GridWitness visible to GridSim

Add a source dict to the `frequency_all_srcs` config so crowd frequency fuses with the NESO 1 s
series (this is the "reaches GridSim" milestone):

```python
{
    "id": "gridwitness",
    "class": "crowd",
    "cadence": "1-5s",
    "path_attr": "GRIDWITNESS_ELECTRICAL_PARQUET_DIR",
    "partition": "year_week",
    "ts": {"kind": "utc", "col": "ts_utc"},
    "map": {"frequency_hz": "frequency_hz"},
}
```

## 4. Scheduling: a `GDA_GridWitness` Task Scheduler job via `headless_run.py`

```
"<pythonw>" "D:\Work\GDA\v1\Ingest\headless_run.py" ^
  "D:\Work\GDA\v1\Ingest\logs\gridwitness.log" ^
  "D:\Work\GDA\v1\Ingest\gridwitness" ^
  gridwitness_acquire.py
```

Note the fresh single-instance lock port **47830** in `RUNBOOK.md` (verify no live collision).

## 5. Deploy the acquirer

Copy `gridwitness_acquire.py` to `D:\Work\GDA\v1\Ingest\gridwitness\gridwitness_acquire.py` and add a
`config.json` (from `config.example.json`) pointing `staging_dir` at the ingest server's CSV staging
root. Verify with `python gridwitness_acquire.py --selftest`.

## 6. (Later) NESO self-sync calibration + GDPR tombstones

- A `--calibrate` post-step / `Scripts/build_gridwitness_calibration.py` cross-correlates each node's
  `frequency_hz` against `lake_paths.FREQUENCY_PARQUET_DIR` (NESO 1 s `dtm`/`f`) → per-node
  offset/drift/quality into `DataSources/Derived/gridwitness_calibration/`. Never overwrites raw.
- Honour the ingest server's erasure tombstones (`DELETE /v1/node`) to drop already-landed rows for a
  deleted node.
