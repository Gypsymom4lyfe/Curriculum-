"""
CLONE-701 | Week 4 Lab — Telemetry Ingestion Gateway
FastAPI service that receives biometric payloads and writes them to InfluxDB.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from influxdb_client import InfluxDBClient, WriteOptions
from influxdb_client.client.write_api import SYNCHRONOUS

from pipeline.schema import BodyMatrixPayload, MetricPoint


INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://localhost:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "waymaker")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "biometrics")

_influx_client: InfluxDBClient | None = None
_write_api = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _influx_client, _write_api
    _influx_client = InfluxDBClient(
        url=INFLUXDB_URL,
        token=INFLUXDB_TOKEN,
        org=INFLUXDB_ORG,
    )
    _write_api = _influx_client.write_api(write_options=SYNCHRONOUS)
    yield
    if _influx_client:
        _influx_client.close()


app = FastAPI(
    title="Telemetry Ingestion Gateway",
    description="CLONE-701 biometric ingestion endpoint (BodyMatrixPayload → InfluxDB)",
    version="1.0.0",
    lifespan=lifespan,
)


def _to_line_protocol(payload: BodyMatrixPayload) -> list[str]:
    """Convert a BodyMatrixPayload into InfluxDB line-protocol strings."""
    lines: list[str] = []
    ts_ns = int(payload.timestamp.timestamp() * 1_000_000_000)
    tags = f"source={payload.source},device={payload.device_id}"

    for metric in payload.metrics:
        line = (
            f"{metric.measurement},{tags} "
            f"value={metric.value} "
            f"{ts_ns}"
        )
        lines.append(line)
    return lines


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> dict:
    """Liveness probe — confirms the gateway is running."""
    return {"status": "ok"}


@app.post("/ingest", status_code=status.HTTP_201_CREATED)
async def ingest(payload: BodyMatrixPayload) -> dict:
    """
    Accept a BodyMatrixPayload and write each metric to InfluxDB.

    Returns a summary of how many points were written.
    """
    if _write_api is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="InfluxDB write client not initialised.",
        )

    lines = _to_line_protocol(payload)
    try:
        _write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=lines)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"InfluxDB write failed: {exc}",
        ) from exc

    return {
        "accepted": len(lines),
        "source": payload.source,
        "device_id": payload.device_id,
        "timestamp": payload.timestamp.isoformat(),
    }
