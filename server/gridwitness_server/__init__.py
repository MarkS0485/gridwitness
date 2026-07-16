"""GridWitness standalone ingest server.

Receives crowd-sourced GB grid measurements from Home Assistant nodes over HTTP, validates and
deduplicates them, enforces per-node consent, and appends them to CSV staging files. It holds the
private/relational data (node<->contributor, hashed tokens, raw postcode) in a local SQLite DB that
is *never* projected into the CSV.

The server stands alone: it knows nothing about the GDA lake. A separate acquirer reads the CSV
staging directory later and independently.
"""

__version__ = "0.1.0"
