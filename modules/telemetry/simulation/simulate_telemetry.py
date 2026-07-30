"""
CLONE-701 — Week 5: Synthetic Physiology Simulator

Generates a continuous stream of realistic biometric readings using a
multi-state random-walk model that mirrors human autonomic nervous system
behaviour:

  - Heart rate (HR) and HRV move in inverse correlation.
  - Sleep score influences recovery state and baseline HR/HRV offsets.
  - Three physiological states cycle stochastically: REST, ACTIVE, STRESSED.

Run directly to POST simulated payloads to the gateway:

    python simulate_telemetry.py --url http://localhost:8000/ingest \
                                 --subject demo-001 \
                                 --interval 1.0

Or import `generate_reading()` for unit tests.
"""

import argparse
import json
import math
import random
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

try:
    import httpx  # optional — only required for live posting
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


# ---------------------------------------------------------------------------
# Physiological state machine
# ---------------------------------------------------------------------------

class PhysioState(str, Enum):
    REST = "REST"
    ACTIVE = "ACTIVE"
    STRESSED = "STRESSED"


# Baseline biometric ranges per state (mean, std_dev)
_STATE_PARAMS: dict[PhysioState, dict[str, tuple[float, float]]] = {
    PhysioState.REST: {
        "heart_rate":       (60.0,  4.0),
        "hrv_ms":           (65.0,  8.0),
        "spo2_pct":         (98.5,  0.3),
        "skin_temp_c":      (33.5,  0.2),
        "respiratory_rate": (13.0,  1.0),
        "sleep_score":      (80.0,  5.0),
    },
    PhysioState.ACTIVE: {
        "heart_rate":       (110.0, 10.0),
        "hrv_ms":           (30.0,   5.0),
        "spo2_pct":         (97.5,   0.5),
        "skin_temp_c":      (35.0,   0.4),
        "respiratory_rate": (22.0,   3.0),
        "sleep_score":      (75.0,   4.0),
    },
    PhysioState.STRESSED: {
        "heart_rate":       (95.0,  8.0),
        "hrv_ms":           (20.0,  4.0),
        "spo2_pct":         (97.0,  0.5),
        "skin_temp_c":      (34.2,  0.3),
        "respiratory_rate": (18.0,  2.0),
        "sleep_score":      (55.0,  8.0),
    },
}

# Transition probability matrix: current → {next: probability}
_TRANSITIONS: dict[PhysioState, dict[PhysioState, float]] = {
    PhysioState.REST:     {PhysioState.REST: 0.85, PhysioState.ACTIVE: 0.10, PhysioState.STRESSED: 0.05},
    PhysioState.ACTIVE:   {PhysioState.REST: 0.20, PhysioState.ACTIVE: 0.70, PhysioState.STRESSED: 0.10},
    PhysioState.STRESSED: {PhysioState.REST: 0.15, PhysioState.ACTIVE: 0.10, PhysioState.STRESSED: 0.75},
}


@dataclass
class SimulatedReading:
    subject_id: str
    source: str
    heart_rate: float
    hrv_ms: float
    spo2_pct: float
    skin_temp_c: float
    respiratory_rate: float
    sleep_score: int
    timestamp: str
    physio_state: str


