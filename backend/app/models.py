from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

SpotStatus = Literal["available", "soon", "occupied"]


class Spot(BaseModel):
    id: str
    lat: float
    lng: float
    status: SpotStatus = Field(default="occupied")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    updatedAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    cameraId: str | None = None


class Event(BaseModel):
    type: str
    payload: dict
