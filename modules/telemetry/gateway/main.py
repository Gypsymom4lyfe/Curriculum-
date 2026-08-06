"""
CLONE-701 — Week 4 Lab
FastAPI ingestion gateway for biometric telemetry.
Accepts BodyMatrixPayload POSTs and writes to InfluxDB.
"""

import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, status
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from pipeline.schema import BodyMatrixPayload  # type: ignore[import]

INFLUXDB_URL = os.environ["INFLUXDB_URL"]
INFLUXDB_TOKEN = os.environ["INFLUXDB_TOKEN"]
INFLUXDB_ORG = os.environ["INFLUXDB_ORG"]
INFLUXDB_BUCKET = os.environ["INFLUXDB_BUCKET"]

app = FastAPI(title="Telemetry Gateway", version="1.0.0")

_influx_client = InfluxDBClient(
    url=INFLUXDB_URL,
    token=INFLUXDB_TOKEN,
    org=INFLUXDB_ORG,
)
_write_api = _influx_client.write_api(write_options=SYNCHRONOUS)


@app.get("/health")
def health() -> dict:
    """Liveness probe used by Docker health checks."""
    return {"status": "ok"}


@app.post("/ingest", status_code=status.HTTP_201_CREATED)
def ingest(payload: BodyMatrixPayload) -> dict:
    """
    Receive a biometric payload and persist it to InfluxDB.

    Each field in BodyMatrixPayload is written as a separate measurement
    tagged with the source device identifier.
    """
    ts = payload.timestamp or datetime.now(timezone.utc)

    points: list[Point] = []

    if payload.heart_rate_bpm is not None:
        points.append(
            Point("heart_rate")
            .tag("source", payload.source)
            .field("bpm", payload.heart_rate_bpm)
            .time(ts, WritePrecision.SECONDS)
        )

    if payload.hrv_ms is not None:
        points.append(
            Point("hrv")
            .tag("source", payload.source)
            .field("ms", payload.hrv_ms)
            .time(ts, WritePrecision.SECONDS)
        )

    if payload.spo2_pct is not None:
        points.append(
            Point("spo2")
            .tag("source", payload.source)
            .field("pct", payload.spo2_pct)
            .time(ts, WritePrecision.SECONDS)
        )

    if payload.skin_temp_c is not None:
        points.append(
            Point("skin_temp")
            .tag("source", payload.source)
            .field("celsius", payload.skin_temp_c)
            .time(ts, WritePrecision.SECONDS)
        )

    if payload.steps is not None:
        points.append(
            Point("steps")
            .tag("source", payload.source)
            .field("count", payload.steps)
            .time(ts, WritePrecision.SECONDS)
        )

    if not points:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Payload contains no measurable biometric fields.",
        )

    try:
        _write_api.write(bucket=INFLUXDB_BUCKET, record=points)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"InfluxDB write failed: {exc}",
        ) from exc

    return {"written": len(points), "source": payload.source}
