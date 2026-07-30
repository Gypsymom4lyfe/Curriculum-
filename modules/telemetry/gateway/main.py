"""
CLONE-701 — Week 4: FastAPI Ingestion Gateway

Accepts POST requests containing BodyMatrixPayload biometric readings
and writes them to InfluxDB using the line protocol.
"""

import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, status
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from pipeline.schema import BodyMatrixPayload

INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "waymaker")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "telemetry")

app = FastAPI(
    title="CLONE-701 Telemetry Gateway",
    description="Biometric ingestion gateway for the digital clone module.",
    version="1.0.0",
)

_influx_client: InfluxDBClient | None = None


def get_influx_client() -> InfluxDBClient:
    global _influx_client
    if _influx_client is None:
        _influx_client = InfluxDBClient(
            url=INFLUXDB_URL,
            token=INFLUXDB_TOKEN,
            org=INFLUXDB_ORG,
        )
    return _influx_client


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> dict:
    """Liveness probe used by Docker health checks."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.post("/ingest", status_code=status.HTTP_201_CREATED)
async def ingest_payload(payload: BodyMatrixPayload) -> dict:
    """
    Accept a validated BodyMatrixPayload and write all metrics to InfluxDB.

    Each biometric field is written as a separate field key under the
    measurement ``body_matrix``, tagged with the source device identifier.
    """
    client = get_influx_client()
    write_api = client.write_api(write_options=SYNCHRONOUS)

    point = (
        Point("body_matrix")
        .tag("source", payload.source)
        .tag("subject_id", payload.subject_id)
        .field("heart_rate", payload.heart_rate)
        .field("hrv_ms", payload.hrv_ms)
        .field("spo2_pct", payload.spo2_pct)
        .field("skin_temp_c", payload.skin_temp_c)
        .field("respiratory_rate", payload.respiratory_rate)
        .field("sleep_score", payload.sleep_score)
        .time(
            payload.timestamp or datetime.now(timezone.utc),
            WritePrecision.SECONDS,
        )
    )

    try:
        write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"InfluxDB write failed: {exc}",
        ) from exc

    return {"status": "written", "subject_id": payload.subject_id}
