import cv2
import numpy as np
import os
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent.parent

REFERENCE_WIDTH = 1253
REFERENCE_HEIGHT = 709
REFERENCE_IMAGE_PATH = (
    ROOT
    / "reference_database"
    / "ESP32_WROOM_reference.jpg"
)

SAVE_DIR = ROOT / "runs" / "web_inspection"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_ARUCO_IDS = (0, 1, 2, 3)

# Canonical PCB corners measured from the 1253x709 ESP32 reference crop.
# The reference database was generated from this crop, not from a smaller
# rectangle with corners at 25,25 and 1058,580.
# Order: top-left, top-right, bottom-right, bottom-left.
DESTINATION_POINTS = np.array(
    [
        [44, 36],
        [1218, 36],
        [1218, 673],
        [44, 673],
    ],
    dtype=np.float32,
)

LAST_ALIGNMENT_METHOD = "unknown"
PCB_ASPECT_RATIO = 1.84


# ============================================================
# ORDER POINTS
# ============================================================

def order_points(points):
    """
    Mengurutkan 4 titik menjadi:

    TL = Top Left
    TR = Top Right
    BR = Bottom Right
    BL = Bottom Left
    """

    points = np.asarray(points, dtype=np.float32)

    if points.shape != (4, 2):
        raise ValueError(
            f"order_points membutuhkan 4 titik, "
            f"tetapi menerima {points.shape}"
        )

    ordered = np.zeros((4, 2), dtype=np.float32)

    s = points.sum(axis=1)
    diff = np.diff(points, axis=1).reshape(-1)

    ordered[0] = points[np.argmin(s)]       # TL
    ordered[2] = points[np.argmax(s)]       # BR
    ordered[1] = points[np.argmin(diff)]    # TR
    ordered[3] = points[np.argmax(diff)]    # BL

    return ordered


def configured_aruco_ids():
    """Read marker IDs from PCB_ARUCO_IDS or use 0,1,2,3."""

    value = os.getenv("PCB_ARUCO_IDS", "0,1,2,3")
    try:
        ids = tuple(int(item.strip()) for item in value.split(","))
    except ValueError:
        return DEFAULT_ARUCO_IDS

    if len(ids) != 4 or len(set(ids)) != 4:
        return DEFAULT_ARUCO_IDS
    return ids


def detect_aruco_marker_centers(frame):
    """Return four marker centers in TL/TR/BR/BL order, if visible."""

    if not hasattr(cv2, "aruco"):
        return None, None

    aruco = cv2.aruco
    dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)

    if hasattr(aruco, "DetectorParameters"):
        try:
            parameters = aruco.DetectorParameters()
        except TypeError:
            parameters = aruco.DetectorParameters_create()
    else:
        parameters = aruco.DetectorParameters_create()

    if hasattr(aruco, "ArucoDetector"):
        detector = aruco.ArucoDetector(dictionary, parameters)
        corners, ids, _ = detector.detectMarkers(frame)
    else:
        corners, ids, _ = aruco.detectMarkers(
            frame,
            dictionary,
            parameters=parameters,
        )

    if ids is None or len(ids) == 0:
        return None, None

    found = {}
    for marker_corners, marker_id in zip(corners, ids.flatten().tolist()):
        found[int(marker_id)] = np.mean(marker_corners.reshape(4, 2), axis=0)

    marker_ids = configured_aruco_ids()
    if any(marker_id not in found for marker_id in marker_ids):
        return None, tuple(sorted(found))

    source = np.array([found[marker_id] for marker_id in marker_ids], dtype=np.float32)
    return source, marker_ids


def get_last_alignment_method():
    return LAST_ALIGNMENT_METHOD


