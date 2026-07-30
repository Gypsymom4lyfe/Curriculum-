"""
CLONE-701 — Week 4 Lab
Pydantic v2 schema for the BodyMatrixPayload ingestion contract.
All biometric fields are optional so partial device payloads are accepted.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class BodyMatrixPayload(BaseModel):
    """
    Validated container for a single biometric sample frame.

    source       : device or integration identifier (e.g. "garmin", "oura", "apple_health")
    timestamp    : ISO-8601 UTC timestamp; defaults to server time if omitted
    heart_rate_bpm: instantaneous heart rate in beats per minute
    hrv_ms       : heart rate variability (RMSSD) in milliseconds
    spo2_pct     : blood-oxygen saturation percentage (0–100)
    skin_temp_c  : peripheral skin temperature in Celsius
    steps        : cumulative step count for the sample window
    """

    source: str = Field(..., min_length=1, max_length=64)
    timestamp: Optional[datetime] = None

    heart_rate_bpm: Optional[float] = Field(default=None, ge=20, le=300)
    hrv_ms: Optional[float] = Field(default=None, ge=0, le=500)
    spo2_pct: Optional[float] = Field(default=None, ge=50, le=100)
    skin_temp_c: Optional[float] = Field(default=None, ge=20, le=45)
    steps: Optional[int] = Field(default=None, ge=0)

    @field_validator("source")
    @classmethod
    def source_no_spaces(cls, v: str) -> str:
        if " " in v:
            raise ValueError("source must not contain spaces")
        return v.lower()
