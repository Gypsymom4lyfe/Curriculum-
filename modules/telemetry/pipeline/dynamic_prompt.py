"""
CLONE-701 | Week 6 Lab — Dynamic Prompt Context Middleware
Queries rolling InfluxDB averages and injects a biometric state block
into LLM system prompts without overflowing the token window.
"""

import os
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from influxdb_client import InfluxDBClient


INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://localhost:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "waymaker")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "biometrics")

ROLLING_WINDOW_MINUTES = 5


class CapacityState(str, Enum):
    """Operator physiological capacity tier derived from biometric indices."""

    GREEN = "GREEN"   # High HRV, resting HR nominal — full capacity
    YELLOW = "YELLOW" # Moderate stress — selective tasking recommended
    RED = "RED"       # High stress / low recovery — protective buffering active


@dataclass
class BiometricContext:
    avg_hrv_ms: float | None
    avg_hr_bpm: float | None
    avg_spo2_pct: float | None
    capacity_state: CapacityState


def _classify_capacity(hrv: float | None, hr: float | None) -> CapacityState:
    """
    Determine operator capacity tier.

    Rules:
    - GREEN  : HRV >= 50 ms  AND  HR <= 75 bpm
    - RED    : HRV <  30 ms  OR   HR >  95 bpm
    - YELLOW : all other readings (or missing data)
    """
    if hrv is None or hr is None:
        return CapacityState.YELLOW

    if hrv >= 50 and hr <= 75:
        return CapacityState.GREEN
    if hrv < 30 or hr > 95:
        return CapacityState.RED
    return CapacityState.YELLOW


def query_rolling_averages(client: InfluxDBClient) -> BiometricContext:
    """
    Fetch rolling ROLLING_WINDOW_MINUTES-minute mean for key metrics.

    Returns a BiometricContext with averaged values (None if no data).
    """
    window = f"-{ROLLING_WINDOW_MINUTES}m"
    query_api = client.query_api()

    def _mean(measurement: str) -> float | None:
        flux = (
            f'from(bucket: "{INFLUXDB_BUCKET}")'
            f"  |> range(start: {window})"
            f'  |> filter(fn: (r) => r._measurement == "{measurement}")'
            f"  |> mean()"
        )
        tables = query_api.query(flux, org=INFLUXDB_ORG)
        for table in tables:
            for record in table.records:
                v = record.get_value()
                if v is not None:
                    return float(v)
        return None

    hrv = _mean("hrv_ms")
    hr = _mean("heart_rate_bpm")
    spo2 = _mean("spo2_pct")

    return BiometricContext(
        avg_hrv_ms=hrv,
        avg_hr_bpm=hr,
        avg_spo2_pct=spo2,
        capacity_state=_classify_capacity(hrv, hr),
    )


def build_biometric_state_block(ctx: BiometricContext) -> str:
    """
    Render a compact biometric state header for injection into LLM system prompts.

    Designed to be prepended to the system prompt; stays well under 200 tokens.
    """
    hrv_str = f"{ctx.avg_hrv_ms:.1f} ms" if ctx.avg_hrv_ms is not None else "N/A"
    hr_str = f"{ctx.avg_hr_bpm:.1f} bpm" if ctx.avg_hr_bpm is not None else "N/A"
    spo2_str = f"{ctx.avg_spo2_pct:.1f}%" if ctx.avg_spo2_pct is not None else "N/A"

    capacity_directives = {
        CapacityState.GREEN: (
            "Operator is at full capacity. Proceed with all tasks normally."
        ),
        CapacityState.YELLOW: (
            "Operator shows moderate physiological stress. "
            "Prioritise high-value tasks; defer low-priority items where possible."
        ),
        CapacityState.RED: (
            "Operator is in high-stress / low-recovery state. "
            "PROTECTIVE BUFFER ACTIVE: defer all non-essential tasks. "
            "Respond with brevity and minimal cognitive load."
        ),
    }

    block = (
        f"[BIOMETRIC STATE — {ROLLING_WINDOW_MINUTES}-min rolling average]\n"
        f"  HRV  : {hrv_str}\n"
        f"  HR   : {hr_str}\n"
        f"  SpO2 : {spo2_str}\n"
        f"  Capacity : {ctx.capacity_state.value}\n"
        f"  Directive : {capacity_directives[ctx.capacity_state]}\n"
        f"[END BIOMETRIC STATE]"
    )
    return block


def get_dynamic_system_prompt(base_prompt: str) -> str:
    """
    Convenience function: connect to InfluxDB, query current state,
    and prepend the biometric block to *base_prompt*.

    Args:
        base_prompt: The static portion of the LLM system prompt.

    Returns:
        The fully assembled system prompt with biometric context injected.
    """
    with InfluxDBClient(
        url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG
    ) as client:
        ctx = query_rolling_averages(client)

    state_block = build_biometric_state_block(ctx)
    return f"{state_block}\n\n{base_prompt}"
