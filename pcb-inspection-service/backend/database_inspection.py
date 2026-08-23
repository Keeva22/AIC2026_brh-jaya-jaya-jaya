"""Reference-database inspection for boards that do not use a live camera.

The JSON files in ``reference_database`` describe the expected component
slots on a healthy board.  This module aligns an uploaded image to that
reference and compares each slot with its healthy appearance.  It is
intentionally independent from YOLO, so Arduino Nano, Orange Pi and
Raspberry Pi can be inspected without loading PyTorch.
"""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parent.parent
REFERENCE_DIR = ROOT / "reference_database"
OUTPUT_DIR = ROOT / "runs" / "database_inspection"


@dataclass(frozen=True)
class DatabaseProfile:
    board_id: str
    board_name: str
    reference_json: Path

    @property
    def data(self) -> dict[str, Any]:
        with self.reference_json.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @property
    def components(self) -> list[dict[str, Any]]:
        return list(self.data.get("components", []))

    @property
    def image_path(self) -> Path:
        image_file = self.data.get("image_file")
        if not image_file:
            raise ValueError(f"Reference {self.reference_json.name} tidak memiliki image_file")
        # Some source ZIPs keep JSON metadata in reference_database while the
        # actual normal images are stored in inspection_image.  Support both
        # layouts so the CLI also works after the project is extracted.
        candidates = (
            REFERENCE_DIR / image_file,
            ROOT / "inspection_image" / image_file,
        )
        for path in candidates:
            if path.exists():
                return path
        searched = ", ".join(str(path) for path in candidates)
        raise FileNotFoundError(f"Gambar reference tidak ditemukan. Dicari di: {searched}")


DATABASE_PROFILES = {
    "arduino_nano": DatabaseProfile(
        "arduino_nano", "Arduino Nano", REFERENCE_DIR / "ArduinoNano.json"
    ),
    "orange_pi": DatabaseProfile(
        "orange_pi", "Orange Pi 3B V1.2", REFERENCE_DIR / "Orange_Pi_3B_V1.2.json"
    ),
    "raspberry_pi": DatabaseProfile(
        "raspberry_pi", "Raspberry Pi 4 Model B", REFERENCE_DIR / "Rapsberry_Pi_4_Model_B.json"
    ),
}


def get_database_profile(board_id: str) -> DatabaseProfile:
    aliases = {
        "nano": "arduino_nano",
        "orangepi": "orange_pi",
        "raspberry": "raspberry_pi",
        "raspberrypi": "raspberry_pi",
    }
    normalized = aliases.get(board_id.lower().strip(), board_id.lower().strip())
    try:
        return DATABASE_PROFILES[normalized]
    except KeyError as exc:
        supported = ", ".join(sorted(DATABASE_PROFILES))
        raise ValueError(f"Board database '{board_id}' tidak didukung. Pilihan: {supported}") from exc


def _ordered_corners(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float32)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).reshape(-1)
    return np.array(
        [
            points[np.argmin(sums)],
            points[np.argmin(differences)],
            points[np.argmax(sums)],
            points[np.argmax(differences)],
        ],
        dtype=np.float32,
    )


