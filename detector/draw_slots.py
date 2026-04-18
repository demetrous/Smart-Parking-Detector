"""Slot polygon drawing tool.

Interactively define parking-slot polygons on a video frame and write the
result to a slots.json file consumed by the detector.

Usage
-----
    # Grab frame 0 from a local video and save to slots.json
    python draw_slots.py --source parking.mp4

    # Start from an existing slots.json (lets you add / edit slots)
    python draw_slots.py --source parking.mp4 --config slots.json

    # Use webcam, jump to frame 60, write to my_slots.json
    python draw_slots.py --source 0 --frame 60 --output my_slots.json

    # Auto-fill lat/lng from pixel centroids using a homography calibration file
    python draw_slots.py --source parking.mp4 --calibration calibration.json

Controls
--------
    Left-click          Add vertex to the current polygon
    Right-click / U     Undo last vertex
    Enter / N           Finish current polygon  →  prompted for slot metadata
    R                   Reset / discard current polygon
    D                   Delete last completed slot
    S                   Save to output file without quitting
    Q / Esc             Save and quit
    ← / →               Step one frame back / forward (video only)
    Space               Pause / resume (video sources)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from calibration import GeoCalibration, load_calibration_optional


# ── colours (BGR) ────────────────────────────────────────────────────────────
COL_DONE = (50, 220, 50)      # completed polygon fill / border
COL_WIP = (50, 180, 255)      # polygon being drawn
COL_VERTEX = (255, 255, 255)  # vertex dot
COL_CURSOR = (0, 220, 255)    # rubber-band line to mouse
COL_LABEL = (255, 255, 255)
COL_BG = (30, 30, 30)         # text background
COL_DELETE = (60, 60, 230)    # last-slot highlight when about to delete


# ── data helpers ─────────────────────────────────────────────────────────────

def _load_existing(path: Path) -> tuple[str, list[dict]]:
    """Return (camera_id, slots_list) from an existing config file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("camera_id", "cam_1"), data.get("slots", [])


def _save(path: Path, camera_id: str, slots: list[dict]) -> None:
    payload = {"camera_id": camera_id, "slots": slots}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[save] Wrote {len(slots)} slot(s) → {path}")


def _polygon_centroid_px(pts: list[tuple[int, int]]) -> tuple[float, float]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _prompt_slot_meta(
    existing_ids: set[str],
    calibration: GeoCalibration | None,
    polygon_px: list[tuple[int, int]],
) -> tuple[str, float, float] | None:
    """Prompt for slot ID (and lat/lng if no calibration). Returns None if user cancels."""
    print("\n─── New slot ───")
    while True:
        raw = input("  Slot ID (e.g. A1) [blank to cancel]: ").strip()
        if not raw:
            return None
        if raw in existing_ids:
            print(f"  ID '{raw}' already used — pick another.")
        else:
            slot_id = raw
            break
    if calibration is not None:
        cx, cy = _polygon_centroid_px(polygon_px)
        lat, lng = calibration.pixel_to_lat_lng(cx, cy)
        print(f"  Using calibration → centroid pixel ({cx:.1f}, {cy:.1f}) → lat {lat:.6f}, lng {lng:.6f}")
        return slot_id, lat, lng
    while True:
        try:
            lat = float(input("  Latitude  (e.g. 47.623): ").strip())
            lng = float(input("  Longitude (e.g. -122.354): ").strip())
            break
        except ValueError:
            print("  Enter valid float values.")
    return slot_id, lat, lng


# ── drawing helpers ───────────────────────────────────────────────────────────

def _draw_polygon(
    canvas: np.ndarray,
    pts: list[tuple[int, int]],
    color: tuple[int, int, int],
    label: str = "",
    filled: bool = True,
) -> None:
    if not pts:
        return
    arr = np.array(pts, dtype=np.int32)
    if filled and len(pts) >= 3:
        overlay = canvas.copy()
        cv2.fillPoly(overlay, [arr], color)
        cv2.addWeighted(overlay, 0.25, canvas, 0.75, 0, canvas)
    cv2.polylines(canvas, [arr], isClosed=(len(pts) >= 3), color=color, thickness=2)
    for p in pts:
        cv2.circle(canvas, p, 4, COL_VERTEX, -1)
    if label and pts:
        cx = int(np.mean([p[0] for p in pts]))
        cy = int(np.mean([p[1] for p in pts]))
        _draw_label(canvas, label, (cx, cy))


