"""Server settings, driven by environment variables with safe defaults.

Kept dependency-free (no pydantic-settings) so the server has a tiny install footprint. All paths
default under ``server_data/`` next to the package, which is gitignored — the SQLite private DB and
the CSV staging tree both live there.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent  # the server/ dir
_DEFAULT_DATA = _PKG_ROOT / "server_data"


def _env_path(key: str, default: Path) -> Path:
    val = os.environ.get(key)
    return Path(val) if val else default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ[key])
    except (KeyError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    staging_dir: Path
    geoip_mmdb: Path | None          # optional MaxMind GeoLite2 for the ANON tier
    # rate limit: allow this many rows per node per minute before 429
    rate_rows_per_min: int
    # Shared secret for the internal admin API (account portal -> server). When unset, the whole
    # /v1/admin surface is disabled and account-linked provisioning is refused. Never crosses the
    # public internet — the portal calls the server over the private container network.
    internal_key: str | None = None
    version: str = "0.1.0"

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = _env_path("GW_DATA_DIR", _DEFAULT_DATA)
        mmdb = os.environ.get("GW_GEOIP_MMDB")
        internal_key = os.environ.get("GW_INTERNAL_KEY") or None
        return cls(
            data_dir=data_dir,
            db_path=_env_path("GW_DB_PATH", data_dir / "gridwitness.db"),
            staging_dir=_env_path("GW_STAGING_DIR", data_dir / "staging"),
            geoip_mmdb=Path(mmdb) if mmdb else None,
            rate_rows_per_min=_env_int("GW_RATE_ROWS_PER_MIN", 6000),
            internal_key=internal_key,
        )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.staging_dir / "electrical").mkdir(parents=True, exist_ok=True)
        (self.staging_dir / "weather").mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings.from_env()
