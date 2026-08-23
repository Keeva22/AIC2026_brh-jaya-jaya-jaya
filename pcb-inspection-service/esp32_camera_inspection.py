"""Live camera runner for ESP32-WROOM PCB inspection.

The inspection algorithm lives in ``backend.inspection_service``. This file
handles camera capture, keyboard controls, and saving an inspection record so
the algorithm can also be used without the web frontend.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "runs" / "camera_inspection"


def default_camera_index() -> int:
    """Return the configured camera index, preserving the project's default."""

    value = os.getenv("PCB_CAMERA_INDEX", "2")
    try:
        return int(value)
    except ValueError:
        return 2


def camera_backend() -> int:
    """Use DirectShow on Windows and the default backend elsewhere."""

    if sys.platform.startswith("win"):
        return cv2.CAP_DSHOW
    return cv2.CAP_ANY


def open_camera(index: int) -> cv2.VideoCapture:
    camera = cv2.VideoCapture(index, camera_backend())
    if not camera.isOpened():
        camera.release()
        raise RuntimeError(
            f"Kamera index {index} tidak dapat dibuka. "
            "Coba --camera 0/1/2 atau set PCB_CAMERA_INDEX."
        )

    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    return camera


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]


def save_inspection_record(
    frame: Any,
    result: dict[str, Any],
    output_dir: Path,
) -> Path:
    """Save the raw frame, a unique annotated result, and a JSON report."""

    output_dir.mkdir(parents=True, exist_ok=True)
    capture_id = timestamp()

    raw_path = output_dir / f"esp32_{capture_id}_input.jpg"
    result_path = output_dir / f"esp32_{capture_id}_result.jpg"
    report_path = output_dir / f"esp32_{capture_id}.json"

    if not cv2.imwrite(str(raw_path), frame):
        raise RuntimeError(f"Frame tidak dapat disimpan: {raw_path}")

    latest_result = Path(result["result_image"])
    if latest_result.exists():
        shutil.copy2(latest_result, result_path)

    report = dict(result)
    report.update(
        {
            "capture_id": capture_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "input_image": str(raw_path),
            "result_image": str(result_path if result_path.exists() else latest_result),
        }
    )
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


def draw_message(frame: Any, message: str, color: tuple[int, int, int]) -> Any:
    output = frame.copy()
    cv2.rectangle(
        output,
        (10, 10),
        (min(output.shape[1] - 10, 900), 62),
        (0, 0, 0),
        -1,
    )
    cv2.putText(
        output,
        message,
        (25, 45),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        color,
        2,
        cv2.LINE_AA,
    )
    return output


def run_single_image(image_path: Path, show: bool) -> int:
    from backend.inspection_service import inspect_esp32

    frame = cv2.imread(str(image_path))
    if frame is None:
        print(f"ERROR: gambar tidak dapat dibaca: {image_path}")
        return 2

    try:
        result = inspect_esp32(frame)
        report_path = save_inspection_record(frame, result, OUTPUT_DIR)
    except Exception as exc:
        print(f"INSPECTION ERROR: {exc}")
        return 1

    print_result(result, report_path)
    if show:
        annotated = cv2.imread(str(result["result_image"]))
        if annotated is not None:
            cv2.imshow("ESP32 Inspection Result", annotated)
            cv2.waitKey(0)
            cv2.destroyAllWindows()
    return 0 if result["status"] == "PASS" else 1


def print_result(result: dict[str, Any], report_path: Path) -> None:
    print("\n" + "=" * 58)
    print(f"ESP32-WROOM: {result['status']}")
    print(f"Alignment={result.get('alignment_method', 'unknown')}")
    print(
        f"Reference={result['reference_count']} | "
        f"Detected={result['detected_count']} | "
        f"Matched={result['matched_count']} | "
        f"Missing={result['missing_count']} | "
        f"Recovered={result.get('recovered_count', 0)}"
    )
    for item in result.get("missing", []):
        print(f"  MISSING: {item['class']} at {item['center']}")
    print(f"Report: {report_path}")
    print("=" * 58)


def run_camera(camera_index: int, inspect_once: bool) -> int:
    from backend.inspection_service import inspect_esp32

    try:
        camera = open_camera(camera_index)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 2

    print("ESP32 camera inspection aktif")
    print("I/SPACE = inspect | S = simpan frame | Q = keluar")
    print(f"Camera index: {camera_index}")

    last_message = "I/SPACE = INSPECT | Q = QUIT"
    last_color = (0, 255, 255)
    try:
        while True:
            ok, frame = camera.read()
            if not ok or frame is None:
                print("ERROR: frame kamera tidak dapat dibaca.")
                return 2

            display = draw_message(frame, last_message, last_color)
            cv2.imshow("ESP32 Camera Inspection", display)
            key = cv2.waitKey(1) & 0xFF

            if key in (ord("q"), ord("Q")):
                return 0

            if key in (ord("s"), ord("S")):
                OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                path = OUTPUT_DIR / f"esp32_{timestamp()}_preview.jpg"
                cv2.imwrite(str(path), frame)
                last_message = f"Frame tersimpan: {path.name}"
                last_color = (255, 255, 0)
                continue

            if key not in (ord("i"), ord("I"), 32):
                continue

            print("\nMenjalankan inspeksi ESP32...")
            try:
                result = inspect_esp32(frame)
                report_path = save_inspection_record(frame, result, OUTPUT_DIR)
                print_result(result, report_path)
                last_message = f"{result['status']} | missing={result['missing_count']}"
                last_color = (0, 255, 0) if result["status"] == "PASS" else (0, 0, 255)

                annotated = cv2.imread(str(result["result_image"]))
                if annotated is not None:
                    cv2.imshow("ESP32 Inspection Result", annotated)
            except Exception as exc:
                print(f"INSPECTION ERROR: {exc}")
                last_message = "INSPECTION ERROR - cek posisi/pencahayaan PCB"
                last_color = (0, 0, 255)

            if inspect_once:
                cv2.waitKey(0)
                return 0
    finally:
        camera.release()
        cv2.destroyAllWindows()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspeksi ESP32-WROOM dengan kamera dan best.pt"
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=default_camera_index(),
        help="index kamera OpenCV (default: PCB_CAMERA_INDEX atau 2)",
    )
    parser.add_argument(
        "--image",
        type=Path,
        help="inspeksi satu file gambar, tanpa membuka kamera",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="ambil satu inspeksi lalu keluar",
    )
    parser.add_argument(
        "--no-display",
        action="store_true",
        help="khusus mode --image: jangan tampilkan jendela hasil",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.image:
        return run_single_image(args.image.resolve(), show=not args.no_display)
    return run_camera(args.camera, inspect_once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
