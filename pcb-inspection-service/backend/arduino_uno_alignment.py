"""Alignment helpers for the Arduino UNO reference image.

The UNO photo is a close-up crop, so its canonical frame is the complete
reference image rather than the ESP32-specific 1253x709 crop.  ORB is tried
first because it preserves the component coordinates from the supplied
reference photo.  A board-contour fallback keeps the camera mode usable when
the image has too few local features.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parent.parent
REFERENCE_IMAGE_PATH = ROOT / "reference_database" / "ArduinoUno_reference.jpg"
SAVE_DIR = ROOT / "runs" / "web_inspection"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

REFERENCE_WIDTH = 1212
REFERENCE_HEIGHT = 835
REFERENCE_ASPECT_RATIO = REFERENCE_WIDTH / REFERENCE_HEIGHT
DESTINATION_POINTS = np.array(
    [
        [0, 0],
        [REFERENCE_WIDTH - 1, 0],
        [REFERENCE_WIDTH - 1, REFERENCE_HEIGHT - 1],
        [0, REFERENCE_HEIGHT - 1],
    ],
    dtype=np.float32,
)

LAST_ALIGNMENT_METHOD = "unknown"


def get_last_alignment_method() -> str:
    return LAST_ALIGNMENT_METHOD


def order_points(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float32)
    if points.shape != (4, 2):
        raise ValueError(f"Diperlukan 4 titik sudut, diterima {points.shape}")

    ordered = np.zeros((4, 2), dtype=np.float32)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).reshape(-1)
    ordered[0] = points[np.argmin(sums)]
    ordered[1] = points[np.argmin(differences)]
    ordered[2] = points[np.argmax(sums)]
    ordered[3] = points[np.argmax(differences)]
    return ordered


def _reference_image() -> np.ndarray | None:
    if not REFERENCE_IMAGE_PATH.exists():
        return None
    image = cv2.imread(str(REFERENCE_IMAGE_PATH))
    if image is None:
        return None
    if image.shape[1] != REFERENCE_WIDTH or image.shape[0] != REFERENCE_HEIGHT:
        return cv2.resize(image, (REFERENCE_WIDTH, REFERENCE_HEIGHT))
    return image


def align_by_reference_features(frame: np.ndarray, save_debug: bool = True):
    reference = _reference_image()
    if reference is None:
        return None

    reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    reference_gray = clahe.apply(reference_gray)
    frame_gray = clahe.apply(frame_gray)

    orb = cv2.ORB_create(
        nfeatures=3500,
        scaleFactor=1.2,
        nlevels=8,
        fastThreshold=8,
    )
    reference_keypoints, reference_descriptors = orb.detectAndCompute(
        reference_gray,
        None,
    )
    frame_keypoints, frame_descriptors = orb.detectAndCompute(frame_gray, None)
    if (
        reference_descriptors is None
        or frame_descriptors is None
        or len(reference_keypoints) < 12
        or len(frame_keypoints) < 12
    ):
        return None

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    raw_matches = matcher.knnMatch(reference_descriptors, frame_descriptors, k=2)
    good_matches = [
        first
        for pair in raw_matches
        if len(pair) == 2
        for first, second in [pair]
        if first.distance < 0.76 * second.distance
    ]
    if len(good_matches) < 12:
        return None

    reference_points = np.float32(
        [reference_keypoints[item.queryIdx].pt for item in good_matches]
    )
    frame_points = np.float32(
        [frame_keypoints[item.trainIdx].pt for item in good_matches]
    )
    matrix, inlier_mask = cv2.findHomography(
        frame_points,
        reference_points,
        cv2.RANSAC,
        5.0,
    )
    if matrix is None or inlier_mask is None:
        return None

    inliers = int(inlier_mask.ravel().sum())
    if inliers < 10 or inliers / max(len(good_matches), 1) < 0.30:
        return None

    aligned = cv2.warpPerspective(
        frame,
        matrix,
        (REFERENCE_WIDTH, REFERENCE_HEIGHT),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
    )
    if save_debug:
        debug = frame.copy()
        try:
            inverse = np.linalg.inv(matrix)
            corners = cv2.perspectiveTransform(
                DESTINATION_POINTS.reshape(1, 4, 2), inverse
            ).reshape(4, 2).astype(np.int32)
            cv2.polylines(debug, [corners], True, (0, 255, 0), 3)
        except np.linalg.LinAlgError:
            pass
        cv2.putText(
            debug,
            f"Alignment: orb_reference ({inliers}/{len(good_matches)})",
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            (255, 255, 0),
            2,
            cv2.LINE_AA,
        )
        cv2.imwrite(str(SAVE_DIR / "arduino_uno_feature_alignment.jpg"), debug)
        cv2.imwrite(str(SAVE_DIR / "arduino_uno_aligned_features.jpg"), aligned)
    return aligned


def find_board_corners_direct(frame: np.ndarray):
    """Find the large blue PCB region using adaptive masks."""

    small_scale = min(1.0, 1400.0 / max(frame.shape[1], 1))
    small = (
        cv2.resize(frame, None, fx=small_scale, fy=small_scale, interpolation=cv2.INTER_AREA)
        if small_scale < 1.0
        else frame.copy()
    )
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    # Arduino's blue solder mask is saturated and darker than the background.
    blue = cv2.inRange(
        hsv,
        np.array([85, 35, 20], dtype=np.uint8),
        np.array([135, 255, 235], dtype=np.uint8),
    )
    kernel_size = max(9, min(35, int(round(small.shape[1] * 0.02))))
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (kernel_size, kernel_size),
    )
    blue = cv2.morphologyEx(blue, cv2.MORPH_CLOSE, kernel, iterations=2)
    blue = cv2.morphologyEx(blue, cv2.MORPH_OPEN, kernel, iterations=1)
    contours, _ = cv2.findContours(blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    image_area = float(small.shape[0] * small.shape[1])
    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < image_area * 0.20:
            continue
        perimeter = cv2.arcLength(contour, True)
        if perimeter <= 0:
            continue
        approx = cv2.approxPolyDP(contour, 0.03 * perimeter, True)
        points = (
            approx.reshape(4, 2).astype(np.float32)
            if len(approx) == 4
            else cv2.boxPoints(cv2.minAreaRect(contour)).astype(np.float32)
        )
        points = order_points(points)
        width = (np.linalg.norm(points[1] - points[0]) + np.linalg.norm(points[2] - points[3])) / 2
        height = (np.linalg.norm(points[3] - points[0]) + np.linalg.norm(points[2] - points[1])) / 2
        aspect = max(width, height) / max(min(width, height), 1.0)
        if aspect < 1.15 or aspect > 2.2:
            continue
        aspect_score = np.exp(-abs(np.log(aspect / REFERENCE_ASPECT_RATIO)))
        score = 0.75 * area / image_area + 0.25 * float(aspect_score)
        candidates.append((score, points))

    if not candidates:
        return None
    points = max(candidates, key=lambda item: item[0])[1]
    if small_scale < 1.0:
        points /= small_scale
    return points.astype(np.float32)


def _valid_corners(corners: np.ndarray, frame: np.ndarray) -> bool:
    if corners is None or len(corners) != 4:
        return False
    height, width = frame.shape[:2]
    if any(x < -8 or y < -8 or x > width + 8 or y > height + 8 for x, y in corners):
        return False
    return cv2.contourArea(corners.astype(np.float32)) >= width * height * 0.08


def align_arduino_uno(frame: np.ndarray, save_debug: bool = True):
    global LAST_ALIGNMENT_METHOD
    LAST_ALIGNMENT_METHOD = "failed"
    if frame is None:
        raise ValueError("Frame kamera kosong.")

    # Try feature alignment even when the frame has the canonical dimensions.
    # A camera can keep the same resolution while the board moves inside the
    # frame; returning the raw frame in that case reintroduces coordinate drift.
    aligned = align_by_reference_features(frame, save_debug=save_debug)
    if aligned is not None:
        LAST_ALIGNMENT_METHOD = "orb_reference"
        return aligned

    # The supplied reference image itself is a valid canonical fallback when
    # it contains too few ORB features for a homography.
    if frame.shape[1] == REFERENCE_WIDTH and frame.shape[0] == REFERENCE_HEIGHT:
        LAST_ALIGNMENT_METHOD = "reference_identity"
        return frame.copy()

    corners = find_board_corners_direct(frame)
    if not _valid_corners(corners, frame):
        return None

    matrix = cv2.getPerspectiveTransform(corners, DESTINATION_POINTS)
    aligned = cv2.warpPerspective(
        frame,
        matrix,
        (REFERENCE_WIDTH, REFERENCE_HEIGHT),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
    )
    LAST_ALIGNMENT_METHOD = "direct_pcb"
    if save_debug:
        debug = frame.copy()
        cv2.polylines(debug, [corners.astype(np.int32)], True, (0, 255, 0), 3)
        cv2.putText(
            debug,
            "Alignment: direct_pcb",
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            (255, 255, 0),
            2,
            cv2.LINE_AA,
        )
        cv2.imwrite(str(SAVE_DIR / "arduino_uno_board_detection.jpg"), debug)
        cv2.imwrite(str(SAVE_DIR / "arduino_uno_aligned_fixed.jpg"), aligned)
    return aligned