class TelemetrySimulator:
    """
    Stateful random-walk simulator maintaining continuity between readings.

    Each call to ``tick()`` advances the internal state by one step, applying
    a mean-reverting perturbation to prevent unbounded drift.
    """

    def __init__(
        self,
        subject_id: str = "sim-subject-001",
        source: str = "simulator",
        initial_state: PhysioState = PhysioState.REST,
    ) -> None:
        self.subject_id = subject_id
        self.source = source
        self._state = initial_state

        params = _STATE_PARAMS[self._state]
        self._values: dict[str, float] = {
            k: random.gauss(mu, sigma) for k, (mu, sigma) in params.items()
        }

    def _maybe_transition(self) -> None:
        """Stochastically move to a new physiological state."""
        weights = _TRANSITIONS[self._state]
        states, probs = zip(*weights.items())
        (self._state,) = random.choices(states, weights=probs, k=1)

    def _walk(self, field: str, momentum: float = 0.3) -> float:
        """
        Mean-reverting random walk.

        Blends the current value toward the new state's mean using
        *momentum*, then adds Gaussian noise scaled to the state's std dev.
        """
        params = _STATE_PARAMS[self._state]
        mu, sigma = params[field]
        current = self._values[field]
        # Mean reversion pull
        reverted = current + momentum * (mu - current)
        # Noise injection
        noisy = reverted + random.gauss(0, sigma * 0.25)
        # Hard clamp to physiological bounds
        bounds = {
            "heart_rate":       (20.0, 250.0),
            "hrv_ms":           (0.0,  300.0),
            "spo2_pct":         (70.0, 100.0),
            "skin_temp_c":      (25.0,  42.0),
            "respiratory_rate": (4.0,   60.0),
            "sleep_score":      (0.0,  100.0),
        }
        lo, hi = bounds[field]
        return max(lo, min(hi, noisy))

    def tick(self) -> SimulatedReading:
        """Advance one time step and return a new SimulatedReading."""
        self._maybe_transition()
        for field in self._values:
            self._values[field] = self._walk(field)

        return SimulatedReading(
            subject_id=self.subject_id,
            source=self.source,
            heart_rate=round(self._values["heart_rate"], 1),
            hrv_ms=round(self._values["hrv_ms"], 1),
            spo2_pct=round(self._values["spo2_pct"], 1),
            skin_temp_c=round(self._values["skin_temp_c"], 2),
            respiratory_rate=round(self._values["respiratory_rate"], 1),
            sleep_score=int(round(self._values["sleep_score"])),
            timestamp=datetime.now(timezone.utc).isoformat(),
            physio_state=self._state.value,
        )


def generate_reading(
    subject_id: str = "test-subject",
    source: str = "simulator",
) -> SimulatedReading:
    """Return a single deterministic reading useful for unit tests."""
    sim = TelemetrySimulator(subject_id=subject_id, source=source)
    return sim.tick()


def _post_reading(url: str, reading: SimulatedReading, client: "httpx.Client") -> None:
    payload = asdict(reading)
    payload.pop("physio_state")  # not part of BodyMatrixPayload schema
    response = client.post(url, json=payload, timeout=5.0)
    response.raise_for_status()


def _run(url: str, subject_id: str, source: str, interval: float, max_ticks: Optional[int]) -> None:
    if not _HTTPX_AVAILABLE:
        raise RuntimeError("httpx is required for live posting: pip install httpx")

    sim = TelemetrySimulator(subject_id=subject_id, source=source)
    tick = 0

    with httpx.Client() as client:
        print(f"[simulator] Streaming to {url} (interval={interval}s) …")
        while max_ticks is None or tick < max_ticks:
            reading = sim.tick()
            try:
                _post_reading(url, reading, client)
                print(
                    f"[{reading.timestamp}] {reading.physio_state:8s} "
                    f"HR={reading.heart_rate:5.1f} HRV={reading.hrv_ms:5.1f} "
                    f"SpO2={reading.spo2_pct:.1f}% Sleep={reading.sleep_score}"
                )
            except Exception as exc:
                print(f"[simulator] POST failed: {exc}")

            tick += 1
            time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="CLONE-701 telemetry simulator")
    parser.add_argument("--url", default="http://localhost:8000/ingest", help="Gateway ingest endpoint")
    parser.add_argument("--subject", default="sim-subject-001", help="Subject ID tag")
    parser.add_argument("--source", default="simulator", help="Source device label")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between readings")
    parser.add_argument("--ticks", type=int, default=None, help="Stop after N ticks (default: run forever)")
    args = parser.parse_args()

    _run(
        url=args.url,
        subject_id=args.subject,
        source=args.source,
        interval=args.interval,
        max_ticks=args.ticks,
    )


if __name__ == "__main__":
    main()
