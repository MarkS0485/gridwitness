"""Turn an electrician's survey file into frequency + voltage rows — and NOTHING else.

Two input shapes:

  * CSV / TXT / TSV — a logger export from any analyser (Fluke, Hioki, Dranetz, Chauvin Arnoux, …).
    Column names vary wildly between vendors, so we identify the timestamp, voltage and frequency
    columns by fuzzy header matching and ignore every other column. That column whitelist is where
    the "only frequency and voltage leave" guarantee is enforced in code: current, power, THD, and
    anything else in the file is never even read into a row.

  * PQDIF (.pqd/.pqdif) — the IEEE 1159.3 binary interchange format. We don't parse binary here;
    the pqdif2csv .NET tool (GSF.PQDIF) converts it to a long-format CSV first, which we then read.

Everything returns a list of ParsedRow. Timestamps are normalised to UTC ISO-8601 'Z'. Out-of-band
values are dropped (and counted), never staged.

pandas is imported lazily (module top-level import is fine here — this whole module is only loaded by
the out-of-band worker, never by the dependency-light FastAPI server).
"""
from __future__ import annotations

import csv
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Plausibility bounds. Frequency reuses the server's 40–70 Hz sanity band; voltage spans LN (~230) to
# LL (~400) plus generous margin — anything outside is a sensor/scale error, not a real GB reading.
FREQ_MIN, FREQ_MAX = 40.0, 70.0
VOLT_MIN, VOLT_MAX = 40.0, 520.0

# Fuzzy header matching. A column matches a channel if its lower-cased name contains any token.
# Order matters only for disambiguation; we test frequency before voltage so a stray "v" in a
# frequency header can't win. Current/power/PF tokens are deliberately absent — those never map.
_TS_TOKENS = ("timestamp", "date/time", "datetime", "date time", "time", "date", "utc")
_FREQ_TOKENS = ("frequency", "freq", "hz")
_VOLT_TOKENS = (
    "voltage", "vrms", "urms", "v rms", "u rms", "volt", "v_rms", "u_rms",
    # bare per-phase voltage headers common on three-phase analysers (V1/U1/Van style)
    "v1", "v2", "v3", "u1", "u2", "u3", "van", "vbn", "vcn", "uan", "ubn", "ucn",
)

# Three-phase voltage columns → phase labels. Single voltage column → "1p".
_PHASE_HINTS = (
    (("l1", "v1", "u1", "ph1", "phase 1", "phase1", "a-n", "van"), "L1"),
    (("l2", "v2", "u2", "ph2", "phase 2", "phase2", "b-n", "vbn"), "L2"),
    (("l3", "v3", "u3", "ph3", "phase 3", "phase3", "c-n", "vcn"), "L3"),
)


@dataclass
class ParsedRow:
    ts_utc: str
    phase: str
    voltage_v: float | None
    frequency_hz: float | None


@dataclass
class ParseResult:
    rows: list[ParsedRow]
    read: int          # data lines seen
    kept: int          # rows with at least one in-band value
    dropped: int       # rows dropped (unparseable ts, or all values out of band)
    note: str | None = None
    deferred: bool = False   # True = couldn't handle here (PQDIF, no converter) — leave it queued


def _to_iso_z(value: str, _pd_cache: list = []) -> str | None:
    """Parse a heterogeneous logger timestamp to UTC ISO-8601 'Z'. Uses pandas' tolerant parser."""
    if not _pd_cache:
        import pandas as pd  # lazy; worker-only dependency
        _pd_cache.append(pd)
    pd = _pd_cache[0]
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if ts is None or pd.isna(ts):
        return None
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def _num(value: str) -> float | None:
    """Parse a numeric cell, tolerating both US (1,234.5) and European (1 234,5 / 238,5) formatting.

    Ambiguous cases resolve toward the European decimal comma, which is what matters in our value
    domain (voltage ~40–520, frequency ~50) — a lone comma with no dot is a decimal point, not a
    thousands separator, for any number we'd legitimately keep.
    """
    s = str(value).strip().replace(" ", "")
    if not s:
        return None
    if "." in s and "," in s:
        s = s.replace(",", "")            # comma = thousands grouping, dot = decimal
    elif s.count(",") == 1 and "." not in s:
        s = s.replace(",", ".")           # lone comma = European decimal
    else:
        s = s.replace(",", "")            # multiple commas = grouping
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _match(header: str, tokens: tuple[str, ...]) -> bool:
    h = header.strip().lower()
    return any(t in h for t in tokens)


def _phase_for(header: str) -> str:
    h = header.strip().lower()
    for hints, label in _PHASE_HINTS:
        if any(hint in h for hint in hints):
            return label
    return "1p"


def _classify_columns(headers: list[str]) -> tuple[str | None, list[tuple[str, str]], str | None]:
    """Return (timestamp_col, [(voltage_col, phase)], frequency_col). Unmatched columns are ignored."""
    ts_col = next((h for h in headers if _match(h, _TS_TOKENS)), None)
    freq_col = next((h for h in headers if _match(h, _FREQ_TOKENS)), None)
    volt_cols: list[tuple[str, str]] = [
        (h, _phase_for(h)) for h in headers
        if _match(h, _VOLT_TOKENS) and not _match(h, _FREQ_TOKENS) and h != ts_col
    ]
    return ts_col, volt_cols, freq_col


