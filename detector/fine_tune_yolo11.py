"""Fine-tune YOLO11 on a parking dataset using Ultralytics.

This is intentionally a thin wrapper around ``YOLO.train`` so the project has a
repeatable command for P2.2 without introducing a new training framework. Use a
standard Ultralytics dataset YAML that points at train/val images and labels.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultralytics import YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fine-tune YOLO11 on parking data")
    parser.add_argument("--data", required=True, type=Path, help="Ultralytics dataset YAML")
    parser.add_argument("--model", default="yolo11n.pt", help="Base YOLO11 weights")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", default=None, help="Ultralytics device string, e.g. 0 or cpu")
    parser.add_argument("--project", default="runs/parking-spotter")
    parser.add_argument("--name", default="yolo11-parking")
    parser.add_argument("--output", type=Path, help="Optional JSON summary path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model = YOLO(args.model)
    results = model.train(
        data=str(args.data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=args.project,
        name=args.name,
    )

    save_dir = getattr(results, "save_dir", None)
    summary = {
        "baseModel": args.model,
        "data": str(args.data),
        "epochs": args.epochs,
        "imgsz": args.imgsz,
        "batch": args.batch,
        "device": args.device,
        "runDir": str(save_dir) if save_dir is not None else None,
        "bestWeights": str(Path(save_dir) / "weights" / "best.pt") if save_dir is not None else None,
    }
    text = json.dumps(summary, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
