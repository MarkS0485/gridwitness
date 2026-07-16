"""CSV staging: append validated, allow-listed rows to hourly CSV files.

Layout (the only contract with the GDA lake):
    staging/electrical/dt=YYYY-MM-DD/HH.csv
    staging/weather/dt=YYYY-MM-DD/HH.csv

Append-only CSV with a stable header: crash-safe, trivially inspectable, zero schema migration. The
hour partition comes from the *row's* timestamp, so backfilled old data lands in the correct hour.

Dedupe here is cheap and within a recent window only — the real idempotent MERGE
(``new.combine_first(old)``) lives downstream in the GDA acquirer.
"""
from __future__ import annotations

import csv
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .privacy import ELECTRICAL_CSV_COLUMNS, WEATHER_CSV_COLUMNS


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Deduper:
    """Recent-window dedupe: remembers the last ``maxsize`` keys, evicting oldest."""

    def __init__(self, maxsize: int = 200_000):
        self.maxsize = maxsize
        self._seen: "OrderedDict[tuple, None]" = OrderedDict()
        self._lock = threading.Lock()

    def filter_new(self, rows: list[dict[str, Any]], key_fields: tuple[str, ...]) -> tuple[list[dict], int]:
        unique: list[dict[str, Any]] = []
        dups = 0
        with self._lock:
            for r in rows:
                key = tuple(r.get(k) for k in key_fields)
                if key in self._seen:
                    dups += 1
                    continue
                self._seen[key] = None
                if len(self._seen) > self.maxsize:
                    self._seen.popitem(last=False)
                unique.append(r)
        return unique, dups


class StagingWriter:
    ELECTRICAL_KEY = ("node_id", "ts_utc", "phase")
    WEATHER_KEY = ("node_id", "time")

    def __init__(self, staging_dir: Path):
        self.root = staging_dir
        self._lock = threading.Lock()
        self._dedupe = Deduper()
        self.last_write_monotonic: float | None = None

    # --- public -----------------------------------------------------------------------------------

    def write_electrical(self, rows: list[dict[str, Any]]) -> tuple[int, int]:
        unique, dups = self._dedupe.filter_new(rows, self.ELECTRICAL_KEY)
        self._append("electrical", ELECTRICAL_CSV_COLUMNS, "ts_utc", unique)
        return len(unique), dups

    def write_weather(self, rows: list[dict[str, Any]]) -> tuple[int, int]:
        unique, dups = self._dedupe.filter_new(rows, self.WEATHER_KEY)
        self._append("weather", WEATHER_CSV_COLUMNS, "time", unique)
        return len(unique), dups

    def staging_lag_s(self) -> float:
        if self.last_write_monotonic is None:
            return 0.0
        return round(time.monotonic() - self.last_write_monotonic, 3)

    # --- internal ---------------------------------------------------------------------------------

    def _path(self, kind: str, ts_field_value: str) -> Path:
        dt = _parse_iso(ts_field_value)
        return self.root / kind / f"dt={dt:%Y-%m-%d}" / f"{dt:%H}.csv"

    def _append(self, kind: str, columns: list[str], ts_field: str, rows: Iterable[dict[str, Any]]) -> None:
        # Group by target file so we open each once.
        buckets: dict[Path, list[dict[str, Any]]] = {}
        for r in rows:
            buckets.setdefault(self._path(kind, r[ts_field]), []).append(r)
        if not buckets:
            return
        with self._lock:
            for path, group in buckets.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                new_file = not path.exists()
                with path.open("a", newline="", encoding="utf-8") as fh:
                    writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
                    if new_file:
                        writer.writeheader()
                    for r in group:
                        writer.writerow({c: r.get(c) for c in columns})
            self.last_write_monotonic = time.monotonic()
