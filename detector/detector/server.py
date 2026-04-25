"""HTTP YOLO detector for browser-captured simulation frames.

Run from ``detector/``:

    python -m detector.server --model yolo11n.pt --port 8010

The frontend posts a JPEG/PNG/WebP image body to ``POST /detect`` and receives
vehicle bounding boxes in image pixel coordinates.
"""

from __future__ import annotations

import argparse
from functools import lru_cache
from typing import Any

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from ultralytics import YOLO

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
    return DetectResponse(imageWidth=width, imageHeight=height, boxes=boxes)


def detect_vehicle_boxes(model: YOLO, frame: np.ndarray, *, conf: float) -> DetectResponse:
    return detect_boxes(model, frame, conf=conf, include_people=False)


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
