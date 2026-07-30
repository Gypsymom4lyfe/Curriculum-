"""
CLONE-701 — Week 4: Biometric Schema (Pydantic v2)

Defines BodyMatrixPayload — the canonical validated structure for all
inbound biometric readings. Any upstream source (Apple Health, Garmin,
Oura, custom BLE) must be normalised into this shape before ingestion.
"""

from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, Field, field_validator


class BodyMatrixPayload(BaseModel):
    """
    Canonical biometric reading from any supported hardware source.

    All numeric ranges reflect physiologically plausible values for an
    adult human at rest or during light-to-moderate activity.
    """

    subject_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique identifier for the monitored subject.",
    )
    source: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Hardware or integration source label (e.g. 'oura', 'garmin').",
    )
    timestamp: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp of the reading. Defaults to server time if omitted.",
    )

    # --- Cardiovascular ---
    heart_rate: Annotated[float, Field(ge=20.0, le=250.0, description="Heart rate in BPM.")]
    hrv_ms: Annotated[float, Field(ge=0.0, le=300.0, description="Heart rate variability in milliseconds (RMSSD).")]
    spo2_pct: Annotated[float, Field(ge=70.0, le=100.0, description="Blood oxygen saturation percentage.")]

    # --- Thermoregulation ---
    skin_temp_c: Annotated[float, Field(ge=25.0, le=42.0, description="Skin surface temperature in Celsius.")]

    # --- Respiratory ---
    respiratory_rate: Annotated[float, Field(ge=4.0, le=60.0, description="Breaths per minute.")]

    # --- Recovery ---
    sleep_score: Annotated[int, Field(ge=0, le=100, description="Composite sleep quality score (0–100).")]

    @field_validator("subject_id", "source", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()

    model_config = {"str_strip_whitespace": True}
