from __future__ import annotations

import importlib
import sys
import types

fake_ultralytics = types.ModuleType("ultralytics")
fake_ultralytics.YOLO = object
sys.modules.setdefault("ultralytics", fake_ultralytics)

benchmark = importlib.import_module("detector.benchmark")


def test_counts_metrics_binary_occupancy() -> None:
    counts = benchmark.Counts()
    counts.add(expected_active=True, predicted_active=True)
    counts.add(expected_active=False, predicted_active=True)
    counts.add(expected_active=False, predicted_active=False)
    counts.add(expected_active=True, predicted_active=False)

    assert counts.metrics() == {
        "samples": 4,
        "tp": 1,
        "fp": 1,
        "tn": 1,
        "fn": 1,
        "precision": 0.5,
        "recall": 0.5,
        "accuracy": 0.5,
    }


def test_load_labels_jsonl(tmp_path) -> None:
    labels_path = tmp_path / "labels.jsonl"
    labels_path.write_text(
        '{"image":"frame001.jpg","spots":{"A1":"occupied","A2":"available"}}\n',
        encoding="utf-8",
    )

    labels = benchmark._load_labels(labels_path)

    assert labels == {
        "frame001.jpg": {
            "A1": "occupied",
            "A2": "available",
        }
    }