def _sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;").delimiter
    except csv.Error:
        return ","


def _rows_from_records(records: "list[dict[str, str]]", headers: list[str]) -> ParseResult:
    ts_col, volt_cols, freq_col = _classify_columns(headers)
    if ts_col is None or (not volt_cols and freq_col is None):
        return ParseResult([], 0, 0, 0, note="no usable timestamp/voltage/frequency columns")

    out: list[ParsedRow] = []
    read = kept = dropped = 0
    for rec in records:
        read += 1
        iso = _to_iso_z(rec.get(ts_col, ""))
        if iso is None:
            dropped += 1
            continue

        freq = _num(rec.get(freq_col, "")) if freq_col else None
        if freq is not None and not (FREQ_MIN <= freq <= FREQ_MAX):
            freq = None

        made_row = False
        for i, (vcol, phase) in enumerate(volt_cols or []):
            v = _num(rec.get(vcol, ""))
            if v is not None and not (VOLT_MIN <= v <= VOLT_MAX):
                v = None
            # Attach node-global frequency to the first phase only, so it isn't duplicated per phase.
            f_here = freq if i == 0 else None
            if v is None and f_here is None:
                continue
            out.append(ParsedRow(iso, phase, v, f_here))
            made_row = True

        if not volt_cols and freq is not None:
            out.append(ParsedRow(iso, "1p", None, freq))
            made_row = True

        kept += 1 if made_row else 0
        dropped += 0 if made_row else 1
    return ParseResult(out, read, kept, dropped)


_LONG_HEADER = {"timestamp", "phase", "channel", "value"}


def _rows_from_long(records) -> ParseResult:
    """Parse the long format (timestamp,phase,channel,value) — what pqdif2csv emits, and what a
    converted PQDIF re-uploaded as CSV looks like. Groups (timestamp,phase) into wide ParsedRows."""
    grouped: dict[tuple[str, str], ParsedRow] = {}
    read = 0
    for rec in records:
        read += 1
        r = {(k or "").strip().lower(): v for k, v in rec.items()}
        iso = _to_iso_z(r.get("timestamp", ""))
        if iso is None:
            continue
        phase = (r.get("phase") or "1p").strip() or "1p"
        channel = (r.get("channel") or "").strip().lower()
        val = _num(r.get("value", ""))
        if val is None:
            continue
        row = grouped.setdefault((iso, phase), ParsedRow(iso, phase, None, None))
        if "freq" in channel and FREQ_MIN <= val <= FREQ_MAX:
            row.frequency_hz = val
        elif "volt" in channel and VOLT_MIN <= val <= VOLT_MAX:
            row.voltage_v = val
    rows = [r for r in grouped.values() if r.voltage_v is not None or r.frequency_hz is not None]
    return ParseResult(rows, read, len(rows), read - len(rows))


def parse_csv(path: Path) -> ParseResult:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines:
        return ParseResult([], 0, 0, 0, note="empty file")
    delim = _sniff_delimiter("\n".join(lines[:20]))
    reader = csv.DictReader(lines, delimiter=delim)
    if not reader.fieldnames:
        return ParseResult([], 0, 0, 0, note="no header row")
    # A converted-PQDIF export (from pqdif2csv) is already in our long format — parse it directly so
    # you can convert locally on Windows and just re-upload the CSV.
    if {f.strip().lower() for f in reader.fieldnames} == _LONG_HEADER:
        return _rows_from_long(reader)
    records = list(reader)
    return _rows_from_records(records, list(reader.fieldnames))


def parse_pqdif(path: Path, converter: str | None) -> ParseResult:
    """Convert PQDIF→CSV via the pqdif2csv tool, then read its long format (timestamp,phase,channel,value)."""
    if not converter:
        # No converter here (e.g. the Linux worker — pqdif2csv is Windows/.NET). Defer, don't fail:
        # the file stays queued so a Windows-hosted run with GW_PQDIF2CSV set can convert it later.
        return ParseResult([], 0, 0, 0, note="pqdif converter not configured (set GW_PQDIF2CSV)", deferred=True)
    try:
        proc = subprocess.run(
            [converter, str(path)], capture_output=True, text=True, timeout=600, check=True
        )
    except FileNotFoundError:
        return ParseResult([], 0, 0, 0, note=f"pqdif converter not found: {converter}", deferred=True)
    except subprocess.CalledProcessError as e:
        return ParseResult([], 0, 0, 0, note=f"pqdif convert failed: {e.stderr.strip()[:200]}")
    except subprocess.TimeoutExpired:
        return ParseResult([], 0, 0, 0, note="pqdif convert timed out")

    # The tool emits our long format (timestamp,phase,channel,value) — reuse the shared parser.
    return _rows_from_long(csv.DictReader(proc.stdout.splitlines()))


def parse_file(path: Path, converter: str | None) -> ParseResult:
    ext = path.suffix.lower()
    if ext in (".pqd", ".pqdif"):
        return parse_pqdif(path, converter)
    return parse_csv(path)