def align_by_reference_features(frame, save_debug=True):
    """Align a moving/rotated PCB to the canonical reference with ORB.

    The reference image supplies geometry only. ORB works on local grayscale
    features and RANSAC estimates a homography, so the current frame does not
    need the same camera position, scale, or brightness as the reference.
    """

    if not REFERENCE_IMAGE_PATH.exists():
        return None

    reference = cv2.imread(str(REFERENCE_IMAGE_PATH))
    if reference is None:
        return None

    reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    reference_gray = clahe.apply(reference_gray)
    frame_gray = clahe.apply(frame_gray)

    reference_mask = np.zeros(reference_gray.shape, dtype=np.uint8)
    cv2.fillConvexPoly(
        reference_mask,
        DESTINATION_POINTS.astype(np.int32),
        255,
    )

    orb = cv2.ORB_create(
        nfeatures=2500,
        scaleFactor=1.2,
        nlevels=8,
        fastThreshold=10,
    )
    reference_keypoints, reference_descriptors = orb.detectAndCompute(
        reference_gray,
        reference_mask,
    )
    frame_keypoints, frame_descriptors = orb.detectAndCompute(
        frame_gray,
        None,
    )

    if (
        reference_descriptors is None
        or frame_descriptors is None
        or len(reference_keypoints) < 12
        or len(frame_keypoints) < 12
    ):
        return None

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    raw_matches = matcher.knnMatch(
        reference_descriptors,
        frame_descriptors,
        k=2,
    )
    good_matches = [
        first
        for first, second in raw_matches
        if first.distance < 0.75 * second.distance
    ]

    if len(good_matches) < 12:
        return None

    reference_points = np.float32(
        [reference_keypoints[m.queryIdx].pt for m in good_matches]
    )
    frame_points = np.float32(
        [frame_keypoints[m.trainIdx].pt for m in good_matches]
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
    inlier_ratio = inliers / max(len(good_matches), 1)
    if inliers < 10 or inlier_ratio < 0.35:
        return None

    try:
        inverse_matrix = np.linalg.inv(matrix)
        current_corners = cv2.perspectiveTransform(
            DESTINATION_POINTS.reshape(1, 4, 2),
            inverse_matrix,
        ).reshape(4, 2)
    except np.linalg.LinAlgError:
        return None

    frame_height, frame_width = frame.shape[:2]
    if not validate_corners(current_corners, frame_width, frame_height):
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
        cv2.polylines(
            debug,
            [current_corners.astype(np.int32)],
            True,
            (0, 255, 0),
            4,
        )
        cv2.putText(
            debug,
            f"Alignment: orb ({inliers}/{len(good_matches)} inliers)",
            (25, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            (255, 255, 0),
            2,
        )
        cv2.imwrite(
            str(SAVE_DIR / "esp32_feature_alignment.jpg"),
            debug,
        )
        cv2.imwrite(
            str(SAVE_DIR / "esp32_aligned_features.jpg"),
            aligned,
        )

    return aligned


def find_board_corners_direct(frame):
    """Detect the dark ESP32 PCB directly and return its four corners.

    This is the production version of the detector from
    ``test_esp32_normalization.py``. It uses Otsu thresholding plus a dark
    value mask, so the threshold adapts better to lighting than a fixed gray
    threshold. Candidate contours are ranked by area, rectangularity, and
    ESP32-like aspect ratio.
    """

    if frame is None:
        raise ValueError("Frame kosong.")

    frame_height, frame_width = frame.shape[:2]
    scale = min(1.0, 1200.0 / max(frame_width, 1))
    if scale < 1.0:
        small = cv2.resize(
            frame,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA,
        )
    else:
        small = frame.copy()

    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    _, otsu_mask = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )

    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    dark_mask = cv2.inRange(
        hsv,
        np.array([0, 0, 0], dtype=np.uint8),
        np.array([180, 255, 195], dtype=np.uint8),
    )
    binary = cv2.bitwise_and(otsu_mask, dark_mask)

    close_size = max(11, min(41, int(round(small.shape[1] * 0.025))))
    if close_size % 2 == 0:
        close_size += 1
    close_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (close_size, close_size),
    )
    binary = cv2.morphologyEx(
        binary,
        cv2.MORPH_CLOSE,
        close_kernel,
        iterations=2,
    )

    open_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (7, 7),
    )
    binary = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        open_kernel,
        iterations=1,
    )

    contours, _ = cv2.findContours(
        binary,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    if not contours:
        return None, binary

    image_area = float(small.shape[0] * small.shape[1])
    candidates = []

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < image_area * 0.08:
            continue

        perimeter = cv2.arcLength(contour, True)
        if perimeter <= 0:
            continue

        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approx) == 4:
            points = approx.reshape(4, 2).astype(np.float32)
        else:
            rectangle = cv2.minAreaRect(contour)
            points = cv2.boxPoints(rectangle).astype(np.float32)

        points = order_points(points)
        width_top = np.linalg.norm(points[1] - points[0])
        width_bottom = np.linalg.norm(points[2] - points[3])
        height_left = np.linalg.norm(points[3] - points[0])
        height_right = np.linalg.norm(points[2] - points[1])
        average_width = (width_top + width_bottom) / 2.0
        average_height = (height_left + height_right) / 2.0

        if min(average_width, average_height) < 100:
            continue

        aspect = max(average_width, average_height) / max(
            min(average_width, average_height),
            1.0,
        )
        if aspect < 1.15 or aspect > 3.2:
            continue

        rectangle_area = average_width * average_height
        rectangularity = min(area / max(rectangle_area, 1.0), 1.0)
        aspect_error = abs(np.log(max(aspect, 1e-6) / PCB_ASPECT_RATIO))
        aspect_score = float(np.exp(-aspect_error))
        score = (
            0.65 * (area / image_area)
            + 0.20 * rectangularity
            + 0.15 * aspect_score
        )

        candidates.append((score, points))

    if not candidates:
        return None, binary

    _, best_points = max(candidates, key=lambda item: item[0])
    if scale < 1.0:
        best_points = best_points / scale

    return best_points.astype(np.float32), binary


