"""Disk-backed offline buffer (append-only NDJSON).

When a push fails (server down, network out), rows are appended here and drained oldest-first on
reconnect, so gaps self-heal. Rows keep their ORIGINAL timestamps, so a missing window stays visible
downstream rather than being back-dated — a detectable gap, by design.

Pure/sync and HA-free so it is unit-testable; the coordinator runs its file IO in an executor.
Each line: {"kind": "electrical"|"weather", "row": {...}, "buffered_ts": "<iso>"}.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class DiskBuffer:
    def __init__(self, path: Path, *, max_rows: int, max_age_h: int):
        self.path = Path(path)
        self.max_rows = max_rows
        self.max_age_h = max_age_h
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # --- write ------------------------------------------------------------------------------------

    def append(self, items: list[tuple[str, dict]], now_iso: str) -> None:
        if not items:
            return
        with self.path.open("a", encoding="utf-8") as fh:
            for kind, row in items:
                fh.write(json.dumps({"kind": kind, "row": row, "buffered_ts": now_iso}) + "\n")

    # --- read / commit ----------------------------------------------------------------------------

    def count(self) -> int:
        if not self.path.exists():
            return 0
        with self.path.open("r", encoding="utf-8") as fh:
            return sum(1 for _ in fh)

    def peek(self, max_rows: int) -> list[tuple[str, dict]]:
        """Return up to ``max_rows`` oldest items without removing them."""
        if not self.path.exists():
            return []
        out: list[tuple[str, dict]] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if len(out) >= max_rows:
                    break
                try:
                    rec = json.loads(line)
                    out.append((rec["kind"], rec["row"]))
                except (json.JSONDecodeError, KeyError):
                    continue  # skip a corrupt line rather than wedge the buffer
        return out

    def commit(self, n: int) -> None:
        """Remove the first ``n`` lines (the ones just successfully pushed). Atomic rewrite."""
        if n <= 0 or not self.path.exists():
            return
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with self.path.open("r", encoding="utf-8") as src, tmp.open("w", encoding="utf-8") as dst:
            for i, line in enumerate(src):
                if i >= n:
                    dst.write(line)
        os.replace(tmp, self.path)

    def prune(self, now: datetime) -> int:
        """Enforce age + row caps, dropping oldest. Returns number of rows dropped."""
        if not self.path.exists():
            return 0
        cutoff = now - timedelta(hours=self.max_age_h)
        kept: list[str] = []
        dropped = 0
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                    if _parse_iso(rec["buffered_ts"]) < cutoff:
                        dropped += 1
                        continue
                except (json.JSONDecodeError, KeyError, ValueError):
                    dropped += 1
                    continue
                kept.append(line)
        if len(kept) > self.max_rows:
            dropped += len(kept) - self.max_rows
            kept = kept[-self.max_rows:]        # keep the newest max_rows
        if dropped:
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as dst:
                dst.writelines(kept)
            os.replace(tmp, self.path)
        return dropped
