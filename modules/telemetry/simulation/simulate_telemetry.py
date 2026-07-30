"""
CLONE-701 | Week 5 Lab — Synthetic Physiology Simulator
Multi-state random-walk simulation of human biometric telemetry.

States
------
  RECOVERY   : Sleep / rest — HRV rises, HR low, SpO2 stable high.
  BASELINE   : Awake at rest — typical daytime physiology.
  STRESS     : Active / cognitive load — HRV drops, HR rises.
  EXHAUSTION : Prolonged stress — HRV bottoms, HR elevated, SpO2 may dip.

Usage
-----
  python simulate_telemetry.py [--url URL] [--interval SECONDS] [--duration SECONDS]

  Defaults: POST to http://localhost:8000/ingest every 5 seconds indefinitely.
"""

import argparse
import json
import math
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

try:
    import urllib.request as _urllib
except ImportError:
    _urllib = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Physiological state definitions
# ---------------------------------------------------------------------------

class PhysioState(str, Enum):
    RECOVERY = "RECOVERY"
    BASELINE = "BASELINE"
    STRESS = "STRESS"
    EXHAUSTION = "EXHAUSTION"


@dataclass
class StateProfile:
    """Target ranges and random-walk step sizes for a physiological state."""

    hrv_target: float    # ms
    hr_target: float     # bpm
    spo2_target: float   # %
    hrv_step: float = 1.5
    hr_step: float = 1.0
    spo2_step: float = 0.1


STATE_PROFILES: dict[PhysioState, StateProfile] = {
    PhysioState.RECOVERY:   StateProfile(hrv_target=75.0, hr_target=52.0,  spo2_target=98.5),
    PhysioState.BASELINE:   StateProfile(hrv_target=55.0, hr_target=68.0,  spo2_target=98.0),
    PhysioState.STRESS:     StateProfile(hrv_target=28.0, hr_target=92.0,  spo2_target=97.5),
    PhysioState.EXHAUSTION: StateProfile(hrv_target=18.0, hr_target=102.0, spo2_target=96.5),
}

# Transition probability matrix  (from → to)
TRANSITION_MATRIX: dict[PhysioState, dict[PhysioState, float]] = {
    PhysioState.RECOVERY: {
        PhysioState.RECOVERY:   0.80,
        PhysioState.BASELINE:   0.18,
        PhysioState.STRESS:     0.02,
        PhysioState.EXHAUSTION: 0.00,
    },
    PhysioState.BASELINE: {
        PhysioState.RECOVERY:   0.05,
        PhysioState.BASELINE:   0.70,
        PhysioState.STRESS:     0.23,
        PhysioState.EXHAUSTION: 0.02,
    },
    PhysioState.STRESS: {
        PhysioState.RECOVERY:   0.02,
        PhysioState.BASELINE:   0.25,
        PhysioState.STRESS:     0.60,
        PhysioState.EXHAUSTION: 0.13,
    },
    PhysioState.EXHAUSTION: {
        PhysioState.RECOVERY:   0.00,
        PhysioState.BASELINE:   0.10,
        PhysioState.STRESS:     0.35,
        PhysioState.EXHAUSTION: 0.55,
    },
}


def _weighted_choice(distribution: dict[PhysioState, float]) -> PhysioState:
    """Select a state according to probability weights."""
    r = random.random()
    cumulative = 0.0
    for state, prob in distribution.items():
        cumulative += prob
        if r < cumulative:
            return state
    return list(distribution.keys())[-1]


# ---------------------------------------------------------------------------
# Simulator core
# ---------------------------------------------------------------------------

