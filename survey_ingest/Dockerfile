# GridWitness survey ingester. Out-of-band worker: drains the survey upload inbox, extracts
# frequency + voltage, appends to the shared CSV staging tree. Shares the ingest server's /data
# volume. Build context is the REPO ROOT so both server/ and survey_ingest/ are available.
#   docker build -f survey_ingest/Dockerfile -t gw-survey .
FROM python:3.12-slim AS runtime

WORKDIR /app

# Install the ingest server package (for config/db/staging/privacy/models) and the worker's own deps.
COPY server/pyproject.toml ./server/
COPY server/gridwitness_server ./server/gridwitness_server
COPY server/deploy ./server/deploy
RUN pip install --no-cache-dir ./server && pip install --no-cache-dir "pandas>=2.0"

COPY survey_ingest ./survey_ingest

ENV GW_DATA_DIR=/data \
    GW_SERVER_PATH=/app/server \
    GW_SURVEY_INTERVAL=900
# PQDIF: the pqdif2csv tool is .NET Framework (Windows). It is absent here, so PQDIF files are
# skipped with a manifest note; CSV/TXT surveys process normally. Set GW_PQDIF2CSV on a Windows host.

VOLUME ["/data"]

# Simple scheduler: drain, then sleep. The single-instance socket lock makes overlaps harmless.
CMD ["sh", "-c", "while true; do python /app/survey_ingest/survey_ingest.py || true; sleep ${GW_SURVEY_INTERVAL:-900}; done"]
