"""
CLONE-701 — Week 6 Lab
Dynamic prompt middleware: queries rolling InfluxDB averages and injects
a biometric state header block into LLM system prompts.
"""

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from influxdb_client import InfluxDBClient

INFLUXDB_URL = os.environ.get("INFLUXDB_URL", "http://localhost:8086")
INFLUXDB_TOKEN = os.environ.get("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.environ.get("INFLUXDB_ORG", "waymaker")
INFLUXDB_BUCKET = os.environ.get("INFLUXDB_BUCKET", "biometrics")

# Rolling window for average calculations (Week 6: 5-minute window)
ROLLING_WINDOW = "5m"

# Fatigue thresholds derived from research norms
HRV_FATIGUE_THRESHOLD_MS = 30.0   # below this → high fatigue
HR_STRESS_THRESHOLD_BPM = 90.0    # above this → elevated stress
SPO2_LOW_THRESHOLD_PCT = 95.0     # below this → flag for attention


@dataclass
class BiometricState:
    heart_rate_bpm: float | None
    hrv_ms: float | None
    spo2_pct: float | None
    fatigue_index: str          # "low" | "moderate" | "high"
    stress_index: str           # "low" | "moderate" | "high"
    sampled_at: datetime


def _query_rolling_average(query_api, measurement: str, field: str) -> float | None:
    """Return the rolling-window mean for a given measurement/field, or None."""
    flux = (
        f'from(bucket: "{INFLUXDB_BUCKET}")'
        f"  |> range(start: -{ROLLING_WINDOW})"
        f'  |> filter(fn: (r) => r._measurement == "{measurement}")'
        f'  |> filter(fn: (r) => r._field == "{field}")'
        f"  |> mean()"
    )
    tables = query_api.query(flux, org=INFLUXDB_ORG)
    for table in tables:
        for record in table.records:
            return record.get_value()
    return None


def fetch_biometric_state() -> BiometricState:
    """Query InfluxDB and return a structured snapshot of the current biological state."""
    client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    query_api = client.query_api()

    hr = _query_rolling_average(query_api, "heart_rate", "bpm")
    hrv = _query_rolling_average(query_api, "hrv", "ms")
    spo2 = _query_rolling_average(query_api, "spo2", "pct")

    client.close()

    # Determine fatigue index from HRV
    if hrv is None:
        fatigue_index = "unknown"
    elif hrv < HRV_FATIGUE_THRESHOLD_MS:
        fatigue_index = "high"
    elif hrv < HRV_FATIGUE_THRESHOLD_MS * 1.5:
        fatigue_index = "moderate"
    else:
        fatigue_index = "low"

    # Determine stress index from heart rate
    if hr is None:
        stress_index = "unknown"
    elif hr > HR_STRESS_THRESHOLD_BPM:
        stress_index = "high"
    elif hr > HR_STRESS_THRESHOLD_BPM * 0.85:
        stress_index = "moderate"
    else:
        stress_index = "low"

    return BiometricState(
        heart_rate_bpm=hr,
        hrv_ms=hrv,
        spo2_pct=spo2,
        fatigue_index=fatigue_index,
        stress_index=stress_index,
        sampled_at=datetime.now(timezone.utc),
    )


def build_biometric_header(state: BiometricState) -> str:
    """
    Render a compact, token-efficient biometric state block suitable for
    injection into an LLM system prompt.
    """
    hr_str = f"{state.heart_rate_bpm:.1f} bpm" if state.heart_rate_bpm is not None else "unavailable"
    hrv_str = f"{state.hrv_ms:.1f} ms" if state.hrv_ms is not None else "unavailable"
    spo2_str = f"{state.spo2_pct:.1f}%" if state.spo2_pct is not None else "unavailable"

    header = (
        "### [BIOMETRIC STATE — {ts}]\n"
        "| Metric | Value | Index |\n"
        "| :--- | :--- | :--- |\n"
        "| Heart Rate | {hr} | Stress: {stress} |\n"
        "| HRV (RMSSD) | {hrv} | Fatigue: {fatigue} |\n"
        "| SpO₂ | {spo2} | — |\n"
        "### [END BIOMETRIC STATE]\n"
    ).format(
        ts=state.sampled_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        hr=hr_str,
        hrv=hrv_str,
        spo2=spo2_str,
        stress=state.stress_index,
        fatigue=state.fatigue_index,
    )
    return header


def inject_into_system_prompt(base_prompt: str) -> str:
    """
    Fetch current biometric state and prepend the state header to base_prompt.
    Keeps the injected block compact to protect the token budget.
    """
    state = fetch_biometric_state()
    header = build_biometric_header(state)
    return f"{header}\n{base_prompt}"
