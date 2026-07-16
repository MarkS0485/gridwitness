"""Export the ingest contract as published, versioned artifacts.

The pydantic models are the single source of truth. This writes three files third-party submitters
code against, so nobody has to run the server to know the contract:

    schema/gridwitness-ingest.v1.schema.json   JSON Schema (draft 2020-12) for every request/response
    schema/channels.v1.json                    the channel catalogue (units, types, sensitivity)
    schema/openapi.json                         the OpenAPI 3 spec for the ingest server

Usage:  python -m gridwitness_server.schema_export [output_dir]   (default: <repo>/schema)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from pydantic.json_schema import models_json_schema

from .config import Settings
from .models import (
    CHANNEL_CATALOGUE,
    SCHEMA_VERSION,
    RegisterRequest,
    RegisterResponse,
    SamplesRequest,
    SamplesResponse,
)

_REPO = Path(__file__).resolve().parents[2]
_RAW = "https://raw.githubusercontent.com/MarkS0485/gridwitness/main/schema"


def build_ingest_schema() -> dict:
    _, top = models_json_schema(
        [
            (RegisterRequest, "validation"),
            (RegisterResponse, "validation"),
            (SamplesRequest, "validation"),
            (SamplesResponse, "validation"),
        ],
        ref_template="#/$defs/{model}",
        title="GridWitness ingest v1",
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{_RAW}/gridwitness-ingest.v1.schema.json",
        "title": "GridWitness ingest v1",
        "description": "Request/response payloads for the GridWitness ingest API. "
                       "See docs/submitters.md for how to build your own submitter.",
        "gridwitnessSchemaVersion": SCHEMA_VERSION,
        **top,
    }


def build_channels() -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{_RAW}/channels.v1.json",
        "title": "GridWitness channel catalogue v1",
        "gridwitnessSchemaVersion": SCHEMA_VERSION,
        "channels": CHANNEL_CATALOGUE,
    }


def build_openapi() -> dict:
    # Point the app at a throwaway dir so exporting has no side effects on the real data root.
    tmp = Path(tempfile.mkdtemp(prefix="gw_schema_"))
    settings = Settings(data_dir=tmp, db_path=tmp / "x.db", staging_dir=tmp / "staging",
                        geoip_mmdb=None, rate_rows_per_min=1)
    from .main import create_app
    return create_app(settings).openapi()


def write_all(outdir: Path) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, doc in (
        ("gridwitness-ingest.v1.schema.json", build_ingest_schema()),
        ("channels.v1.json", build_channels()),
        ("openapi.json", build_openapi()),
    ):
        path = outdir / name
        path.write_text(json.dumps(doc, indent=2, sort_keys=False) + "\n", encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    outdir = Path(argv[0]) if argv else _REPO / "schema"
    for path in write_all(outdir):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
