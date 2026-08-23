"""FastAPI entry point for the hackathon demo."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


app = FastAPI(
    title="PCB Missing Component Detection",
    description="Camera inspection for Arduino UNO/ESP32 and reference-database inspection for other boards.",
    version="2.0.0",
)

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
INSPECTION_IMAGE_DIR = ROOT / "inspection_image"
REFERENCE_DIR = ROOT / "reference_database"
RUNS_DIR = ROOT / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

BOARD_CATALOG = [
    {
        "id": "arduino_uno",
        "name": "Arduino UNO",
        "short_name": "UNO",
        "mode": "camera",
        "tag": "LIVE CAMERA",
        "description": "Inspeksi real-time dengan kamera dan YOLO.",
        "reference_image": "/media/reference/ArduinoUno_reference.jpg",
    },
    {
        "id": "esp32",
        "name": "ESP32-WROOM",
        "short_name": "ESP32",
        "mode": "camera",
        "tag": "LIVE CAMERA",
        "description": "Alignment papan lalu deteksi komponen kamera.",
        "reference_image": "/media/reference/ESP32_WROOM_reference.jpg",
    },
    {
        "id": "arduino_nano",
        "name": "Arduino Nano",
        "short_name": "NANO",
        "mode": "database",
        "tag": "REFERENCE DB",
        "description": "Perbandingan slot komponen terhadap reference normal.",
        "reference_image": "/media/inspection/ArduinoNano.png",
        "sample_images": [
            {"label": "Normal", "url": "/media/inspection/ArduinoNano.png"},
            {"label": "Missing component", "url": "/media/inspection/ArduinoNano_missing.png"},
            {"label": "Missing / user sample 01", "url": "/media/inspection/ArduinoNano_missing_user_01.png"},
        ],
    },
    {
        "id": "orange_pi",
        "name": "Orange Pi 3B V1.2",
        "short_name": "ORANGE PI",
        "mode": "database",
        "tag": "REFERENCE DB",
        "description": "Deteksi perubahan komponen dari citra reference.",
        "reference_image": "/media/inspection/Orange_Pi_3B_V1.2.png",
        "sample_images": [
            {"label": "Normal", "url": "/media/inspection/Orange_Pi_3B_V1.2.png"},
            {"label": "Missing component", "url": "/media/inspection/Orange_missingV2.png"},
            {"label": "Missing / user sample 01", "url": "/media/inspection/Orange_missing_user_01.png"},
            {"label": "Missing / user sample 02", "url": "/media/inspection/Orange_missing_user_02.png"},
            {"label": "Missing / user sample 03", "url": "/media/inspection/Orange_missing_user_03.png"},
            {"label": "Missing / user sample 04", "url": "/media/inspection/Orange_missing_user_04.png"},
        ],
    },
    {
        "id": "raspberry_pi",
        "name": "Raspberry Pi 4 Model B",
        "short_name": "RASPBERRY PI",
        "mode": "database",
        "tag": "REFERENCE DB",
        "description": "Perbandingan database dengan penanda lokasi hilang.",
        "reference_image": "/media/inspection/Rapsberry_Pi_4_Model_B.png",
        "sample_images": [
            {"label": "Normal", "url": "/media/inspection/Rapsberry_Pi_4_Model_B.png"},
            {"label": "Missing component", "url": "/media/inspection/Rapsberry_missing.png"},
            {"label": "Missing / user sample 01", "url": "/media/inspection/Raspberry_missing_user_01.png"},
            {"label": "Missing / user sample 02", "url": "/media/inspection/Raspberry_missing_user_02.png"},
            {"label": "Missing / user sample 03", "url": "/media/inspection/Raspberry_missing_user_03.png"},
            {"label": "Missing / user sample 04", "url": "/media/inspection/Raspberry_missing_user_04.png"},
        ],
    },
]
BOARD_MODES = {item["id"]: item["mode"] for item in BOARD_CATALOG}


@app.get("/")
def root():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/boards")
def get_boards() -> dict[str, Any]:
    return {"boards": BOARD_CATALOG}


def _media_url(value: Any) -> Any:
    """Convert internal result paths into safe URLs understood by the UI."""

    if not isinstance(value, str):
        return value
    candidate = Path(value)
    if not candidate.is_absolute():
        return value
    try:
        resolved = candidate.resolve()
        media_roots = (
            (INSPECTION_IMAGE_DIR, "/media/inspection/"),
            (REFERENCE_DIR, "/media/reference/"),
            (RUNS_DIR, "/media/runs/"),
        )
        for media_root, prefix in media_roots:
            root = media_root.resolve()
            if resolved == root or root in resolved.parents:
                relative = resolved.relative_to(root).as_posix()
                return f"{prefix}{relative}"
    except (OSError, ValueError):
        pass
    return value


def _public_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return the detector payload with browser-friendly image URLs."""

    payload = dict(result)
    for key in ("result_image", "aligned_image", "reference_image"):
        if key in payload:
            payload[key] = _media_url(payload[key])
    return payload


@app.post("/api/inspect/{board_id}")
async def inspect_upload(board_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    board_id = board_id.lower().strip()
    if board_id not in BOARD_MODES:
        raise HTTPException(status_code=404, detail=f"Board tidak dikenal: {board_id}")
    payload = await file.read()
    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="File bukan gambar yang dapat dibaca OpenCV")
    try:
        if BOARD_MODES[board_id] == "database":
            from backend.database_inspection import inspect_database_image

            return _public_result(inspect_database_image(image, board_id))
        from backend.inspection_service import inspect_arduino_uno, inspect_esp32

        inspector = inspect_arduino_uno if board_id == "arduino_uno" else inspect_esp32
        return _public_result(inspector(image))
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


app.mount("/media/inspection", StaticFiles(directory=INSPECTION_IMAGE_DIR), name="inspection-media")
app.mount("/media/reference", StaticFiles(directory=REFERENCE_DIR), name="reference-media")
app.mount("/media/runs", StaticFiles(directory=RUNS_DIR), name="runs-media")
app.mount("/web", StaticFiles(directory=WEB_DIR), name="web-assets")
