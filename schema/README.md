# GridWitness schema

Published, versioned artifacts that define the ingest contract. Third-party submitters code against
these; you do not need to run the server or read its source. See
[`docs/submitters.md`](../docs/submitters.md) for the guide.

| File | What it is |
|---|---|
| `gridwitness-ingest.v1.schema.json` | JSON Schema (draft 2020-12) for every request and response body, under `$defs`. |
| `channels.v1.json` | The channel catalogue: every field you may send, with unit, JSON type, and sensitivity. |
| `openapi.json` | OpenAPI 3 spec for the ingest API. Import into Postman or generate a client. |

## Single source of truth

These files are generated from the server's pydantic models, so they cannot drift from what the server
actually accepts. Do not hand-edit them. Regenerate with:

```bash
cd server && python -m gridwitness_server.schema_export
```

A CI test checks the committed catalogue and schema stay consistent with the models, so regenerate
after any model change.

## Versioning

The current version is `1.0` (`gridwitnessSchemaVersion` in each file). Additive changes, such as a new
optional channel, keep the major version. A breaking change publishes `v2` files alongside `v1`, and
`v1` keeps working until a deprecation window is announced.
