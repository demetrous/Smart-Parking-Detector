from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone

HEADER_TIMESTAMP = "X-ParkingSpotter-Timestamp"
HEADER_SIGNATURE = "X-ParkingSpotter-Signature"
SECRET_ENV = "PARKINGSPOTTER_SHARED_SECRET"


def current_shared_secret() -> bytes:
    secret = os.getenv(SECRET_ENV, "").strip()
    if not secret:
        raise RuntimeError(f"{SECRET_ENV} is not configured")
    return secret.encode("utf-8")


def signed_headers(raw_body: bytes, now: datetime | None = None) -> dict[str, str]:
    current = now or datetime.now(timezone.utc)
    timestamp = current.isoformat()
    signature = hmac.new(
        current_shared_secret(),
        timestamp.encode("utf-8") + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        HEADER_TIMESTAMP: timestamp,
        HEADER_SIGNATURE: signature,
    }
