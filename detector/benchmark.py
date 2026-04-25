"""Benchmark ParkingSpotter detector quality and latency on image frames.

Labels are optional. When provided, use JSON Lines with one row per image:

    {"image": "frame001.jpg", "spots": {"A1": "occupied", "A2": "available"}}

Statuses are normalized to occupied/not-occupied for precision and recall, so
``soon`` counts as occupied. Without labels, the tool still reports throughput
and status counts, which is useful for first passes on raw PKLot or pilot clips.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import cv2

from detector.detector.config import load_config
from detector.detector.inference import OccupancyDetector

ACTIVE_STATUSES = {"occupied", "soon"}


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    def add(self, *, expected_active: bool, predicted_active: bool) -> None:
        if expected_active and predicted_active:
            self.tp += 1
        elif not expected_active and predicted_active:
            self.fp += 1
        elif not expected_active and not predicted_active:
            self.tn += 1
        else:
            self.fn += 1

    @property
    def total(self) -> int:
        return self.tp + self.fp + self.tn + self.fn

    def metrics(self) -> dict[str, float | int | None]:
        precision = self.tp / (self.tp + self.fp) if self.tp + self.fp else None
        recall = self.tp / (self.tp + self.fn) if self.tp + self.fn else None
        accuracy = (self.tp + self.tn) / self.total if self.total else None
        return {
            "samples": self.total,
            "tp": self.tp,
            "fp": self.fp,
            "tn": self.tn,
            "fn": self.fn,
            "precision": round(precision, 4) if precision is not None else None,
            "recall": round(recall, 4) if recall is not None else None,
            "accuracy": round(accuracy, 4) if accuracy is not None else None,
        }


def _load_labels(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    labels: dict[str, dict[str, str]] = {}
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        row = json.loads(raw)
        image = str(row["image"])
        spots = row.get("spots")
        if not isinstance(spots, dict):
            raise ValueError(f"{path}:{line_no}: expected object field 'spots'")
        labels[image] = {str(k): str(v) for k, v in spots.items()}
    return labels


def _iter_images(frames_dir: Path) -> list[Path]:
    exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    return sorted(p for p in frames_dir.iterdir() if p.suffix.lower() in exts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark YOLO11 parking occupancy baseline")
    parser.add_argument("--frames-dir", required=True, type=Path, help="Directory of image frames")
    parser.add_argument("--config", required=True, type=Path, help="Slot config JSON")
    parser.add_argument("--labels", type=Path, help="Optional JSONL labels")
    parser.add_argument("--model", default="yolo11n.pt", help="Ultralytics model name or path")
    parser.add_argument("--iou", type=float, default=0.25, help="Slot IoU occupancy threshold")
    parser.add_argument("--track", action="store_true", help="Enable ByteTrack motion mode")
    parser.add_argument("--limit", type=int, default=0, help="Maximum frames to process, 0 = all")
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    images = _iter_images(args.frames_dir)
    if args.limit > 0:
        images = images[: args.limit]
    if not images:
        raise SystemExit(f"No image frames found in {args.frames_dir}")

    labels = _load_labels(args.labels)
    detector = OccupancyDetector(
        slots=cfg.slots,
        model_name=args.model,
        iou_threshold=args.iou,
        debounce_frames=1,
        enable_tracking=args.track,
    )

    counts = Counts()
    latencies_ms: list[float] = []
    status_counts: dict[str, int] = {}
    labeled_frames = 0

    for image_path in images:
        frame = cv2.imread(str(image_path))
        if frame is None:
            raise RuntimeError(f"Could not read frame {image_path}")

        started = time.perf_counter()
        detector.process_frame(frame)
        latencies_ms.append((time.perf_counter() - started) * 1000)
        statuses = detector.snapshot_statuses()
        for status in statuses.values():
            status_counts[status] = status_counts.get(status, 0) + 1

        expected = labels.get(image_path.name) or labels.get(str(image_path.relative_to(args.frames_dir)))
        if expected:
            labeled_frames += 1
            for slot_id, expected_status in expected.items():
                if slot_id not in statuses:
                    continue
                counts.add(
                    expected_active=expected_status in ACTIVE_STATUSES,
                    predicted_active=statuses[slot_id] in ACTIVE_STATUSES,
                )

    latency_report = {
        "frames": len(images),
        "mean_ms": round(statistics.mean(latencies_ms), 2),
        "median_ms": round(statistics.median(latencies_ms), 2),
        "fps": round(1000 / statistics.mean(latencies_ms), 2),
    }
    report = {
        "model": args.model,
        "camera_id": cfg.camera_id,
        "slots": len(cfg.slots),
        "latency": latency_report,
        "status_counts": status_counts,
        "labeled_frames": labeled_frames,
        "occupancy_metrics": counts.metrics(),
    }

    text = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
