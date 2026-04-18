"""Detector entry point.

Usage
-----
    python -m detector.main --source 0                     # webcam
    python -m detector.main --source video.mp4             # local file
    python -m detector.main --source rtsp://cam/stream     # RTSP stream
    python -m detector.main --source 0 --preview           # show annotated window
    python -m detector.main --source 0 --config slots.json # custom slot config
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone

import cv2
import httpx

from .auth import current_shared_secret, signed_headers
from .config import CameraConfig, load_config, resolve_backend_url
from .inference import OccupancyDetector
from .source import VideoSource

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

_FALLBACK_CONFIG = CameraConfig(camera_id="demo", slots=[])


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Smart Parking Detector")
    p.add_argument("--source", default="0", help="Video source: int index, file path, or RTSP URL")
    p.add_argument("--config", default="slots.json", help="Path to slot config JSON")
    p.add_argument(
        "--backend-url",
        default=None,
        help="Backend base URL (overrides PARKINGSPOTTER_BACKEND_URL and deprecated backend_url in JSON)",
    )
    p.add_argument("--model", default="yolo11n.pt", help="Ultralytics model name or path")
    p.add_argument("--iou", type=float, default=0.25, help="IoU threshold for occupancy")
    p.add_argument("--debounce", type=int, default=3, help="Frames required to confirm a status change")
    p.add_argument("--skip", type=int, default=2, help="Process every N-th frame (1 = every frame)")
    p.add_argument("--preview", action="store_true", help="Show annotated video window (press q to quit)")
    # ByteTrack / motion-based "soon"
    p.add_argument("--track", action="store_true",
                   help="Enable ByteTrack vehicle tracking for motion-based 'soon' detection")
    p.add_argument("--motion-px", type=float, default=15.0,
                   help="Centroid displacement threshold (pixels) to flag a vehicle as moving (default: 15)")
    p.add_argument("--motion-frames", type=int, default=10,
                   help="Centroid history window (frames) used for motion detection (default: 10)")
    return p.parse_args()


def post_spot(
    backend_url: str,
    camera_id: str,
    slot_id: str,
    lat: float,
    lng: float,
    status: str,
    confidence: float,
) -> None:
    payload = {
        "id": slot_id,
        "lat": lat,
        "lng": lng,
        "status": status,
        "confidence": confidence,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "cameraId": camera_id,
    }
    raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    try:
        with httpx.Client(timeout=3.0) as client:
            client.post(
                f"{backend_url}/spots",
                content=raw_body,
                headers=signed_headers(raw_body),
            )
    except Exception as exc:
        log.warning("Failed to post spot %s: %s", slot_id, exc)


def main() -> None:
    args = parse_args()

    # Parse source: if numeric string treat as webcam index
    source: str | int = args.source
    if isinstance(source, str) and source.isdigit():
        source = int(source)

    # Load slot config
    try:
        cfg = load_config(args.config)
        log.info("Loaded %d slot(s) from %s", len(cfg.slots), args.config)
    except FileNotFoundError:
        log.warning("Config file %r not found — running with no slots (inference only)", args.config)
        cfg = _FALLBACK_CONFIG
    except Exception as exc:
        log.error("Failed to load config: %s", exc)
        sys.exit(1)

    try:
        current_shared_secret()
    except RuntimeError as exc:
        log.error("%s", exc)
        sys.exit(1)

    backend_url = resolve_backend_url(args.backend_url, cfg)
    log.info("Posting detector updates to %s", backend_url)

    def on_update(slot_id: str, status: str, confidence: float) -> None:
        slot = next((s for s in cfg.slots if s.id == slot_id), None)
        if slot is None:
            return
        log.info("Spot %s → %s (conf=%.2f)", slot_id, status, confidence)
        post_spot(backend_url, cfg.camera_id, slot_id, slot.lat, slot.lng, status, confidence)

    if args.track:
        log.info("ByteTrack enabled — motion-based 'soon' active (threshold=%.0fpx, window=%d frames)",
                 args.motion_px, args.motion_frames)

    detector = OccupancyDetector(
        slots=cfg.slots,
        model_name=args.model,
        iou_threshold=args.iou,
        debounce_frames=args.debounce,
        on_update=on_update,
        enable_tracking=args.track,
        motion_window_frames=args.motion_frames,
        motion_threshold_px=args.motion_px,
    )

    log.info("Opening source: %r", source)
    with VideoSource(source, skip_frames=args.skip) as vs:
        for frame in vs.frames():
            detector.process_frame(frame)

            if args.preview:
                annotated = detector.annotate_frame(frame)
                cv2.imshow("Smart Parking Detector", annotated)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

    cv2.destroyAllWindows()
    log.info("Detector stopped.")


if __name__ == "__main__":
    main()
