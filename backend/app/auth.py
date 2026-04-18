from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone

from fastapi import HTTPException, status

HEADER_TIMESTAMP = "X-ParkingSpotter-Timestamp"
HEADER_SIGNATURE = "X-ParkingSpotter-Signature"
SECRET_ENV = "PARKINGSPOTTER_SHARED_SECRET"
MAX_AGE_ENV = "PARKINGSPOTTER_MAX_SIGNATURE_AGE_SECONDS"


def current_shared_secret() -> bytes:
    secret = os.getenv(SECRET_ENV, "").strip()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{SECRET_ENV} is not configured",
        )
    return secret.encode("utf-8")


def _parse_timestamp(raw_timestamp: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed detector timestamp",
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def compute_signature(secret: bytes, timestamp: str, raw_body: bytes) -> str:
    signed = timestamp.encode("utf-8") + b"." + raw_body
    return hmac.new(secret, signed, hashlib.sha256).hexdigest()


def verify_signed_detector_request(
    *,
    raw_body: bytes,
    timestamp: str | None,
    signature: str | None,
    now: datetime | None = None,
) -> None:
    if not timestamp or not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing detector authentication headers",
        )

    parsed = _parse_timestamp(timestamp)
    max_age = int(os.getenv(MAX_AGE_ENV, "30"))
    current = now or datetime.now(timezone.utc)
    if abs((current - parsed).total_seconds()) > max_age:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Detector signature is stale",
        )

    expected = compute_signature(current_shared_secret(), timestamp, raw_body)
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid detector signature",
        )