def _draw_label(canvas: np.ndarray, text: str, pos: tuple[int, int]) -> None:
    font, scale, thick = cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1
    (tw, th), base = cv2.getTextSize(text, font, scale, thick)
    x, y = pos
    x = max(0, min(x - tw // 2, canvas.shape[1] - tw))
    y = max(th + 4, min(y, canvas.shape[0] - base - 4))
    cv2.rectangle(canvas, (x - 2, y - th - 4), (x + tw + 2, y + base), COL_BG, -1)
    cv2.putText(canvas, text, (x, y), font, scale, COL_LABEL, thick, cv2.LINE_AA)


def _hud(canvas: np.ndarray, lines: list[str]) -> None:
    """Draw a small semi-transparent help panel in the top-left corner."""
    font, scale, thick = cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1
    line_h = 18
    pad = 6
    max_w = max(cv2.getTextSize(l, font, scale, thick)[0][0] for l in lines)
    h = line_h * len(lines) + pad * 2
    w = max_w + pad * 2
    overlay = canvas.copy()
    cv2.rectangle(overlay, (0, 0), (w, h), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.6, canvas, 0.4, 0, canvas)
    for i, line in enumerate(lines):
        cv2.putText(
            canvas, line, (pad, pad + line_h * (i + 1) - 4),
            font, scale, (200, 200, 200), thick, cv2.LINE_AA,
        )


# ── frame grabbing ────────────────────────────────────────────────────────────

def _grab_frame(source: str | int, frame_idx: int) -> np.ndarray:
    """Return a single BGR frame from *source* at position *frame_idx*."""
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        sys.exit(f"[error] Cannot open source: {source!r}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total > 0:
        frame_idx = max(0, min(frame_idx, total - 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        sys.exit("[error] Could not read a frame from source.")
    return frame


def _is_video_file(source: str | int) -> bool:
    if isinstance(source, int):
        return False
    p = Path(source)
    return p.exists() and p.suffix.lower() in {
        ".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".m4v", ".webm",
    }


# ── main tool ─────────────────────────────────────────────────────────────────

class PolygonTool:
    WIN = "ParkingSpotter — Draw Slots"

    def __init__(
        self,
        source: str | int,
        output: Path,
        config: Path | None,
        frame_idx: int,
        calibration: GeoCalibration | None,
    ) -> None:
        self.source = source
        self.output = output
        self.frame_idx = frame_idx
        self._is_video = _is_video_file(source)
        self.calibration = calibration

        # Load existing config or start fresh
        if config and config.exists():
            self.camera_id, self.slots = _load_existing(config)
            print(f"[load] Loaded {len(self.slots)} existing slot(s) from {config}")
        else:
            self.camera_id = "cam_1"
            self.slots: list[dict] = []
        if self.calibration is not None and self.camera_id != self.calibration.camera_id:
            print(
                f"[warn] slots camera_id={self.camera_id!r} differs from "
                f"calibration camera_id={self.calibration.camera_id!r} — align them for multi-camera ingest."
            )
        elif self.calibration is not None and not (config and config.exists()):
            self.camera_id = self.calibration.camera_id

        # Grab base frame
        self._base_frame = _grab_frame(self.source, self.frame_idx)
        self._current_pts: list[tuple[int, int]] = []
        self._mouse_pos: tuple[int, int] = (0, 0)

    # ── mouse callback ────────────────────────────────────────────────────────

    def _on_mouse(self, event: int, x: int, y: int, flags: int, _: object) -> None:
        self._mouse_pos = (x, y)
        if event == cv2.EVENT_LBUTTONDOWN:
            self._current_pts.append((x, y))
        elif event == cv2.EVENT_RBUTTONDOWN:
            self._undo()

    def _undo(self) -> None:
        if self._current_pts:
            self._current_pts.pop()

    # ── render ────────────────────────────────────────────────────────────────

    def _render(self, highlight_last: bool = False) -> np.ndarray:
        canvas = self._base_frame.copy()

        # Draw completed slots
        for i, slot in enumerate(self.slots):
            pts = [tuple(p) for p in slot["polygon"]]
            color = COL_DELETE if (highlight_last and i == len(self.slots) - 1) else COL_DONE
            _draw_polygon(canvas, pts, color, label=slot["id"])  # type: ignore[arg-type]

        # Draw WIP polygon
        if self._current_pts:
            _draw_polygon(canvas, self._current_pts, COL_WIP, filled=False)
            # Rubber-band line to mouse cursor
            cv2.line(canvas, self._current_pts[-1], self._mouse_pos, COL_CURSOR, 1, cv2.LINE_AA)

        # HUD
        hud = [
            "Left-click: add vertex",
            "Right-click / U: undo vertex",
            "Enter / N: finish slot",
            "R: reset current polygon",
            "D: delete last slot",
            "S: save  |  Q/Esc: save & quit",
        ]
        if self._is_video:
            hud += ["← / →: prev / next frame"]
        if self.calibration is not None:
            hud.insert(0, "Calibration: auto lat/lng from polygon centroid")
        _hud(canvas, hud)

        # Status line at bottom
        status = (
            f"Slots: {len(self.slots)}  |  "
            f"Current vertices: {len(self._current_pts)}  |  "
            f"Frame: {self.frame_idx}"
        )
        _draw_label(canvas, status, (canvas.shape[1] // 2, canvas.shape[0] - 10))

        return canvas

    # ── slot completion ────────────────────────────────────────────────────────

    def _finish_slot(self) -> None:
        if len(self._current_pts) < 3:
            print("[warn] Need at least 3 vertices to complete a slot.")
            return
        existing_ids = {s["id"] for s in self.slots}
        meta = _prompt_slot_meta(existing_ids, self.calibration, self._current_pts)
        if meta is None:
            print("[info] Slot cancelled — polygon kept, keep adding vertices or press R to reset.")
            return
        slot_id, lat, lng = meta
        self.slots.append({
            "id": slot_id,
            "lat": lat,
            "lng": lng,
            "polygon": list(self._current_pts),
        })
        print(f"[ok] Added slot '{slot_id}' with {len(self._current_pts)} vertices.")
        self._current_pts = []

    # ── main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        cv2.namedWindow(self.WIN, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(self.WIN, self._on_mouse)

        # Ask for camera metadata once at startup
        print("\n═══ ParkingSpotter — Slot Drawing Tool ═══")
        raw = input(f"  Camera ID [{self.camera_id}]: ").strip()
        if raw:
            self.camera_id = raw
        if self.calibration is not None and self.camera_id != self.calibration.camera_id:
            print(
                f"[warn] Camera ID {self.camera_id!r} ≠ calibration {self.calibration.camera_id!r}."
            )
        print(
            "  Set backend URL via detector --backend-url or PARKINGSPOTTER_BACKEND_URL when you run the detector.\n"
        )
        print(
            "\n  Draw polygons by clicking on the frame.\n"
            "  Press Enter when a polygon is done.\n"
        )

        highlight = False
        while True:
            canvas = self._render(highlight_last=highlight)
            cv2.imshow(self.WIN, canvas)

            key = cv2.waitKey(30) & 0xFF

            if key == 255:  # no key
                continue

            if key in (ord("q"), 27):  # Q or Esc
                _save(self.output, self.camera_id, self.slots)
                break

            elif key in (13, ord("n")):  # Enter or N
                self._finish_slot()
                highlight = False

            elif key in (ord("u"), 8):  # U or Backspace
                self._undo()

            elif key == ord("r"):  # R — reset WIP
                self._current_pts = []
                print("[info] Current polygon reset.")

            elif key == ord("d"):  # D — delete last completed slot
                if not self.slots:
                    print("[warn] No slots to delete.")
                elif not highlight:
                    highlight = True
                    print(f"[warn] Press D again to confirm delete of slot '{self.slots[-1]['id']}'.")
                else:
                    removed = self.slots.pop()
                    print(f"[ok] Deleted slot '{removed['id']}'.")
                    highlight = False

            elif key == ord("s"):  # S — save
                _save(self.output, self.camera_id, self.slots)

            elif self._is_video and key == 81:  # ← left arrow
                self.frame_idx = max(0, self.frame_idx - 1)
                self._base_frame = _grab_frame(self.source, self.frame_idx)

            elif self._is_video and key == 83:  # → right arrow
                self.frame_idx += 1
                self._base_frame = _grab_frame(self.source, self.frame_idx)

            else:
                highlight = False  # any other key cancels delete-confirm

        cv2.destroyAllWindows()


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Interactively draw parking-slot polygons on a video frame.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--source", default="0",
        help="Video source: webcam index (0), file path, or RTSP URL (default: 0)",
    )
    p.add_argument(
        "--output", default="slots.json",
        help="Output slots.json path (default: slots.json)",
    )
    p.add_argument(
        "--config",
        help="Existing slots.json to load and extend (defaults to --output if it exists)",
    )
    p.add_argument(
        "--frame", type=int, default=0,
        help="Frame index to use as the background image (default: 0)",
    )
    p.add_argument(
        "--calibration",
        help=(
            "Path to calibration JSON (see calibration.example.json). "
            "When set, finishing a slot only asks for the spot ID; lat/lng come from the polygon centroid."
        ),
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    source: str | int = args.source
    if isinstance(source, str) and source.isdigit():
        source = int(source)

    output = Path(args.output)

    # Default --config to --output if the output file already exists
    if args.config:
        config = Path(args.config)
    elif output.exists():
        config = output
    else:
        config = None

    cal_path = Path(args.calibration) if args.calibration else None
    calibration = load_calibration_optional(cal_path)
    if calibration is not None:
        print(f"[calibration] Loaded {cal_path} — camera_id={calibration.camera_id!r}")

    tool = PolygonTool(
        source=source,
        output=output,
        config=config,
        frame_idx=args.frame,
        calibration=calibration,
    )
    tool.run()


if __name__ == "__main__":
    main()
