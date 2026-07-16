# GridWitness

Crowd-sourced GB grid measurement via Home Assistant. Turn the metering hardware you already own (smart plugs, 3-phase energy meters, inverters, weather stations) into a distributed, UTC-timestamped measurement fabric for the GB electricity grid.

North star: breadth the professional networks don't have. Four professional PMUs cost thousands of pounds. Four hundred amateur nodes cover the whole island.

## What's in this repo

| Path | What it is |
|---|---|
| `custom_components/gridwitness/` | The Home Assistant custom integration (HACS). The primary deliverable. |
| `server/` | A standalone Python ingest server (FastAPI) you self-host. It receives data and writes CSV. |
| `gda_acquirer/` | The GDA lake acquirer, designed here and deployed into the GDA repo later. |
| `schema/` | The published, versioned ingest schema (JSON Schema, channel catalogue, OpenAPI). Code your own submitter against these. |
| `docs/` | The contracts: [data model](docs/data-model.md), [ingest API](docs/ingest-api.md), [submitter guide](docs/submitters.md), [privacy](docs/privacy-statement.md), [architecture](docs/architecture.md). |
| `DESIGN.md` | The full project design. |

## Bring your own data

GridWitness is not tied to Home Assistant. If you have grid or weather data, or an app that produces
it, you can submit directly against a published, versioned schema. Start with the
[submitter guide](docs/submitters.md) and the machine-readable contract in [`schema/`](schema/).

## How it fits together

The Home Assistant integration pushes readings over HTTPS with a per-node token to a self-hosted ingest server. The server validates them, enforces consent, and appends them to CSV staging files. Separately and later, a GDA acquirer reads those CSV files into the research lake, where GridSim consumes them. The CSV staging directory is the only contract between the server and the lake, so the two never call each other and either can be rebuilt independently.

## Privacy first

We ask for the least revealing useful thing (grid frequency, which reveals nothing about your house) and make every escalation an explicit, revocable opt-in. Your postcode never leaves the server. See the [privacy statement](docs/privacy-statement.md) and the earn-the-ask matrix in the design.

## Status

P0 is a frequency-first MVP with all channels supported. Two things gate a public launch: TLS with a real hostname, and a finalised privacy statement. See `DESIGN.md` section 9 for the roadmap.

## Licence

MIT.
