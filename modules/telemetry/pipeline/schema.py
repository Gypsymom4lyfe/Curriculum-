"""
CLONE-701 | Week 4 Lab — Biometric Schema Definitions
Pydantic v2 models for validating and normalising BodyMatrixPayload inputs.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, field_validator


class DataSource(str, Enum):
    apple_health = "apple_health"
    garmin = "garmin"
    oura = "oura"
    ble_custom = "ble_custom"
    simulation = "simulation"


class MetricPoint(BaseModel):
    """A single named biometric measurement."""

    measurement: Annotated[str, Field(min_length=1, max_length=64)]
    value: float
    unit: str = ""

    @field_validator("measurement")
    @classmethod
    def measurement_slug(cls, v: str) -> str:
        """Enforce lowercase snake_case measurement names."""
        normalised = v.strip().lower().replace(" ", "_").replace("-", "_")
        if not normalised.isidentifier():
            raise ValueError(
                f"measurement must be a valid identifier, got: {v!r}"
            )
        return normalised

    @field_validator("value")
    @classmethod
    def finite_value(cls, v: float) -> float:
        import math

        if not math.isfinite(v):
            raise ValueError("metric value must be a finite number")
        return v


class BodyMatrixPayload(BaseModel):
    """
    Top-level container for a biometric telemetry batch.

    Attributes:
        source:     Hardware/platform origin of the data.
        device_id:  Unique identifier for the originating device.
        timestamp:  UTC datetime of data capture (defaults to now).
        metrics:    One or more MetricPoint readings.
    """

    source: DataSource
    device_id: Annotated[str, Field(min_length=1, max_length=128)]
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metrics: Annotated[list[MetricPoint], Field(min_length=1)]

    @field_validator("timestamp")
    @classmethod
    def must_be_utc(cls, v: datetime) -> datetime:
        """Ensure timestamp is UTC-aware."""
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @field_validator("metrics")
    @classmethod
    def no_duplicate_measurements(
        cls, metrics: list[MetricPoint]
    ) -> list[MetricPoint]:
        names = [m.measurement for m in metrics]
        if len(names) != len(set(names)):
            duplicates = {n for n in names if names.count(n) > 1}
            raise ValueError(
                f"Duplicate measurement names in payload: {duplicates}"
            )
        return metrics
