"""Unified CLI for camera and reference-database PCB inspection.

Examples:
    python run_inspection.py --board arduino_uno --camera 0
    python run_inspection.py --board esp32 --image frame.jpg --no-display
    python run_inspection.py --board orange_pi --image inspection_image/Orange_missingV2.png
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import cv2


ROOT = Path(__file__).resolve().parent
CAMERA_BOARDS = {"arduino_uno", "esp32"}
DATABASE_BOARDS = {"arduino_nano", "orange_pi", "raspberry_pi"}
CAMERA_OUTPUT_DIR = ROOT / "runs" / "camera_inspection"
IMAGE_DIR = ROOT / "inspection_image"
BOARD_LABELS = {
    "arduino_uno": "Arduino UNO (kamera)",
    "esp32": "ESP32-WROOM (kamera)",
    "arduino_nano": "Arduino Nano (database)",
    "orange_pi": "Orange Pi 3B V1.2 (database)",
    "raspberry_pi": "Raspberry Pi 4 Model B (database)",
}
DATABASE_IMAGE_FILES = {
    "arduino_nano": ("ArduinoNano.png", "ArduinoNano_missing.png"),
    "orange_pi": ("Orange_Pi_3B_V1.2.png", "Orange_missingV2.png"),
    "raspberry_pi": ("Rapsberry_Pi_4_Model_B.png", "Rapsberry_missing.png"),
}


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]


def camera_index() -> int:
    try:
        return int(os.getenv("PCB_CAMERA_INDEX", "0"))
    except ValueError:
        return 0


def inspect_camera_frame(frame: Any, board_id: str) -> dict[str, Any]:
    from backend.inspection_service import inspect_arduino_uno, inspect_esp32

    inspector: Callable[[Any], dict[str, Any]] = (
        inspect_arduino_uno if board_id == "arduino_uno" else inspect_esp32
    )
    return inspector(frame)


def save_camera_record(frame: Any, result: dict[str, Any], board_id: str) -> Path:
    CAMERA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    capture_id = timestamp()
    input_path = CAMERA_OUTPUT_DIR / f"{board_id}_{capture_id}_input.jpg"
    result_path = CAMERA_OUTPUT_DIR / f"{board_id}_{capture_id}_result.jpg"
    report_path = CAMERA_OUTPUT_DIR / f"{board_id}_{capture_id}.json"
    if not cv2.imwrite(str(input_path), frame):
        raise RuntimeError(f"Frame tidak dapat disimpan: {input_path}")
    source_result = Path(result["result_image"])
    if source_result.exists():
        shutil.copy2(source_result, result_path)
    report = dict(result)
    report.update(
        {
            "capture_id": capture_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "input_image": str(input_path),
            "result_image": str(result_path if result_path.exists() else source_result),
        }
    )
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


def save_database_record(image_path: Path, result: dict[str, Any], board_id: str) -> Path:
    output_dir = ROOT / "runs" / "database_inspection"
    output_dir.mkdir(parents=True, exist_ok=True)
    capture_id = timestamp()
    input_path = output_dir / f"{board_id}_{capture_id}_input{image_path.suffix.lower() or '.jpg'}"
    report_path = output_dir / f"{board_id}_{capture_id}.json"
    shutil.copy2(image_path, input_path)
    report = dict(result)
    report.update(
        {
            "capture_id": capture_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "input_image": str(input_path),
        }
    )
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


def print_result(result: dict[str, Any], report_path: Path | None = None) -> None:
    print("\n" + "=" * 64)
    print(f"{result.get('board', result.get('board_id', 'PCB'))}: {result['status']}")
    print(f"Mode={result.get('mode', 'camera')} | Alignment={result.get('alignment_method', 'n/a')}")
    print(
        f"Reference={result.get('reference_count', 0)} | "
        f"Detected={result.get('detected_count', result.get('reference_count', 0))} | "
        f"Missing={result.get('missing_count', 0)}"
    )
    for item in result.get("missing", []):
        print(
            f"  MISSING: {item.get('component_id', item.get('class', 'component'))} "
            f"at {item.get('center')} score={item.get('missing_score', item.get('confidence', 'n/a'))}"
        )
    if report_path:
        print(f"Report: {report_path}")
    if result.get("result_image"):
        print(f"Result image: {result['result_image']}")
    print("=" * 64)


def run_database_image(board_id: str, image_path: Path) -> int:
    from backend.database_inspection import inspect_database_image

    image = cv2.imread(str(image_path))
    if image is None:
        print(f"ERROR: gambar tidak dapat dibaca: {image_path}")
        return 2
    try:
        result = inspect_database_image(image, board_id)
        report_path = save_database_record(image_path, result, board_id)
    except Exception as exc:
        print(f"INSPECTION ERROR: {exc}")
        return 1
    print_result(result, report_path)
    return 0 if result["status"] == "PASS" else 1


def run_camera_image(board_id: str, image_path: Path, show: bool) -> int:
    image = cv2.imread(str(image_path))
    if image is None:
        print(f"ERROR: gambar tidak dapat dibaca: {image_path}")
        return 2
    try:
        result = inspect_camera_frame(image, board_id)
        report_path = save_camera_record(image, result, board_id)
    except Exception as exc:
        print(f"INSPECTION ERROR: {exc}")
        return 1
    print_result(result, report_path)
    if show:
        annotated = cv2.imread(str(result["result_image"]))
        if annotated is not None:
            cv2.imshow(f"{board_id} inspection", annotated)
            cv2.waitKey(0)
            cv2.destroyAllWindows()
    return 0 if result["status"] == "PASS" else 1


def open_camera(index: int) -> cv2.VideoCapture:
    backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
    camera = cv2.VideoCapture(index, backend)
    if not camera.isOpened():
        camera.release()
        raise RuntimeError(f"Kamera index {index} tidak dapat dibuka. Coba --camera 0/1/2.")
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    return camera


def run_camera(board_id: str, index: int, inspect_once: bool) -> int:
    try:
        camera = open_camera(index)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(f"{board_id} camera inspection aktif | I/SPACE=inspect | S=save | Q=quit")
    last_message = "I/SPACE = INSPECT | Q = QUIT"
    last_color = (0, 255, 255)
    try:
        while True:
            ok, frame = camera.read()
            if not ok or frame is None:
                print("ERROR: frame kamera tidak dapat dibaca.")
                return 2
            preview = frame.copy()
            cv2.rectangle(preview, (10, 10), (min(preview.shape[1] - 10, 940), 62), (0, 0, 0), -1)
            cv2.putText(preview, last_message, (25, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.72, last_color, 2, cv2.LINE_AA)
            cv2.imshow(f"{board_id} camera", preview)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q")):
                return 0
            if key in (ord("s"), ord("S")):
                CAMERA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                path = CAMERA_OUTPUT_DIR / f"{board_id}_{timestamp()}_preview.jpg"
                cv2.imwrite(str(path), frame)
                last_message, last_color = f"Frame tersimpan: {path.name}", (255, 255, 0)
                continue
            if key not in (ord("i"), ord("I"), 32):
                continue
            try:
                result = inspect_camera_frame(frame, board_id)
                report_path = save_camera_record(frame, result, board_id)
                print_result(result, report_path)
                last_message = f"{result['status']} | missing={result['missing_count']}"
                last_color = (0, 255, 0) if result["status"] == "PASS" else (0, 0, 255)
                annotated = cv2.imread(str(result["result_image"]))
                if annotated is not None:
                    cv2.imshow(f"{board_id} result", annotated)
            except Exception as exc:
                print(f"INSPECTION ERROR: {exc}")
                last_message, last_color = "INSPECTION ERROR - cek posisi/pencahayaan PCB", (0, 0, 255)
            if inspect_once:
                cv2.waitKey(0)
                return 0
    finally:
        camera.release()
        cv2.destroyAllWindows()


def choose_board() -> str | None:
    """Show a short board menu when the script is run without --board."""

    board_ids = ["arduino_nano", "orange_pi", "raspberry_pi", "arduino_uno", "esp32"]
    print("\n=== PCB Missing Component Detection ===")
    print("Pilih board:")
    for number, board_id in enumerate(board_ids, start=1):
        print(f"  {number}. {BOARD_LABELS[board_id]}")
    print("  0. Keluar")
    try:
        choice = input("Pilihan: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if choice == "0":
        return None
    try:
        index = int(choice) - 1
        return board_ids[index]
    except (ValueError, IndexError):
        print("Pilihan tidak valid.")
        return None


def choose_database_image(board_id: str) -> Path | None:
    """List the normal/missing samples from inspection_image."""

    configured_files = DATABASE_IMAGE_FILES.get(board_id, ())
    image_paths = [IMAGE_DIR / name for name in configured_files if (IMAGE_DIR / name).exists()]
    if not image_paths:
        image_paths = sorted(
            path
            for path in IMAGE_DIR.iterdir()
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}
        ) if IMAGE_DIR.exists() else []
    if not image_paths:
        print(f"Tidak ada gambar di folder: {IMAGE_DIR}")
        return None

    print(f"\nPilih gambar untuk {BOARD_LABELS[board_id]}:")
    for number, path in enumerate(image_paths, start=1):
        print(f"  {number}. {path.name}")
    print("  0. Batal")
    try:
        choice = input("Pilihan gambar: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if choice == "0":
        return None
    try:
        return image_paths[int(choice) - 1]
    except (ValueError, IndexError):
        print("Pilihan gambar tidak valid.")
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PCB missing-component inspection")
    parser.add_argument(
        "--board",
        choices=sorted(CAMERA_BOARDS | DATABASE_BOARDS),
        help="board; jika dikosongkan, menu interaktif akan ditampilkan",
    )
    parser.add_argument("--image", type=Path, help="inspect one image instead of opening a camera")
    parser.add_argument("--camera", type=int, default=camera_index(), help="OpenCV camera index")
    parser.add_argument("--once", action="store_true", help="inspect one camera frame and exit")
    parser.add_argument("--no-display", action="store_true", help="do not display result for --image")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.board is None:
        args.board = choose_board()
        if args.board is None:
            return 0
    if args.board in DATABASE_BOARDS:
        if not args.image:
            args.image = choose_database_image(args.board)
            if args.image is None:
                return 0
        return run_database_image(args.board, args.image.resolve())
    if args.image:
        return run_camera_image(args.board, args.image.resolve(), show=not args.no_display)
    return run_camera(args.board, args.camera, args.once)


if __name__ == "__main__":
    raise SystemExit(main())
