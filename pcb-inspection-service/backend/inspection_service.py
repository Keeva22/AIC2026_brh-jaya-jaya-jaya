"""YOLO-based component inspection for the supported PCB profiles."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import cv2

from backend.database_inspection import (
    _bbox as database_bbox,
    _crop as database_crop,
    _slot_score as database_slot_score,
)

from backend.arduino_uno_alignment import (
    align_arduino_uno,
    get_last_alignment_method as get_uno_alignment_method,
)
from backend.esp32_alignment import (
    align_esp32,
    get_last_alignment_method as get_esp32_alignment_method,
)


ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "models" / "best.pt"
SAVE_DIR = ROOT / "runs" / "web_inspection"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

CONF_THRESHOLD = 0.20
INFERENCE_IMAGE_SIZE = 1280

LOCAL_RECOVERY_CONF_THRESHOLD = 0.15
LOCAL_RECOVERY_IMAGE_SIZE = 1280
LARGE_IC_RECOVERY_CONF_THRESHOLD = 0.05
LARGE_IC_RECOVERY_IMAGE_SIZE = 1536
LOCAL_RECOVERY_PADDING = 0.25

MATCH_DISTANCE = 50.0
MAX_ADAPTIVE_DISTANCE = 90.0

UNO_FLEXIBLE_MIN_DISTANCE = 85.0
UNO_FLEXIBLE_MAX_DISTANCE = 135.0

UNO_CLASS_MIN_DISTANCE = {
    "connector": 210.0,
    "resistor": 125.0,
    "capacitor": 135.0,
    "diode": 135.0,
    "led": 115.0,
    "ic": 125.0,
}

UNO_OCCUPANCY_DISTANCE = 70.0

UNO_REFERENCE_EVIDENCE_CLASSES = {
    "connector",
    "diode",
}

UNO_REFERENCE_EVIDENCE_THRESHOLD = 0.56

UNO_REFERENCE_EVIDENCE_CLASS_THRESHOLDS = {
    "connector": 0.38,
    "diode": 0.56,
}

# Threshold default
CAMERA_APPEARANCE_THRESHOLD = 0.65
CAMERA_APPEARANCE_SMALL_THRESHOLD = 0.75

# Threshold khusus Arduino UNO
UNO_CAMERA_APPEARANCE_THRESHOLD = 0.65
UNO_CAMERA_APPEARANCE_SMALL_THRESHOLD = 0.75
UNO_IC_APPEARANCE_THRESHOLD = 0.45

# Occupancy matching dipakai oleh mode flexible matching Arduino UNO
ALLOW_CROSS_CLASS_OCCUPANCY = (
    os.getenv("PCB_ALLOW_CROSS_CLASS_OCCUPANCY", "1") != "0"
)


@dataclass(frozen=True)
class BoardProfile:
    board_id: str
    board_name: str
    reference_json: Path
    aligner: Callable[..., Any]
    alignment_method: Callable[[], str]
    result_filename: str
    reference_image: Path | None = None
    match_mode: str = "strict"
    confidence_threshold: float = CONF_THRESHOLD

    @property
    def data(self) -> dict[str, Any]:
        with self.reference_json.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @property
    def components(self) -> list[dict[str, Any]]:
        return self.data["components"]

    @property
    def width(self) -> int:
        return int(self.data["image_width"])

    @property
    def height(self) -> int:
        return int(self.data["image_height"])


ESP32_PROFILE = BoardProfile(
    board_id="esp32",
    board_name="ESP32-WROOM",
    reference_json=ROOT / "reference_database" / "ESP32_WROOM_camera.json",
    aligner=align_esp32,
    alignment_method=get_esp32_alignment_method,
    result_filename="esp32_latest.jpg",
    reference_image=ROOT / "reference_database" / "ESP32_WROOM_reference.jpg",
    confidence_threshold=0.12,
)


ARDUINO_UNO_PROFILE = BoardProfile(
    board_id="arduino_uno",
    board_name="Arduino UNO",
    reference_json=ROOT / "reference_database" / "ArduinoUno.json",
    aligner=align_arduino_uno,
    alignment_method=get_uno_alignment_method,
    result_filename="arduino_uno_latest.jpg",
    reference_image=ROOT / "reference_database" / "ArduinoUno_reference.jpg",
    match_mode="class_count_flexible",
    confidence_threshold=0.12,
)


PROFILES = {
    ESP32_PROFILE.board_id: ESP32_PROFILE,
    ARDUINO_UNO_PROFILE.board_id: ARDUINO_UNO_PROFILE,
}


model = None


def get_model():
    """Load YOLO only when a camera inspection is requested."""

    global model

    if model is not None:
        return model

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"YOLO model tidak ditemukan: {MODEL_PATH}"
        )

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "Dependensi kamera belum terpasang. Jalankan: "
            "python -m pip install -r requirements.txt"
        ) from exc

    print("Loading YOLO model...")
    model = YOLO(str(MODEL_PATH))
    print("YOLO model loaded.")

    return model


def get_board_profile(board_id: str) -> BoardProfile:
    try:
        return PROFILES[board_id.lower()]
    except KeyError as exc:
        supported = ", ".join(sorted(PROFILES))
        raise ValueError(
            f"Board '{board_id}' tidak didukung. Pilihan: {supported}"
        ) from exc


def distance(point1, point2) -> float:
    return math.hypot(
        point1[0] - point2[0],
        point1[1] - point2[1],
    )


def match_tolerance(reference: dict[str, Any]) -> float:
    bbox = reference.get("bbox")

    if not bbox or len(bbox) != 4:
        return MATCH_DISTANCE

    diagonal = math.hypot(
        float(bbox[2]) - float(bbox[0]),
        float(bbox[3]) - float(bbox[1]),
    )

    return min(
        MAX_ADAPTIVE_DISTANCE,
        max(MATCH_DISTANCE, 0.25 * diagonal),
    )


def normalize_lighting(image):
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)

    lightness, channel_a, channel_b = cv2.split(lab)

    lightness = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8),
    ).apply(lightness)

    return cv2.cvtColor(
        cv2.merge((lightness, channel_a, channel_b)),
        cv2.COLOR_LAB2BGR,
    )


def _crop_reference_region(image, bbox, padding=0.35):
    """Crop a bounded component region with board context."""

    height, width = image.shape[:2]

    if not bbox or len(bbox) != 4:
        return None

    x1, y1, x2, y2 = [
        float(value)
        for value in bbox
    ]

    pad_x = max(8.0, (x2 - x1) * padding)
    pad_y = max(8.0, (y2 - y1) * padding)

    left = max(0, int(round(x1 - pad_x)))
    top = max(0, int(round(y1 - pad_y)))
    right = min(width, int(round(x2 + pad_x)))
    bottom = min(height, int(round(y2 + pad_y)))

    if right <= left or bottom <= top:
        return None

    return image[top:bottom, left:right]


def _normalized_patch_features(patch):
    """Return lighting-tolerant grayscale and edge features."""

    if patch is None or patch.size == 0:
        return None, None

    enhanced = normalize_lighting(patch)

    gray = cv2.cvtColor(
        enhanced,
        cv2.COLOR_BGR2GRAY,
    )

    gray = cv2.resize(
        gray,
        (96, 96),
        interpolation=cv2.INTER_AREA,
    ).astype("float32")

    gray = (
        gray - float(gray.mean())
    ) / max(float(gray.std()), 1.0)

    edge_source = cv2.normalize(
        gray,
        None,
        0,
        255,
        cv2.NORM_MINMAX,
    ).astype("uint8")

    edges = cv2.Canny(
        edge_source,
        45,
        130,
    ).astype("float32")

    edges = (
        edges - float(edges.mean())
    ) / max(float(edges.std()), 1.0)

    return gray, edges


def _correlation(first, second):
    if (
        first is None
        or second is None
        or first.shape != second.shape
    ):
        return -1.0

    value = float((first * second).mean())

    return max(
        -1.0,
        min(1.0, value),
    )


def _localized_template_score(current, reference, bbox):
    """Find the reference patch inside a larger local search region."""

    template = _crop_reference_region(
        reference,
        bbox,
        padding=0.25,
    )

    search = _crop_reference_region(
        current,
        bbox,
        padding=1.00,
    )

    if template is None or search is None:
        return -1.0

    template = cv2.cvtColor(
        normalize_lighting(template),
        cv2.COLOR_BGR2GRAY,
    )

    search = cv2.cvtColor(
        normalize_lighting(search),
        cv2.COLOR_BGR2GRAY,
    )

    if (
        search.shape[0] < template.shape[0]
        or search.shape[1] < template.shape[1]
    ):
        return -1.0

    result = cv2.matchTemplate(
        search,
        template,
        cv2.TM_CCOEFF_NORMED,
    )

    return float(cv2.minMaxLoc(result)[1])


def recover_reference_evidence(
    aligned,
    missing,
    profile,
):
    """Recover distinctive UNO slots when YOLO misses their class."""

    if profile.board_id != "arduino_uno":
        return [], missing

    image_file = profile.data.get("image_file")

    if not image_file:
        return [], missing

    reference_path = (
        profile.reference_json.parent / image_file
    )

    reference = cv2.imread(str(reference_path))

    if reference is None:
        return [], missing

    if reference.shape[:2] != aligned.shape[:2]:
        reference = cv2.resize(
            reference,
            (aligned.shape[1], aligned.shape[0]),
        )

    recovered = []
    remaining = []

    for item in missing:
        if item["class"] not in UNO_REFERENCE_EVIDENCE_CLASSES:
            remaining.append(item)
            continue

        current_patch = _crop_reference_region(
            aligned,
            item.get("bbox"),
            padding=0.40,
        )

        reference_patch = _crop_reference_region(
            reference,
            item.get("bbox"),
            padding=0.40,
        )

        current_gray, current_edges = (
            _normalized_patch_features(current_patch)
        )

        reference_gray, reference_edges = (
            _normalized_patch_features(reference_patch)
        )

        score = (
            0.65 * _correlation(
                current_gray,
                reference_gray,
            )
            + 0.35 * _correlation(
                current_edges,
                reference_edges,
            )
        )

        if item["class"] == "connector":
            score = max(
                score,
                _localized_template_score(
                    aligned,
                    reference,
                    item.get("bbox"),
                ),
            )

        evidence_threshold = (
            UNO_REFERENCE_EVIDENCE_CLASS_THRESHOLDS.get(
                item["class"],
                UNO_REFERENCE_EVIDENCE_THRESHOLD,
            )
        )

        if score >= evidence_threshold:
            recovered.append(
                {
                    "reference_index": item["reference_index"],
                    "reference": profile.components[
                        item["reference_index"]
                    ],
                    "detection": {
                        "class": item["class"],
                        "confidence": score,
                        "center": item["center"],
                        "bbox": item.get("bbox"),
                        "source": "reference_patch_evidence",
                    },
                    "distance": 0.0,
                    "class_match": False,
                    "reference_evidence": True,
                }
            )
        else:
            remaining.append(item)

    return recovered, remaining


def camera_appearance_evidence(
    aligned,
    profile: BoardProfile,
    matched=None,
):
    """Compare expected slots with the healthy camera reference."""

    reference_path = profile.reference_image

    if (
        reference_path is None
        or not reference_path.exists()
    ):
        return [], []

    reference = cv2.imread(str(reference_path))

    if reference is None:
        return [], []

    if reference.shape[:2] != aligned.shape[:2]:
        reference = cv2.resize(
            reference,
            (aligned.shape[1], aligned.shape[0]),
        )

    missing = []
    scores = []

    matched_by_reference = {
        item["reference_index"]: item
        for item in (matched or [])
    }

    for reference_index, component in enumerate(
        profile.components
    ):
        box = database_bbox(
            component,
            profile.width,
            profile.height,
        )

        reference_patch, outer = database_crop(
            reference,
            box,
            padding=0.45,
        )

        current_patch, _ = database_crop(
            aligned,
            box,
            padding=0.45,
        )

        score = database_slot_score(
            reference_patch,
            current_patch,
            box,
            outer,
        )

        x1, y1, x2, y2 = box

        area = max(
            1.0,
            float((x2 - x1) * (y2 - y1)),
        )

        class_name = str(
            component.get("class", "component")
        )

        matched_item = matched_by_reference.get(
            reference_index
        )

        ic_template_similarity = None

        # Use a local template first so normal camera crop/lighting changes
        # do not make a healthy large IC look missing.
        if profile.board_id == "arduino_uno" and class_name == "ic":
            ic_template_similarity = _localized_template_score(
                aligned,
                reference,
                box,
            )

            if ic_template_similarity >= 0.55:
                score = min(score, 0.20)
            else:
                reference_gray, reference_edges = _normalized_patch_features(
                    reference_patch
                )
                current_gray, current_edges = _normalized_patch_features(
                    current_patch
                )
                structural_difference = (
                    0.60 * (
                        1.0 - _correlation(
                            reference_gray,
                            current_gray,
                        )
                    )
                    + 0.40 * (
                        1.0 - _correlation(
                            reference_edges,
                            current_edges,
                        )
                    )
                )
                score = max(score, structural_difference)

        if (
            matched_item is not None
            and matched_item.get("class_match") is False
        ):
            threshold = 0.45

        elif class_name == "connector":
            threshold = 0.56

        elif profile.board_id == "arduino_uno" and class_name == "ic":
            threshold = UNO_IC_APPEARANCE_THRESHOLD

        elif area < 2500:
            threshold = (
                UNO_CAMERA_APPEARANCE_SMALL_THRESHOLD
                if profile.board_id == "arduino_uno"
                else CAMERA_APPEARANCE_SMALL_THRESHOLD
            )

        else:
            threshold = (
                UNO_CAMERA_APPEARANCE_THRESHOLD
                if profile.board_id == "arduino_uno"
                else CAMERA_APPEARANCE_THRESHOLD
            )

        rounded_score = round(
            float(score),
            4,
        )

        scores.append(
            {
                "reference_index": reference_index,
                "class": class_name,
                "score": rounded_score,
                "threshold": threshold,
                "template_similarity": (
                    round(float(ic_template_similarity), 4)
                    if ic_template_similarity is not None
                    else None
                ),
            }
        )

        if score >= threshold:
            missing.append(
                {
                    "reference_index": reference_index,
                    "class": class_name,
                    "center": component["center"],
                    "bbox": component.get("bbox"),
                    "appearance_score": rounded_score,
                }
            )

    return missing, scores


def merge_appearance_missing(
    matched,
    missing,
    appearance_missing,
):
    """Make appearance evidence authoritative."""

    flagged = {
        item["reference_index"]: item
        for item in appearance_missing
    }

    if not flagged:
        return matched, missing

    matched = [
        item
        for item in matched
        if item["reference_index"] not in flagged
    ]

    merged_missing = []
    seen = set()

    for item in missing:
        reference_index = item["reference_index"]

        if reference_index in flagged:
            item = flagged[reference_index]

        merged_missing.append(item)
        seen.add(reference_index)

    for reference_index, item in flagged.items():
        if reference_index not in seen:
            merged_missing.append(item)

    return (
        matched,
        sorted(
            merged_missing,
            key=lambda item: item["reference_index"],
        ),
    )


def recover_missing_by_appearance(
    missing,
    appearance_scores,
    profile: BoardProfile,
):
    """Recover visible UNO slots when YOLO misses their class."""

    # Keep the ESP32 pipeline unchanged.
    if profile.board_id != "arduino_uno":
        return [], missing

    scores_by_reference = {
        item["reference_index"]: item
        for item in appearance_scores
    }

    recovered = []
    remaining = []

    for item in missing:
        reference_index = item["reference_index"]
        evidence = scores_by_reference.get(reference_index)

        # A large appearance difference means the component is genuinely
        # missing or covered, so it must remain FAIL.
        if (
            evidence is None
            or evidence["score"] >= evidence["threshold"]
        ):
            remaining.append(item)
            continue

        component = profile.components[reference_index]
        recovered.append(
            {
                "reference_index": reference_index,
                "reference": component,
                "detection": {
                    "class": component["class"],
                    "confidence": max(
                        0.0,
                        1.0 - float(evidence["score"]),
                    ),
                    "center": component["center"],
                    "bbox": component.get("bbox"),
                    "source": "reference_presence_evidence",
                },
                "distance": 0.0,
                "class_match": False,
                "reference_evidence": True,
                "appearance_score": evidence["score"],
            }
        )

    return recovered, remaining


def collect_detections(
    result,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
):
    if (
        result.boxes is None
        or len(result.boxes) == 0
    ):
        return []

    detections = []

    for box in result.boxes:
        cls = int(box.cls[0])
        confidence = float(box.conf[0])
        coords = box.xyxy[0].tolist()

        x1 = float(coords[0]) + offset_x
        y1 = float(coords[1]) + offset_y
        x2 = float(coords[2]) + offset_x
        y2 = float(coords[3]) + offset_y

        detections.append(
            {
                "class": get_model().names[cls],
                "confidence": confidence,
                "center": [
                    (x1 + x2) / 2.0,
                    (y1 + y2) / 2.0,
                ],
                "bbox": [x1, y1, x2, y2],
            }
        )

    return detections


def deduplicate_detections(
    detections,
    max_distance: float = 15.0,
):
    result = []

    for detection in sorted(
        detections,
        key=lambda item: item["confidence"],
        reverse=True,
    ):
        if not any(
            detection["class"] == existing["class"]
            and distance(
                detection["center"],
                existing["center"],
            ) <= max_distance
            for existing in result
        ):
            result.append(detection)

    return result


def match_reference_strict(
    detections,
    components,
):
    possible_matches = []

    for reference_index, reference in enumerate(
        components
    ):
        for detection_index, detection in enumerate(
            detections
        ):
            if detection["class"] != reference["class"]:
                continue

            current_distance = distance(
                reference["center"],
                detection["center"],
            )

            if current_distance <= match_tolerance(
                reference
            ):
                possible_matches.append(
                    {
                        "reference_index": reference_index,
                        "detection_index": detection_index,
                        "distance": current_distance,
                    }
                )

    matched = []
    used_references = set()
    used_detections = set()

    for candidate in sorted(
        possible_matches,
        key=lambda item: item["distance"],
    ):
        reference_index = candidate["reference_index"]
        detection_index = candidate["detection_index"]

        if (
            reference_index in used_references
            or detection_index in used_detections
        ):
            continue

        matched.append(
            {
                "reference_index": reference_index,
                "reference": components[
                    reference_index
                ],
                "detection": detections[
                    detection_index
                ],
                "distance": candidate["distance"],
            }
        )

        used_references.add(reference_index)
        used_detections.add(detection_index)

    missing = [
        {
            "reference_index": reference_index,
            "class": reference["class"],
            "center": reference["center"],
            "bbox": reference.get("bbox"),
        }
        for reference_index, reference in enumerate(
            components
        )
        if reference_index not in used_references
    ]

    return matched, missing


def match_reference_flexible(
    detections,
    components,
):
    """Match UNO components with tolerant local evidence."""

    matched = []
    missing = []
    used_references = set()
    used_detections = set()

    same_class_candidates = [
        {
            "reference_index": reference_index,
            "detection_index": detection_index,
            "distance": distance(
                reference["center"],
                detection["center"],
            ),
        }
        for reference_index, reference in enumerate(
            components
        )
        for detection_index, detection in enumerate(
            detections
        )
        if (
            reference["class"] == detection["class"]
            and distance(
                reference["center"],
                detection["center"],
            )
            <= flexible_match_tolerance(reference)
        )
    ]

    for candidate in sorted(
        same_class_candidates,
        key=lambda item: item["distance"],
    ):
        reference_index = candidate["reference_index"]
        detection_index = candidate["detection_index"]

        if (
            reference_index in used_references
            or detection_index in used_detections
        ):
            continue

        matched.append(
            {
                "reference_index": reference_index,
                "reference": components[
                    reference_index
                ],
                "detection": detections[
                    detection_index
                ],
                "distance": candidate["distance"],
                "class_match": True,
            }
        )

        used_references.add(reference_index)
        used_detections.add(detection_index)

    # Cross-class occupancy untuk mengatasi salah klasifikasi YOLO.
    if ALLOW_CROSS_CLASS_OCCUPANCY:
        occupancy_candidates = [
            {
                "reference_index": reference_index,
                "detection_index": detection_index,
                "distance": distance(
                    reference["center"],
                    detection["center"],
                ),
            }
            for reference_index, reference in enumerate(
                components
            )
            for detection_index, detection in enumerate(
                detections
            )
            if (
                reference_index not in used_references
                and detection_index not in used_detections
                and distance(
                    reference["center"],
                    detection["center"],
                )
                <= UNO_OCCUPANCY_DISTANCE
            )
        ]

        for candidate in sorted(
            occupancy_candidates,
            key=lambda item: item["distance"],
        ):
            reference_index = candidate["reference_index"]
            detection_index = candidate["detection_index"]

            if (
                reference_index in used_references
                or detection_index in used_detections
            ):
                continue

            matched.append(
                {
                    "reference_index": reference_index,
                    "reference": components[
                        reference_index
                    ],
                    "detection": detections[
                        detection_index
                    ],
                    "distance": candidate["distance"],
                    "class_match": False,
                }
            )

            used_references.add(reference_index)
            used_detections.add(detection_index)

    for reference_index, reference in enumerate(
        components
    ):
        if reference_index not in used_references:
            missing.append(
                {
                    "reference_index": reference_index,
                    "class": reference["class"],
                    "center": reference["center"],
                    "bbox": reference.get("bbox"),
                }
            )

    return matched, missing


def flexible_match_tolerance(
    reference: dict[str, Any],
) -> float:
    """Return a bounded local search radius for UNO."""

    bbox = reference.get("bbox")

    if not bbox or len(bbox) != 4:
        geometry_tolerance = UNO_FLEXIBLE_MAX_DISTANCE
    else:
        diagonal = math.hypot(
            float(bbox[2]) - float(bbox[0]),
            float(bbox[3]) - float(bbox[1]),
        )

        geometry_tolerance = min(
            UNO_FLEXIBLE_MAX_DISTANCE,
            max(
                UNO_FLEXIBLE_MIN_DISTANCE,
                0.70 * diagonal,
            ),
        )

    class_tolerance = UNO_CLASS_MIN_DISTANCE.get(
        reference.get("class"),
        0.0,
    )

    return max(
        geometry_tolerance,
        class_tolerance,
    )


def match_reference(
    detections,
    components,
    mode="strict",
):
    if mode == "class_count_flexible":
        return match_reference_flexible(
            detections,
            components,
        )

    return match_reference_strict(
        detections,
        components,
    )


def recover_missing_detections(
    roi,
    missing,
    components,
    mode="strict",
):
    active_model = get_model()
    recovered = []

    height, width = roi.shape[:2]

    for item in missing:
        reference = components[
            item["reference_index"]
        ]

        bbox = reference.get("bbox")

        if bbox and len(bbox) == 4:
            rx1, ry1, rx2, ry2 = [
                float(value)
                for value in bbox
            ]
        else:
            cx, cy = reference["center"]
            rx1 = cx - 50
            ry1 = cy - 50
            rx2 = cx + 50
            ry2 = cy + 50

        box_width = max(rx2 - rx1, 20.0)
        box_height = max(ry2 - ry1, 20.0)

        pad_x = max(
            20.0,
            box_width * LOCAL_RECOVERY_PADDING,
        )

        pad_y = max(
            20.0,
            box_height * LOCAL_RECOVERY_PADDING,
        )

        crop_x1 = max(
            0,
            int(rx1 - pad_x),
        )

        crop_y1 = max(
            0,
            int(ry1 - pad_y),
        )

        crop_x2 = min(
            width,
            int(rx2 + pad_x),
        )

        crop_y2 = min(
            height,
            int(ry2 + pad_y),
        )

        if (
            crop_x2 <= crop_x1
            or crop_y2 <= crop_y1
        ):
            continue

        crop = roi[
            crop_y1:crop_y2,
            crop_x1:crop_x2,
        ]

        passes = [
            (
                crop,
                LOCAL_RECOVERY_IMAGE_SIZE,
                LOCAL_RECOVERY_CONF_THRESHOLD,
                False,
            ),
            (
                normalize_lighting(crop),
                LOCAL_RECOVERY_IMAGE_SIZE,
                LOCAL_RECOVERY_CONF_THRESHOLD,
                False,
            ),
        ]

        if (
            reference["class"] == "ic"
            and box_width * box_height >= 50000
        ):
            passes.extend(
                [
                    (
                        crop,
                        LARGE_IC_RECOVERY_IMAGE_SIZE,
                        LARGE_IC_RECOVERY_CONF_THRESHOLD,
                        True,
                    ),
                    (
                        normalize_lighting(crop),
                        LARGE_IC_RECOVERY_IMAGE_SIZE,
                        LARGE_IC_RECOVERY_CONF_THRESHOLD,
                        True,
                    ),
                ]
            )

        candidates = []

        for (
            source,
            image_size,
            confidence,
            augment,
        ) in passes:
            results = active_model.predict(
                source=source,
                imgsz=image_size,
                conf=confidence,
                max_det=20,
                augment=augment,
                verbose=False,
            )

            candidates.extend(
                collect_detections(
                    results[0],
                    crop_x1,
                    crop_y1,
                )
            )

        candidates = [
            candidate
            for candidate in deduplicate_detections(
                candidates
            )
            if candidate["class"]
            == reference["class"]
        ]

        if candidates:
            candidate = min(
                candidates,
                key=lambda item: distance(
                    reference["center"],
                    item["center"],
                ),
            )

            allowed_distance = (
                flexible_match_tolerance(reference)
                if mode == "class_count_flexible"
                else match_tolerance(reference)
            )

            if (
                distance(
                    reference["center"],
                    candidate["center"],
                )
                <= allowed_distance
            ):
                recovered.append(candidate)

    return recovered


def draw_result(
    roi,
    matched,
    missing,
    detections,
    profile: BoardProfile,
):
    annotated = roi.copy()

    for item in matched:
        cx, cy = [
            int(value)
            for value in item["detection"]["center"]
        ]

        cv2.circle(
            annotated,
            (cx, cy),
            8,
            (0, 255, 0),
            -1,
        )

        cv2.putText(
            annotated,
            "OK",
            (cx + 10, cy),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
        )

    for item in missing:
        cx, cy = [
            int(value)
            for value in item["center"]
        ]

        cv2.circle(
            annotated,
            (cx, cy),
            16,
            (0, 0, 255),
            3,
        )

        cv2.line(
            annotated,
            (cx - 16, cy - 16),
            (cx + 16, cy + 16),
            (0, 0, 255),
            3,
        )

        cv2.line(
            annotated,
            (cx + 16, cy - 16),
            (cx - 16, cy + 16),
            (0, 0, 255),
            3,
        )

        cv2.putText(
            annotated,
            f"MISSING: {item['class']}",
            (cx + 20, cy),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 255),
            2,
        )

    matched_reference_indices = {
        item["reference_index"]
        for item in matched
    }

    complete_reference = (
        len(matched_reference_indices)
        == len(profile.components)
    )

    status = (
        "PASS"
        if complete_reference and not missing
        else "FAIL"
    )

    status_color = (
        (0, 255, 0)
        if status == "PASS"
        else (0, 0, 255)
    )

    cv2.rectangle(
        annotated,
        (10, 10),
        (590, 125),
        (255, 255, 255),
        -1,
    )

    cv2.putText(
        annotated,
        status,
        (30, 55),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.5,
        status_color,
        4,
    )

    cv2.putText(
        annotated,
        profile.board_name,
        (30, 90),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 0, 0),
        2,
    )

    cv2.putText(
        annotated,
        (
            f"Reference: {len(profile.components)} "
            f"| Detected: {len(detections)} "
            f"| Missing: {len(missing)}"
        ),
        (30, 115),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (50, 50, 50),
        2,
    )

    return annotated, status


def inspect_board(
    frame,
    profile: BoardProfile,
) -> dict[str, Any]:
    if frame is None:
        raise ValueError("Frame kamera kosong.")

    if not profile.reference_json.exists():
        raise FileNotFoundError(
            f"Reference {profile.board_name} tidak ditemukan: "
            f"{profile.reference_json}"
        )

    aligned = profile.aligner(
        frame,
        save_debug=True,
    )

    if aligned is None:
        raise RuntimeError(
            f"{profile.board_name} alignment gagal. "
            "PCB tidak dapat ditemukan."
        )

    height, width = aligned.shape[:2]

    if (
        width != profile.width
        or height != profile.height
    ):
        raise RuntimeError(
            f"Ukuran aligned image {width}x{height} "
            f"tidak sesuai reference "
            f"{profile.width}x{profile.height}."
        )

    active_model = get_model()

    results = active_model.predict(
        source=aligned,
        imgsz=INFERENCE_IMAGE_SIZE,
        conf=profile.confidence_threshold,
        verbose=False,
    )

    enhanced_results = active_model.predict(
        source=normalize_lighting(aligned),
        imgsz=INFERENCE_IMAGE_SIZE,
        conf=profile.confidence_threshold,
        verbose=False,
    )

    detections = deduplicate_detections(
        collect_detections(results[0])
        + collect_detections(enhanced_results[0])
    )

    matched, missing = match_reference(
        detections,
        profile.components,
        profile.match_mode,
    )

    recovered = recover_missing_detections(
        aligned,
        missing,
        profile.components,
        profile.match_mode,
    )

    if recovered:
        detections.extend(recovered)

        matched, missing = match_reference(
            detections,
            profile.components,
            profile.match_mode,
        )

    evidence_matched, missing = (
        recover_reference_evidence(
            aligned,
            missing,
            profile,
        )
    )

    if evidence_matched:
        matched.extend(evidence_matched)

    appearance_missing, appearance_scores = (
        camera_appearance_evidence(
            aligned,
            profile,
            matched,
        )
    )

    matched, missing = merge_appearance_missing(
        matched,
        missing,
        appearance_missing,
    )

    appearance_recovered, missing = recover_missing_by_appearance(
        missing,
        appearance_scores,
        profile,
    )

    if appearance_recovered:
        matched.extend(appearance_recovered)

    annotated, status = draw_result(
        aligned,
        matched,
        missing,
        detections,
        profile,
    )

    result_path = SAVE_DIR / profile.result_filename

    if not cv2.imwrite(
        str(result_path),
        annotated,
    ):
        raise RuntimeError(
            f"Hasil inspeksi tidak dapat disimpan: "
            f"{result_path}"
        )

    return {
        "board": profile.board_name,
        "alignment_method": profile.alignment_method(),
        "status": status,
        "reference_count": len(profile.components),
        "detected_count": len(detections),
        "recovered_count": len(recovered),
        "reference_evidence_count": len(evidence_matched),
        "appearance_missing_count": len(appearance_missing),
        "appearance_scores": appearance_scores,
        "matched_count": len(matched),
        "missing_count": len(missing),
        "missing": missing,
        "detections": detections,
        "result_image": str(result_path),
    }


def inspect_esp32(frame):
    return inspect_board(
        frame,
        ESP32_PROFILE,
    )


def inspect_arduino_uno(frame):
    return inspect_board(
        frame,
        ARDUINO_UNO_PROFILE,
    )
