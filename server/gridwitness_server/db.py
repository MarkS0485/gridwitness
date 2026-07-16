"""SQLite private store.

Holds ONLY the private/relational data: node records, hashed tokens, the node<->contributor link,
and the raw postcode (data-share tier). None of this is ever written to CSV staging — the staging
projection (privacy.py) works from an explicit allow-list, not from these tables.

Sync sqlite3 behind a lock. Route handlers touching the DB are declared ``def`` so FastAPI runs them
in its threadpool and the event loop is never blocked. Fine for a single home box.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    node_id      TEXT PRIMARY KEY,
    created_utc  TEXT NOT NULL,
    device_type  TEXT,
    firmware     TEXT,
    cadence_ms   INTEGER,
    loc_tier     TEXT NOT NULL,
    loc_ref      TEXT,
    cell_id      TEXT,
    channels     TEXT NOT NULL,          -- JSON array of consented channel names
    deleted_utc  TEXT                    -- NULL unless erased
);
CREATE TABLE IF NOT EXISTS tokens (
    node_id       TEXT PRIMARY KEY,
    token_sha256  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS node_private (
    node_id         TEXT PRIMARY KEY,
    postcode        TEXT,               -- raw, data-share only; never published
    raw_region      TEXT,               -- IP-derived coarse region; never published
    contributor_ref TEXT                -- reserved for a future accounts system
);
CREATE TABLE IF NOT EXISTS tombstones (
    node_id         TEXT PRIMARY KEY,
    tombstoned_utc  TEXT NOT NULL       -- honoured by the GDA acquirer to drop landed rows
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- writes -----------------------------------------------------------------------------------

    def create_node(
        self,
        *,
        node_id: str,
        token_sha256: str,
        device_type: str,
        firmware: str | None,
        cadence_ms: int | None,
        loc_tier: str,
        loc_ref: str | None,
        cell_id: str | None,
        channels: list[str],
        postcode: str | None,
        raw_region: str | None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO nodes(node_id, created_utc, device_type, firmware, cadence_ms, "
                "loc_tier, loc_ref, cell_id, channels, deleted_utc) "
                "VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                (node_id, _now(), device_type, firmware, cadence_ms, loc_tier, loc_ref,
                 cell_id, json.dumps(sorted(channels))),
            )
            self._conn.execute(
                "INSERT INTO tokens(node_id, token_sha256) VALUES (?,?)", (node_id, token_sha256)
            )
            self._conn.execute(
                "INSERT INTO node_private(node_id, postcode, raw_region, contributor_ref) "
                "VALUES (?,?,?,NULL)",
                (node_id, postcode, raw_region),
            )
            self._conn.commit()

    def update_consent(
        self,
        node_id: str,
        *,
        channels: list[str] | None,
        loc_tier: str | None,
        loc_ref: str | None,
        cell_id: str | None,
        postcode: str | None,
    ) -> None:
        with self._lock:
            if channels is not None:
                self._conn.execute(
                    "UPDATE nodes SET channels=? WHERE node_id=?",
                    (json.dumps(sorted(channels)), node_id),
                )
            if loc_tier is not None:
                self._conn.execute(
                    "UPDATE nodes SET loc_tier=?, loc_ref=?, cell_id=? WHERE node_id=?",
                    (loc_tier, loc_ref, cell_id, node_id),
                )
                self._conn.execute(
                    "UPDATE node_private SET postcode=? WHERE node_id=?", (postcode, node_id)
                )
            self._conn.commit()

    def delete_node(self, node_id: str) -> bool:
        """GDPR erasure: drop token + private data, mark node deleted, write a tombstone."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE nodes SET deleted_utc=? WHERE node_id=? AND deleted_utc IS NULL",
                (_now(), node_id),
            )
            if cur.rowcount == 0:
                self._conn.commit()
                return False
            self._conn.execute("DELETE FROM tokens WHERE node_id=?", (node_id,))
            self._conn.execute("DELETE FROM node_private WHERE node_id=?", (node_id,))
            self._conn.execute(
                "INSERT OR REPLACE INTO tombstones(node_id, tombstoned_utc) VALUES (?,?)",
                (node_id, _now()),
            )
            self._conn.commit()
            return True

    # --- reads ------------------------------------------------------------------------------------

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM nodes WHERE node_id=? AND deleted_utc IS NULL", (node_id,)
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["channels"] = set(json.loads(d["channels"]))
        return d

    def get_token_hash(self, node_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT token_sha256 FROM tokens WHERE node_id=?", (node_id,)
            ).fetchone()
        return row["token_sha256"] if row else None

    def ok(self) -> bool:
        try:
            with self._lock:
                self._conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False
