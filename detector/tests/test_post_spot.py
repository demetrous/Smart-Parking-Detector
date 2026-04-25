from __future__ import annotations

import importlib
import sys
import types

import httpx

fake_ultralytics = types.ModuleType("ultralytics")
fake_ultralytics.YOLO = object
sys.modules.setdefault("ultralytics", fake_ultralytics)

main = importlib.import_module("detector.detector.main")


def test_post_spot_logs_backend_rejection(monkeypatch, caplog) -> None:
    class FakeClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def post(self, *_: object, **__: object) -> httpx.Response:
            request = httpx.Request("POST", "http://backend/spots")
            return httpx.Response(403, text="bad signature", request=request)

    monkeypatch.setenv("PARKINGSPOTTER_SHARED_SECRET", "secret")
    monkeypatch.setattr(main.httpx, "Client", FakeClient)

    with caplog.at_level("WARNING"):
        main.post_spot(
            "http://backend",
            "cam_1",
            "A1",
            47.0,
            -122.0,
            "occupied",
            0.9,
        )

    assert "Backend rejected spot A1 update with HTTP 403" in caplog.text