@dataclass
class TelemetrySimulator:
    device_id: str = "sim-device-001"
    initial_state: PhysioState = PhysioState.BASELINE

    _state: PhysioState = field(init=False)
    _hrv: float = field(init=False)
    _hr: float = field(init=False)
    _spo2: float = field(init=False)

    def __post_init__(self) -> None:
        self._state = self.initial_state
        profile = STATE_PROFILES[self._state]
        self._hrv = profile.hrv_target
        self._hr = profile.hr_target
        self._spo2 = profile.spo2_target

    def _random_walk(
        self, current: float, target: float, step: float, lo: float, hi: float
    ) -> float:
        """Move *current* one step toward *target* with Gaussian noise."""
        direction = 1.0 if target > current else -1.0
        noise = random.gauss(0, step * 0.5)
        next_val = current + direction * step + noise
        return max(lo, min(hi, next_val))

    def step(self) -> dict[str, Any]:
        """Advance simulation by one tick; return a BodyMatrixPayload dict."""
        # Maybe transition state
        self._state = _weighted_choice(TRANSITION_MATRIX[self._state])
        profile = STATE_PROFILES[self._state]

        self._hrv = self._random_walk(
            self._hrv, profile.hrv_target, profile.hrv_step, lo=5.0, hi=150.0
        )
        self._hr = self._random_walk(
            self._hr, profile.hr_target, profile.hr_step, lo=35.0, hi=180.0
        )
        self._spo2 = self._random_walk(
            self._spo2, profile.spo2_target, profile.spo2_step, lo=88.0, hi=100.0
        )

        return {
            "source": "simulation",
            "device_id": self.device_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": [
                {"measurement": "hrv_ms",         "value": round(self._hrv, 2),  "unit": "ms"},
                {"measurement": "heart_rate_bpm",  "value": round(self._hr, 1),   "unit": "bpm"},
                {"measurement": "spo2_pct",        "value": round(self._spo2, 2), "unit": "%"},
            ],
        }

    @property
    def current_state(self) -> PhysioState:
        return self._state


# ---------------------------------------------------------------------------
# HTTP delivery
# ---------------------------------------------------------------------------

def post_payload(url: str, payload: dict[str, Any]) -> int:
    """POST *payload* as JSON to *url*; return HTTP status code."""
    body = json.dumps(payload).encode()
    req = _urllib.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _urllib.urlopen(req, timeout=10) as resp:
        return resp.status


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate biometric telemetry and POST to the ingestion gateway."
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000/ingest",
        help="Gateway ingest endpoint (default: http://localhost:8000/ingest)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Seconds between telemetry ticks (default: 5)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Total run time in seconds; 0 = run indefinitely (default: 0)",
    )
    parser.add_argument(
        "--device-id",
        default="sim-device-001",
        help="Simulated device identifier (default: sim-device-001)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print payloads to stdout instead of POSTing to the gateway.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sim = TelemetrySimulator(device_id=args.device_id)
    start = time.monotonic()
    tick = 0

    print(f"[simulate_telemetry] Starting simulation → {args.url}")
    print(f"  interval={args.interval}s  duration={'∞' if args.duration == 0 else f'{args.duration}s'}")
    print("  Press Ctrl+C to stop.\n")

    try:
        while True:
            tick += 1
            payload = sim.step()

            if args.dry_run:
                print(f"[tick {tick:>4}] state={sim.current_state.value:<10} "
                      f"HRV={payload['metrics'][0]['value']:>6.2f}ms  "
                      f"HR={payload['metrics'][1]['value']:>5.1f}bpm  "
                      f"SpO2={payload['metrics'][2]['value']:>5.2f}%")
            else:
                try:
                    status = post_payload(args.url, payload)
                    print(f"[tick {tick:>4}] state={sim.current_state.value:<10} "
                          f"HTTP {status}  "
                          f"HRV={payload['metrics'][0]['value']:>6.2f}ms  "
                          f"HR={payload['metrics'][1]['value']:>5.1f}bpm  "
                          f"SpO2={payload['metrics'][2]['value']:>5.2f}%")
                except Exception as exc:
                    print(f"[tick {tick:>4}] POST failed: {exc}", file=sys.stderr)

            if args.duration > 0 and (time.monotonic() - start) >= args.duration:
                break

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n[simulate_telemetry] Stopped by user.")


if __name__ == "__main__":
    main()
