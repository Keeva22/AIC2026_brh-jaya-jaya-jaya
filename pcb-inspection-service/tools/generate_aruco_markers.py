"""Generate a printable ArUco marker sheet for the ESP32 inspection jig."""

from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "aruco_markers" / "esp32_jig_markers.png"
CANVAS_WIDTH = 1500
CANVAS_HEIGHT = 1000
MARKER_SIZE = 180

# Marker centers use TL/TR/BR/BL order from backend.esp32_alignment.
POSITIONS = {
    0: (150, 150),
    1: (1350, 150),
    2: (1350, 796),
    3: (150, 796),
}


def make_marker(dictionary, marker_id):
    if hasattr(cv2.aruco, "generateImageMarker"):
        return cv2.aruco.generateImageMarker(dictionary, marker_id, MARKER_SIZE)
    return cv2.aruco.drawMarker(dictionary, marker_id, MARKER_SIZE)


def main():
    if not hasattr(cv2, "aruco"):
        raise RuntimeError(
            "cv2.aruco tidak tersedia. Install opencv-contrib-python."
        )

    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    canvas = np.full(
        (CANVAS_HEIGHT, CANVAS_WIDTH, 3),
        255,
        dtype=np.uint8,
    )

    for marker_id, (cx, cy) in POSITIONS.items():
        marker = make_marker(dictionary, marker_id)
        x1 = cx - MARKER_SIZE // 2
        y1 = cy - MARKER_SIZE // 2
        canvas[y1 : y1 + MARKER_SIZE, x1 : x1 + MARKER_SIZE] = cv2.cvtColor(
            marker,
            cv2.COLOR_GRAY2BGR,
        )
        cv2.putText(
            canvas,
            f"ID {marker_id}",
            (x1, y1 + MARKER_SIZE + 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 0, 0),
            2,
            cv2.LINE_AA,
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(OUTPUT), canvas):
        raise RuntimeError(f"Gagal menyimpan marker: {OUTPUT}")
    print(f"Marker sheet tersimpan di: {OUTPUT}")


if __name__ == "__main__":
    main()