def align_to_reference(image: np.ndarray, reference: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """Return an image in reference coordinates using ORB when possible."""

    if image is None or reference is None:
        raise ValueError("Gambar input/reference kosong.")

    reference_height, reference_width = reference.shape[:2]
    input_height, input_width = image.shape[:2]
    reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    reference_gray = clahe.apply(reference_gray)
    image_gray = clahe.apply(image_gray)

    orb = cv2.ORB_create(nfeatures=3500, scaleFactor=1.2, nlevels=8, fastThreshold=8)
    reference_keypoints, reference_descriptors = orb.detectAndCompute(reference_gray, None)
    image_keypoints, image_descriptors = orb.detectAndCompute(image_gray, None)
    if reference_descriptors is not None and image_descriptors is not None:
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        pairs = matcher.knnMatch(reference_descriptors, image_descriptors, k=2)
        good = [
            first
            for pair in pairs
            if len(pair) == 2
            for first, second in [pair]
            if first.distance < 0.76 * second.distance
        ]
        if len(good) >= 10:
            reference_points = np.float32(
                [reference_keypoints[item.queryIdx].pt for item in good]
            )
            image_points = np.float32(
                [image_keypoints[item.trainIdx].pt for item in good]
            )
            matrix, inlier_mask = cv2.findHomography(
                image_points, reference_points, cv2.RANSAC, 5.0
            )
            if matrix is not None and inlier_mask is not None:
                inliers = int(inlier_mask.ravel().sum())
                ratio = inliers / max(len(good), 1)
                corners = np.float32(
                    [[0, 0], [input_width - 1, 0], [input_width - 1, input_height - 1], [0, input_height - 1]]
                ).reshape(1, 4, 2)
                projected = cv2.perspectiveTransform(corners, matrix).reshape(4, 2)
                area = abs(float(cv2.contourArea(_ordered_corners(projected))))
                reference_area = float(reference_width * reference_height)
                if inliers >= 8 and ratio >= 0.28 and reference_area * 0.35 <= area <= reference_area * 2.8:
                    aligned = cv2.warpPerspective(
                        image,
                        matrix,
                        (reference_width, reference_height),
                        flags=cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_CONSTANT,
                    )
                    return aligned, {
                        "method": "orb_reference",
                        "inliers": inliers,
                        "matches": len(good),
                        "inlier_ratio": round(ratio, 4),
                    }

    aligned = cv2.resize(image, (reference_width, reference_height), interpolation=cv2.INTER_AREA)
    return aligned, {
        "method": "resize_identity" if (input_width, input_height) == (reference_width, reference_height) else "resize",
        "inliers": 0,
        "matches": 0,
        "inlier_ratio": 0.0,
    }


def _bbox(component: dict[str, Any], width: int, height: int) -> tuple[int, int, int, int]:
    values = component.get("bbox")
    if not values or len(values) != 4:
        center = component.get("center", [width / 2, height / 2])
        size = 30
        values = [center[0] - size, center[1] - size, center[0] + size, center[1] + size]
    x1, y1, x2, y2 = [int(round(float(value))) for value in values]
    x1 = max(0, min(width - 1, x1))
    y1 = max(0, min(height - 1, y1))
    x2 = max(x1 + 1, min(width, x2))
    y2 = max(y1 + 1, min(height, y2))
    return x1, y1, x2, y2


def _crop(image: np.ndarray, box: tuple[int, int, int, int], padding: float) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    x1, y1, x2, y2 = box
    pad_x = max(8, int(round((x2 - x1) * padding)))
    pad_y = max(8, int(round((y2 - y1) * padding)))
    height, width = image.shape[:2]
    outer = (
        max(0, x1 - pad_x),
        max(0, y1 - pad_y),
        min(width, x2 + pad_x),
        min(height, y2 + pad_y),
    )
    ox1, oy1, ox2, oy2 = outer
    return image[oy1:oy2, ox1:ox2], outer


def _normalized_gray(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (96, 96), interpolation=cv2.INTER_AREA).astype(np.float32)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray.astype(np.uint8)).astype(np.float32)
    mean, standard_deviation = float(gray.mean()), float(gray.std())
    return (gray - mean) / max(standard_deviation, 1.0)


def _correlation(first: np.ndarray, second: np.ndarray) -> float:
    first = first.reshape(-1)
    second = second.reshape(-1)
    # ``mean`` already normalizes by the number of pixels. Dividing by the
    # array size a second time makes even identical patches look unrelated.
    value = float(np.mean(first * second))
    return max(-1.0, min(1.0, value))


