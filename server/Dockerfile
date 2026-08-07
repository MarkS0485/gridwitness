# GridWitness ingest server (FastAPI + uvicorn). Stays on the private container network;
# Caddy terminates TLS and routes /v1/* here. Private SQLite + CSV staging live under /data.
FROM python:3.12-slim AS runtime

WORKDIR /app

# Install the package (dependency-light: fastapi, uvicorn, pydantic).
COPY pyproject.toml ./
COPY deploy ./deploy
COPY gridwitness_server ./gridwitness_server
RUN pip install --no-cache-dir .

ENV GW_HOST=0.0.0.0 \
    GW_PORT=8000 \
    GW_DATA_DIR=/data

EXPOSE 8000
VOLUME ["/data"]

CMD ["python", "-m", "gridwitness_server.main"]
