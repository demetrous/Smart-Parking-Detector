"""HTTP YOLO detector for browser-captured simulation frames.

Run from ``detector/``:

    python -m detector.server --model yolo11n.pt --port 8010

The frontend posts a JPEG/PNG/WebP image body to ``POST /detect`` and receives
vehicle bounding boxes in image pixel coordinates.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import cv2
import httpx
import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from ultralytics import YOLO

from .auth import current_shared_secret, signed_headers
from .inference import VEHICLE_CLASSES

PERSON_CLASS = 0


class DetectionBox(BaseModel):
    classId: int
    className: str
    confidence: float = Field(ge=0.0, le=1.0)
    x1: float
    y1: float
    x2: float
    y2: float


class DetectResponse(BaseModel):
    imageWidth: int
    imageHeight: int
    boxes: list[DetectionBox]
    experimental: dict[str, Any] = Field(default_factory=dict)


class SyncSpot(BaseModel):
    id: str
    lat: float
    lng: float
    status: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class SyncRequest(BaseModel):
    cameraId: str
    spots: list[SyncSpot]
    backendUrl: str | None = None


class GeometryLine(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    length: float


class GeometryResponse(BaseModel):
    imageWidth: int
    imageHeight: int
    lines: list[GeometryLine]


def _decode_image(raw_body: bytes) -> np.ndarray:
    arr = np.frombuffer(raw_body, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="Could not decode image body")
    return frame


def _class_name(names: Any, cls_id: int) -> str:
    if isinstance(names, dict):
        return str(names.get(cls_id, cls_id))
    if isinstance(names, list) and 0 <= cls_id < len(names):
        return str(names[cls_id])
    return str(cls_id)


def detect_boxes(model: YOLO, frame: np.ndarray, *, conf: float, include_people: bool = False) -> DetectResponse:
    height, width = frame.shape[:2]
    boxes: list[DetectionBox] = []
    allowed_classes = VEHICLE_CLASSES | ({PERSON_CLASS} if include_people else set())
    for result in model(frame, verbose=False, conf=conf):
        if result.boxes is None:
            continue
        names = getattr(result, "names", getattr(model, "names", {}))
        for box in result.boxes:
            cls_id = int(box.cls[0].item())
            if cls_id not in allowed_classes:
                continue
            confidence = float(box.conf[0].item()) if getattr(box, "conf", None) is not None else 1.0
            x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
            boxes.append(
                DetectionBox(
                    classId=cls_id,
                    className=_class_name(names, cls_id),
                    confidence=round(confidence, 4),
                    x1=max(0.0, min(x1, width)),
                    y1=max(0.0, min(y1, height)),
                    x2=max(0.0, min(x2, width)),
                    y2=max(0.0, min(y2, height)),
                )
            )
    return DetectResponse(
        imageWidth=width,
        imageHeight=height,
        boxes=boxes,
        experimental={
            "makeModel": {
                "enabled": False,
                "stage": "extension-point",
                "reason": "Requires a fine-grained vehicle classifier trained on the target region.",
            }
        },
    )


def detect_vehicle_boxes(model: YOLO, frame: np.ndarray, *, conf: float) -> DetectResponse:
    return detect_boxes(model, frame, conf=conf, include_people=False)


def detect_geometry_lines(frame: np.ndarray, *, limit: int = 80) -> GeometryResponse:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 80, 180)
    raw_lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=80,
        minLineLength=max(30, min(frame.shape[:2]) // 18),
        maxLineGap=12,
    )
    if raw_lines is None:
        return GeometryResponse(imageWidth=frame.shape[1], imageHeight=frame.shape[0], lines=[])
    lines: list[GeometryLine] = []
    for item in raw_lines[:limit]:
        x1, y1, x2, y2 = [int(v) for v in item[0]]
        lines.append(
            GeometryLine(
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                length=round(float(np.hypot(x2 - x1, y2 - y1)), 2),
            )
        )
    return GeometryResponse(
        imageWidth=frame.shape[1],
        imageHeight=frame.shape[0],
        lines=sorted(lines, key=lambda line: line.length, reverse=True),
    )


def _backend_url(override: str | None = None) -> str:
    return (override or os.getenv("PARKINGSPOTTER_BACKEND_URL") or "http://127.0.0.1:8000").rstrip("/")


def _spot_payload(camera_id: str, spot: SyncSpot) -> bytes:
    payload = {
        "id": spot.id,
        "lat": spot.lat,
        "lng": spot.lng,
        "status": spot.status,
        "confidence": spot.confidence,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "cameraId": camera_id,
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def create_app(model_name: str, cors_origins: list[str] | None = None) -> FastAPI:
    app = FastAPI(title="ParkingSpotter YOLO Detector", version="0.1.0")
    origins = cors_origins or ["http://localhost:5173", "http://127.0.0.1:5173"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @lru_cache(maxsize=1)
    def model() -> YOLO:
        return YOLO(model_name)

    @app.get("/health")
    async def health() -> dict[str, str | bool]:
        return {"ok": True, "model": model_name}

    @app.post("/detect", response_model=DetectResponse)
    async def detect(request: Request, conf: float = 0.25, include_people: bool = False) -> DetectResponse:
        raw_body = await request.body()
        if not raw_body:
            raise HTTPException(status_code=400, detail="Empty image body")
        frame = _decode_image(raw_body)
        return detect_boxes(model(), frame, conf=conf, include_people=include_people)

    @app.post("/geometry/lines", response_model=GeometryResponse)
    async def geometry_lines(request: Request) -> GeometryResponse:
        raw_body = await request.body()
        if not raw_body:
            raise HTTPException(status_code=400, detail="Empty image body")
        frame = _decode_image(raw_body)
        return detect_geometry_lines(frame)

    @app.post("/spots/sync")
    async def sync_spots(payload: SyncRequest) -> dict[str, Any]:
        try:
            current_shared_secret()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        backend_url = _backend_url(payload.backendUrl)
        posted = 0
        errors: list[dict[str, str]] = []
        with httpx.Client(timeout=5.0) as client:
            for spot in payload.spots:
                raw_body = _spot_payload(payload.cameraId, spot)
                try:
                    response = client.post(
                        f"{backend_url}/spots",
                        content=raw_body,
                        headers=signed_headers(raw_body),
                    )
                    response.raise_for_status()
                    posted += 1
                except Exception as exc:
                    errors.append({"spotId": spot.id, "error": str(exc)})
        return {"ok": not errors, "posted": posted, "errors": errors}

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve YOLO detections over HTTP")
    parser.add_argument("--model", default="yolo11n.pt", help="YOLO model name or local weights path")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument(
        "--cors-origin",
        action="append",
        default=None,
        help="Allowed browser origin; can be repeated",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uvicorn.run(
        create_app(args.model, cors_origins=args.cors_origin),
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