def _slot_score(reference_patch: np.ndarray, current_patch: np.ndarray, inner_box: tuple[int, int, int, int], outer: tuple[int, int, int, int]) -> float:
    """Estimate how different one expected slot is from the healthy reference.

    The first version compared mostly grayscale structure. That is too easy to
    fool when a missing part is covered with an opaque marker whose brightness
    is similar to the PCB. Include color change and compare the slot against
    its surrounding ring so global lighting changes do not turn the whole
    board into a false defect.
    """

    if reference_patch.size == 0 or current_patch.size == 0:
        return 1.0
    reference_feature = _normalized_gray(reference_patch)
    current_feature = _normalized_gray(current_patch)
    feature_difference = 0.5 * (1.0 - _correlation(reference_feature, current_feature))

    reference_patch = reference_patch.astype(np.float32)
    current_patch = current_patch.astype(np.float32)
    reference_gray = cv2.cvtColor(reference_patch, cv2.COLOR_BGR2GRAY)
    current_gray = cv2.cvtColor(current_patch, cv2.COLOR_BGR2GRAY)
    if reference_gray.shape != current_gray.shape:
        current_gray = cv2.resize(current_gray, (reference_gray.shape[1], reference_gray.shape[0]))
        current_patch = cv2.resize(current_patch, (reference_patch.shape[1], reference_patch.shape[0]))
    pixel_difference = cv2.absdiff(reference_gray, current_gray) / 255.0
    color_difference = np.mean(np.abs(reference_patch - current_patch), axis=2) / 255.0

    ox1, oy1, _, _ = outer
    x1, y1, x2, y2 = inner_box
    ix1, iy1 = max(0, x1 - ox1), max(0, y1 - oy1)
    ix2, iy2 = min(pixel_difference.shape[1], x2 - ox1), min(pixel_difference.shape[0], y2 - oy1)
    inner = pixel_difference[iy1:iy2, ix1:ix2]
    mask = np.ones(pixel_difference.shape, dtype=bool)
    mask[iy1:iy2, ix1:ix2] = False
    ring = pixel_difference[mask]
    inner_color = color_difference[iy1:iy2, ix1:ix2]
    ring_color = color_difference[mask]
    inner_difference = float(inner.mean()) if inner.size else float(pixel_difference.mean())
    ring_difference = float(np.median(ring)) if ring.size else 0.0
    local_contrast = max(0.0, min(1.0, inner_difference - ring_difference + 0.15))
    inner_color_difference = float(inner_color.mean()) if inner_color.size else float(color_difference.mean())
    ring_color_difference = float(np.median(ring_color)) if ring_color.size else 0.0
    color_contrast = max(
        0.0,
        min(
            1.0,
            inner_color_difference
            + 1.15 * max(0.0, inner_color_difference - ring_color_difference),
        ),
    )

    reference_edges = cv2.Canny(np.clip(reference_gray, 0, 255).astype(np.uint8), 45, 130)
    current_edges = cv2.Canny(np.clip(current_gray, 0, 255).astype(np.uint8), 45, 130)
    edge_difference = 0.5 * (1.0 - _correlation(reference_edges.astype(np.float32), current_edges.astype(np.float32)))
    score = (
        0.20 * feature_difference
        + 0.25 * inner_difference
        + 0.25 * color_contrast
        + 0.15 * local_contrast
        + 0.15 * edge_difference
    )
    return float(max(0.0, min(1.0, score)))


def _threshold_for(component: dict[str, Any]) -> float:
    configured = os.getenv("PCB_DB_MISSING_THRESHOLD")
    if configured:
        try:
            return max(0.05, min(0.95, float(configured)))
        except ValueError:
            pass
    x1, y1, x2, y2 = [float(value) for value in component.get("bbox", [0, 0, 30, 30])]
    area = max(1.0, (x2 - x1) * (y2 - y1))
    # Large parts should fail decisively when covered. Small SMD slots retain
    # extra tolerance because a few pixels of alignment/JPEG noise can be
    # meaningful at that scale.
    return 0.16 if area >= 2500 else 0.22


