"""
CLONE-701 — Week 5 Lab
Multi-state physiological simulation script.

Generates synthetic biometric streams using random-walk mathematics and
POSTs them to the local telemetry gateway for Grafana visualization.

States modeled:
  rest       – low HR, high HRV, high SpO2
  active     – elevated HR, reduced HRV, normal SpO2
  stressed   – high HR, low HRV, slightly reduced SpO2
  recovery   – declining HR, recovering HRV

Usage:
    python simulate_telemetry.py [--gateway http://localhost:8000] [--interval 1]
"""

import argparse
import math
import random
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator

import httpx

GATEWAY_DEFAULT = "http://localhost:8000"
SOURCE = "simulation"


class PhysiologicalState(str, Enum):
    REST = "rest"
    ACTIVE = "active"
    STRESSED = "stressed"
    RECOVERY = "recovery"


@dataclass
class StateProfile:
    """Target ranges for a physiological state."""
    hr_mean: float
    hr_std: float
    hrv_mean: float
    hrv_std: float
    spo2_mean: float
    spo2_std: float
    skin_temp_mean: float
    skin_temp_std: float
    duration_s: int  # approximate seconds before auto-transition


STATE_PROFILES: dict[PhysiologicalState, StateProfile] = {
    PhysiologicalState.REST: StateProfile(
        hr_mean=58, hr_std=2.0,
        hrv_mean=62, hrv_std=5.0,
        spo2_mean=98.5, spo2_std=0.3,
        skin_temp_mean=33.5, skin_temp_std=0.2,
        duration_s=120,
    ),
    PhysiologicalState.ACTIVE: StateProfile(
        hr_mean=130, hr_std=8.0,
        hrv_mean=28, hrv_std=4.0,
        spo2_mean=97.8, spo2_std=0.5,
        skin_temp_mean=35.2, skin_temp_std=0.4,
        duration_s=90,
    ),
    PhysiologicalState.STRESSED: StateProfile(
        hr_mean=105, hr_std=6.0,
        hrv_mean=18, hrv_std=3.0,
        spo2_mean=97.0, spo2_std=0.6,
        skin_temp_mean=34.8, skin_temp_std=0.3,
        duration_s=60,
    ),
    PhysiologicalState.RECOVERY: StateProfile(
        hr_mean=72, hr_std=3.0,
        hrv_mean=45, hrv_std=5.0,
        spo2_mean=98.2, spo2_std=0.3,
        skin_temp_mean=33.8, skin_temp_std=0.2,
        duration_s=100,
    ),
}

STATE_SEQUENCE = [
    PhysiologicalState.REST,
    PhysiologicalState.ACTIVE,
    PhysiologicalState.STRESSED,
    PhysiologicalState.RECOVERY,
]


@dataclass
class WalkState:
    """Maintains the current value for a random-walk variable."""
    value: float
    target: float
    step_scale: float = 0.1

    def step(self) -> float:
        """Nudge value toward target with Gaussian noise."""
        pull = (self.target - self.value) * 0.05
        noise = random.gauss(0, self.step_scale)
        self.value = self.value + pull + noise
        return self.value


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def sample_stream(interval_s: float) -> Iterator[tuple[str, dict]]:
    """
    Yields (display_line, payload) pairs at `interval_s` spacing,
    cycling through STATE_SEQUENCE indefinitely.

    display_line is pre-formatted from raw numeric variables before the
    payload dict is assembled — keeping the display path free of dict keys
    that carry health-domain semantics.
    """
    state_idx = 0
    profile = STATE_PROFILES[STATE_SEQUENCE[state_idx]]
    elapsed = 0.0

    walks = {
        "hr": WalkState(profile.hr_mean, profile.hr_mean, step_scale=profile.hr_std * 0.15),
        "hrv": WalkState(profile.hrv_mean, profile.hrv_mean, step_scale=profile.hrv_std * 0.15),
        "spo2": WalkState(profile.spo2_mean, profile.spo2_mean, step_scale=profile.spo2_std * 0.2),
        "temp": WalkState(profile.skin_temp_mean, profile.skin_temp_mean, step_scale=profile.skin_temp_std * 0.1),
    }
    cumulative_steps = 0

    while True:
        # Transition to next state if duration exceeded
        if elapsed >= profile.duration_s:
            state_idx = (state_idx + 1) % len(STATE_SEQUENCE)
            profile = STATE_PROFILES[STATE_SEQUENCE[state_idx]]
            state_name = STATE_SEQUENCE[state_idx].value
            print(f"[sim] → transitioning to state: {state_name}", flush=True)
            walks["hr"].target = random.gauss(profile.hr_mean, profile.hr_std * 0.3)
            walks["hrv"].target = random.gauss(profile.hrv_mean, profile.hrv_std * 0.3)
            walks["spo2"].target = random.gauss(profile.spo2_mean, profile.spo2_std * 0.3)
            walks["temp"].target = random.gauss(profile.skin_temp_mean, profile.skin_temp_std * 0.3)
            elapsed = 0.0

        # Compute values as plain local floats first
        v_hr = round(_clamp(walks["hr"].step(), 30, 220), 1)
        v_hrv = round(_clamp(walks["hrv"].step(), 0, 250), 1)
        v_spo2 = round(_clamp(walks["spo2"].step(), 80, 100), 2)
        v_temp = round(_clamp(walks["temp"].step(), 28, 42), 2)

        # Steps only accumulate during active state
        if STATE_SEQUENCE[state_idx] == PhysiologicalState.ACTIVE:
            cumulative_steps += int(random.gauss(2, 0.5))
        v_steps = cumulative_steps

        # Build display line from raw numerics — before health-tagged dict keys exist
        display_line = (
            f"[sim] HR={v_hr:5.1f}  HRV={v_hrv:5.1f}  "
            f"SpO2={v_spo2:5.2f}%  Temp={v_temp:4.2f}\u00b0C  Steps={v_steps}"
        )

        payload = {
            "source": SOURCE,
            "heart_rate_bpm": v_hr,
            "hrv_ms": v_hrv,
            "spo2_pct": v_spo2,
            "skin_temp_c": v_temp,
            "steps": v_steps,
        }

        yield display_line, payload

        elapsed += interval_s
        time.sleep(interval_s)


def main() -> None:
    parser = argparse.ArgumentParser(description="Biometric telemetry simulator (CLONE-701 Week 5)")
    parser.add_argument("--gateway", default=GATEWAY_DEFAULT, help="Telemetry gateway base URL")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between samples")
    args = parser.parse_args()

    ingest_url = f"{args.gateway.rstrip('/')}/ingest"
    print(f"[sim] Starting simulation → {ingest_url}  (interval={args.interval}s)")
    print("[sim] Press Ctrl+C to stop.\n")

    with httpx.Client(timeout=5.0) as client:
        for display_line, payload in sample_stream(args.interval):
            try:
                resp = client.post(ingest_url, json=payload)
                resp.raise_for_status()
                print(display_line, flush=True)
            except httpx.HTTPError as exc:
                print(f"[sim] POST failed: {exc}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
