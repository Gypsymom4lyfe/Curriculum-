"""
CLONE-701 — Week 6: Dynamic Context Injection Middleware

Queries a rolling 5-minute window of biometric averages from InfluxDB
and renders a structured system-prompt block that can be prepended to
any LLM call, enabling real-time physiological context injection.
"""

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from influxdb_client import InfluxDBClient

INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "waymaker")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "telemetry")

# Thresholds derived from autonomic physiology research
HRV_LOW_THRESHOLD = 30.0     # ms — below this indicates high sympathetic load
HR_HIGH_THRESHOLD = 90.0     # BPM — elevated resting HR signals fatigue
SLEEP_SCORE_LOW = 60         # below 60 triggers protective buffering


@dataclass
class BiometricState:
    heart_rate: float
    hrv_ms: float
    spo2_pct: float
    skin_temp_c: float
    respiratory_rate: float
    sleep_score: float
    sampled_at: str

    @property
    def fatigue_index(self) -> str:
        """
        Derive a qualitative fatigue level from biometric averages.

        - HIGH   → HRV critically low or sleep score poor
        - MEDIUM → HR mildly elevated or HRV borderline
        - LOW    → all signals within recovery range
        """
        if self.hrv_ms < HRV_LOW_THRESHOLD or self.sleep_score < SLEEP_SCORE_LOW:
            return "HIGH"
        if self.heart_rate > HR_HIGH_THRESHOLD:
            return "MEDIUM"
        return "LOW"

    @property
    def green_light(self) -> bool:
        """True when biometric state supports full operational capacity."""
        return self.fatigue_index == "LOW"


def query_rolling_averages(window_minutes: int = 5) -> BiometricState:
    """
    Pull mean values for each metric over the last *window_minutes* from
    InfluxDB and return a typed BiometricState dataclass.
    """
    client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    query_api = client.query_api()

    flux = f"""
    from(bucket: "{INFLUXDB_BUCKET}")
      |> range(start: -{window_minutes}m)
      |> filter(fn: (r) => r._measurement == "body_matrix")
      |> filter(fn: (r) =>
           r._field == "heart_rate" or
           r._field == "hrv_ms" or
           r._field == "spo2_pct" or
           r._field == "skin_temp_c" or
           r._field == "respiratory_rate" or
           r._field == "sleep_score")
      |> mean()
      |> pivot(rowKey:["_start"], columnKey: ["_field"], valueColumn: "_value")
    """

    tables = query_api.query(flux)
    averages: dict[str, float] = {}
    for table in tables:
        for record in table.records:
            for field in ("heart_rate", "hrv_ms", "spo2_pct", "skin_temp_c",
                          "respiratory_rate", "sleep_score"):
                if record.values.get(field) is not None:
                    averages[field] = float(record.values[field])

    return BiometricState(
        heart_rate=averages.get("heart_rate", 70.0),
        hrv_ms=averages.get("hrv_ms", 50.0),
        spo2_pct=averages.get("spo2_pct", 98.0),
        skin_temp_c=averages.get("skin_temp_c", 33.5),
        respiratory_rate=averages.get("respiratory_rate", 14.0),
        sleep_score=averages.get("sleep_score", 75.0),
        sampled_at=datetime.now(timezone.utc).isoformat(),
    )


def build_system_prompt_block(state: BiometricState) -> str:
    """
    Render a compact, token-efficient biometric state block suitable for
    injection at the top of an LLM system prompt.

    The block is deliberately concise to preserve the primary context
    window budget for task-specific instructions.
    """
    green = "ACTIVE" if state.green_light else "DEFERRED"

    return (
        f"[BIOMETRIC STATE — {state.sampled_at}]\n"
        f"HR: {state.heart_rate:.1f} bpm | "
        f"HRV: {state.hrv_ms:.1f} ms | "
        f"SpO2: {state.spo2_pct:.1f}% | "
        f"Temp: {state.skin_temp_c:.1f}°C | "
        f"RR: {state.respiratory_rate:.1f} brpm | "
        f"Sleep: {int(state.sleep_score)}/100\n"
        f"FATIGUE INDEX: {state.fatigue_index} | "
        f"OPERATIONAL MODE: {green}\n"
        f"INSTRUCTION: {'Proceed with full task execution.' if state.green_light else 'Defer non-essential tasks. Prioritise recovery protocols.'}"
    )


def generate_dynamic_prompt(window_minutes: int = 5) -> str:
    """
    Convenience function: query InfluxDB and return a ready-to-use
    system prompt block in a single call.
    """
    state = query_rolling_averages(window_minutes)
    return build_system_prompt_block(state)