def _label_components(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: defaultdict[str, int] = defaultdict(int)
    labeled = []
    for index, component in enumerate(components):
        class_name = str(component.get("class", "component"))
        counts[class_name] += 1
        item = dict(component)
        item["reference_index"] = index
        item["component_id"] = f"{class_name}_{counts[class_name]}"
        labeled.append(item)
    return labeled


def _draw_result(image: np.ndarray, checks: list[dict[str, Any]], profile: DatabaseProfile) -> np.ndarray:
    output = image.copy()
    missing_count = sum(item["status"] == "MISSING" for item in checks)
    for item in checks:
        x1, y1, x2, y2 = item["bbox"]
        is_missing = item["status"] == "MISSING"
        color = (0, 0, 255) if is_missing else (0, 190, 0)
        cv2.rectangle(output, (x1, y1), (x2, y2), color, 3 if is_missing else 2)
        label = f"MISSING {item['component_id']}" if is_missing else f"OK {item['component_id']}"
        cv2.putText(output, label, (x1, max(20, y1 - 7)), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 2, cv2.LINE_AA)
    status = "PASS" if missing_count == 0 else "FAIL"
    color = (0, 190, 0) if status == "PASS" else (0, 0, 255)
    cv2.rectangle(output, (10, 10), (560, 92), (255, 255, 255), -1)
    cv2.putText(output, status, (25, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 3, cv2.LINE_AA)
    cv2.putText(output, f"{profile.board_name} | missing: {missing_count}", (25, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (40, 40, 40), 2, cv2.LINE_AA)
    return output


def inspect_database_image(image: np.ndarray, board_id: str, output_dir: Path | None = None) -> dict[str, Any]:
    """Inspect a non-camera board image against its JSON reference database."""

    if image is None:
        raise ValueError("Gambar input kosong.")
    profile = get_database_profile(board_id)
    reference = cv2.imread(str(profile.image_path))
    if reference is None:
        raise RuntimeError(f"Gambar reference tidak dapat dibaca: {profile.image_path}")
    aligned, alignment = align_to_reference(image, reference)
    height, width = reference.shape[:2]
    checks = []
    for component in _label_components(profile.components):
        box = _bbox(component, width, height)
        reference_patch, outer = _crop(reference, box, padding=0.45)
        current_patch, _ = _crop(aligned, box, padding=0.45)
        score = _slot_score(reference_patch, current_patch, box, outer)
        threshold = _threshold_for(component)
        checks.append(
            {
                "reference_index": component["reference_index"],
                "component_id": component["component_id"],
                "class": component.get("class", "component"),
                "center": component.get("center"),
                "bbox": list(box),
                "missing_score": round(score, 4),
                "threshold": threshold,
                "status": "MISSING" if score >= threshold else "OK",
            }
        )

    output_dir = output_dir or OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    result_path = output_dir / f"{profile.board_id}_{stamp}_result.jpg"
    aligned_path = output_dir / f"{profile.board_id}_{stamp}_aligned.jpg"
    annotated = _draw_result(aligned, checks, profile)
    if not cv2.imwrite(str(result_path), annotated):
        raise RuntimeError(f"Hasil inspeksi tidak dapat disimpan: {result_path}")
    cv2.imwrite(str(aligned_path), aligned)

    missing = [item for item in checks if item["status"] == "MISSING"]
    return {
        "board_id": profile.board_id,
        "board": profile.board_name,
        "mode": "database",
        "status": "PASS" if not missing else "FAIL",
        "reference_count": len(checks),
        "missing_count": len(missing),
        "missing": missing,
        "components": checks,
        "alignment": alignment,
        "alignment_method": alignment["method"],
        "reference_image": str(profile.image_path),
        "aligned_image": str(aligned_path),
        "result_image": str(result_path),
    }