# ============================================================
# FOUR CORNERS FROM CONTOUR
# ============================================================

def find_board_corners(frame):
    """
    Mencari kontur PCB terbesar dan mengambil 4 sudutnya.

    Tidak menggunakan YOLO.
    Tidak menggunakan SIFT.
    Tidak menggunakan ROI lama.
    """

    if frame is None:
        raise ValueError("Frame kosong.")

    original = frame.copy()

    gray = cv2.cvtColor(
        original,
        cv2.COLOR_BGR2GRAY
    )

    # --------------------------------------------------------
    # BLUR
    # --------------------------------------------------------

    blurred = cv2.GaussianBlur(
        gray,
        (5, 5),
        0
    )

    # --------------------------------------------------------
    # EDGE
    # --------------------------------------------------------

    edges = cv2.Canny(
        blurred,
        50,
        150
    )

    # --------------------------------------------------------
    # MORPHOLOGY
    # --------------------------------------------------------

    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (7, 7)
    )

    edges = cv2.morphologyEx(
        edges,
        cv2.MORPH_CLOSE,
        kernel,
        iterations=2
    )

    # --------------------------------------------------------
    # FIND CONTOURS
    # --------------------------------------------------------

    contours, _ = cv2.findContours(
        edges,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        return None, None

    image_area = (
        frame.shape[0]
        *
        frame.shape[1]
    )

    candidates = []

    # --------------------------------------------------------
    # SEARCH QUADRILATERAL
    # --------------------------------------------------------

    for contour in contours:

        area = cv2.contourArea(contour)

        if area < image_area * 0.05:
            continue

        perimeter = cv2.arcLength(
            contour,
            True
        )

        approx = cv2.approxPolyDP(
            contour,
            0.02 * perimeter,
            True
        )

        # ----------------------------------------------------
        # PRIORITY: QUADRILATERAL
        # ----------------------------------------------------

        if len(approx) == 4:

            points = (
                approx.reshape(4, 2)
            )

            candidates.append(
                (
                    area,
                    points
                )
            )

    # --------------------------------------------------------
    # IF QUADRILATERAL FOUND
    # --------------------------------------------------------

    if candidates:

        candidates.sort(
            key=lambda x: x[0],
            reverse=True
        )

        area, points = candidates[0]

        ordered = order_points(
            points
        )

        return ordered, edges

    # --------------------------------------------------------
    # FALLBACK: MIN AREA RECTANGLE
    # --------------------------------------------------------

    largest = max(
        contours,
        key=cv2.contourArea
    )

    area = cv2.contourArea(
        largest
    )

    if area < image_area * 0.05:
        return None, edges

    rect = cv2.minAreaRect(
        largest
    )

    box = cv2.boxPoints(
        rect
    )

    box = np.float32(box)

    ordered = order_points(
        box
    )

    return ordered, edges


# ============================================================
# VALIDATE CORNERS
# ============================================================

def validate_corners(
    corners,
    frame_width,
    frame_height
):

    if corners is None:
        return False

    if len(corners) != 4:
        return False

    margin = 5

    for x, y in corners:

        if x < -margin:
            return False

        if y < -margin:
            return False

        if x > frame_width + margin:
            return False

        if y > frame_height + margin:
            return False

    # --------------------------------------------------------
    # CHECK AREA
    # --------------------------------------------------------

    area = cv2.contourArea(
        corners.astype(np.float32)
    )

    frame_area = (
        frame_width
        *
        frame_height
    )

    if area < frame_area * 0.05:
        return False

    return True


# ============================================================
# ALIGN PCB
# ============================================================

def align_esp32(
    frame,
    save_debug=True
):

    global LAST_ALIGNMENT_METHOD
    LAST_ALIGNMENT_METHOD = "failed"

    if frame is None:
        raise ValueError(
            "Frame kamera kosong."
        )

    frame_height, frame_width = (
        frame.shape[:2]
    )

    print()
    print(
        "=============================================="
    )
    print(
        "              ALIGNING ESP32"
    )
    print(
        "=============================================="
    )

    print()
    print(
        f"Camera size: "
        f"{frame_width} x {frame_height}"
    )

    # ========================================================
    # FIND CORNERS
    #
    # Detect the physical PCB first. This makes the normal path independent
    # from the reference photograph: camera translation, scale, and moderate
    # brightness changes are handled from the board contour itself. ORB is a
    # fallback for scenes where the board edge is hidden or blends into the
    # background; ArUco remains the final fallback.
    # ========================================================

    corners, edges = find_board_corners_direct(frame)
    if corners is not None:
        alignment_method = "direct_pcb"
    else:
        feature_aligned = align_by_reference_features(
            frame,
            save_debug=save_debug,
        )
        if feature_aligned is not None:
            LAST_ALIGNMENT_METHOD = "orb_reference"
            return feature_aligned

        corners, marker_ids = detect_aruco_marker_centers(frame)
        alignment_method = "aruco_fallback"

    if corners is None:

        print()
        print(
            "ALIGNMENT GAGAL"
        )

        print(
            "PCB tidak ditemukan."
        )

        return None

    # ========================================================
    # VALIDATE
    # ========================================================

    valid = validate_corners(
        corners,
        frame_width,
        frame_height
    )

    if not valid:

        print()
        print(
            "ALIGNMENT GAGAL"
        )

        print(
            "Sudut PCB tidak valid."
        )

        return None

    # ========================================================
    # PRINT CORNERS
    # ========================================================

    print()
    print(
        "Current corners:"
    )

    print(
        np.round(
            corners,
            1
        )
    )

    # ========================================================
    # DESTINATION
    #
    # INI HARUS SAMA DENGAN:
    #
    # image_width  = 1253
    # image_height = 709
    #
    # pada ESP32_WROOM_camera.json
    # ========================================================

    destination = DESTINATION_POINTS

    # ========================================================
    # HOMOGRAPHY
    # ========================================================

    matrix = cv2.getPerspectiveTransform(
        corners.astype(np.float32),
        destination
    )

    # ========================================================
    # WARP
    # ========================================================

    aligned = cv2.warpPerspective(
        frame,
        matrix,
        (
            REFERENCE_WIDTH,
            REFERENCE_HEIGHT
        ),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT
    )

    # ========================================================
    # VALIDATE OUTPUT
    # ========================================================

    if aligned is None:
        raise RuntimeError(
            "Hasil alignment kosong."
        )

    if aligned.size == 0:
        raise RuntimeError(
            "Hasil alignment tidak memiliki data."
        )

    print()
    print(
        f"Aligned size: "
        f"{aligned.shape[1]} x "
        f"{aligned.shape[0]}"
    )

    # ========================================================
    # DEBUG IMAGE
    # ========================================================

    debug = frame.copy()

    pts = corners.astype(
        np.int32
    )

    # PCB outline
    cv2.polylines(
        debug,
        [pts],
        True,
        (0, 255, 0),
        4
    )

    labels = [
        "TL",
        "TR",
        "BR",
        "BL"
    ]

    for point, label in zip(
        pts,
        labels
    ):

        x, y = (
            int(point[0]),
            int(point[1])
        )

        cv2.circle(
            debug,
            (x, y),
            10,
            (0, 0, 255),
            -1
        )

        cv2.putText(
            debug,
            label,
            (x + 10, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 255),
            2
        )

    cv2.putText(
        debug,
        f"Alignment: {alignment_method}",
        (25, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 0),
        2,
    )

    # ========================================================
    # SAVE DEBUG
    # ========================================================

    if save_debug:

        debug_path = (
            SAVE_DIR
            /
            "esp32_board_detection.jpg"
        )

        aligned_path = (
            SAVE_DIR
            /
            "esp32_aligned_fixed.jpg"
        )

        cv2.imwrite(
            str(debug_path),
            debug
        )

        cv2.imwrite(
            str(aligned_path),
            aligned
        )

        print()
        print(
            "Saved debug:"
        )

        print(
            debug_path
        )

        print(
            "Saved aligned:"
        )

        print(
            aligned_path
        )

    # ========================================================
    # RETURN
    # ========================================================

    LAST_ALIGNMENT_METHOD = alignment_method

    return aligned


# ============================================================
# ALIAS
# ============================================================

align_pcb = align_esp32
