"""Driver-facing camera: phone use, seatbelts, drowsiness and yawning."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from .cv_common import (
    Detection,
    EngineReport,
    VideoWriterSafe,
    draw_banner,
    open_video,
    save_evidence,
    try_load_yolo,
)

PHONE_WEIGHTS = ("bestphonenew.pt", "phone_best.pt", "phone.pt")
BELT_WEIGHTS = ("besttt.pt", "seatbelt_best.pt", "belt_best.pt", "seatbelt.pt")

EAR_THRESHOLD = 0.22
MAR_THRESHOLD = 0.58
PHONE_CONF = 0.55
BELT_CONF = 0.45

# Frame counts restated in seconds so the same rule holds at any frame rate.
WEBCAM_FPS_BASELINE = 20.0
EAR_CONSEC_SECONDS = 8 / WEBCAM_FPS_BASELINE
MAR_CONSEC_SECONDS = 12 / WEBCAM_FPS_BASELINE
BELT_TRIGGER_SECONDS = 3.0

PHONE_COOLDOWN_SEC = 8.0
DROWSY_COOLDOWN_SEC = 5.0
YAWN_COOLDOWN_SEC = 6.0
BELT_COOLDOWN_SEC = 20.0

LEFT_EYE = [362, 385, 387, 263, 373, 380]
RIGHT_EYE = [33, 160, 158, 133, 153, 144]
MOUTH = [78, 81, 13, 312, 308, 178, 14, 402]
CHIN_LANDMARK = 152
NOSE_LANDMARK = 1

# Geometric filters that reject detections which are the wrong size, shape or
# position to plausibly be a phone in the driver's hands or a belt across the
# chest. These cut the false positive rate substantially.
PHONE_MIN_W, PHONE_MAX_W = 40, 180
PHONE_MIN_H, PHONE_MAX_H = 60, 220
PHONE_MIN_ASPECT = 0.9
PHONE_TOP_MARGIN = 0.15
PHONE_BOTTOM_MARGIN = 0.85
BELT_MAX_ASPECT = 0.75
BELT_CHIN_FACTOR = 0.70

SCORE_PENALTY = {"phone_use": 10, "no_seatbelt": 15, "drowsiness": 20, "yawning": 5}

SEVERITY = {
    "drowsiness": "high",
    "no_seatbelt": "high",
    "phone_use": "high",
    "yawning": "medium",
}

NOTES = {
    "phone_use": "Phone detected in the driver's hands",
    "no_seatbelt": "No seatbelt detected",
    "drowsiness": "Eyes closed past the EAR threshold (micro-sleep indicator)",
    "yawning": "Yawn detected via mouth aspect ratio",
}

# A continuous violation is logged once, with its duration, rather than
# re-firing every cooldown. Set to False to log repeatedly instead.
PHONE_LATCH = True
DROWSY_LATCH = True

# How long a detection must be absent before the violation counts as over.
# Object detectors flicker: a phone held steadily is found on most frames and
# missed on some. Without this gap, every missed frame ends one violation and
# starts another, and a single phone call becomes forty rows.
END_GAP_SECONDS = 2.0

NEGATIVE_BELT_LABELS = {
    "no_seatbelt", "no-seatbelt", "noseatbelt", "unbuckled", "not_wearing",
    "without_seatbelt", "no_belt", "nobelt", "no seatbelt",
}


def _resolve(models_dir: Path, names) -> Path | None:
    for n in names:
        p = models_dir / n
        if p.exists():
            return p
    return None


def _load(yolo, weights: str):
    try:
        return yolo(weights), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _try_mediapipe():
    try:
        import mediapipe as mp

        return mp
    except Exception:
        return None


def _euclidean(a, b):
    import numpy as np

    return np.linalg.norm(a - b)


def _points(landmarks, indices, w, h):
    import numpy as np

    return [np.array([landmarks[i].x * w, landmarks[i].y * h]) for i in indices]


def calculate_ear(landmarks, eye_indices, w, h) -> float:
    pts = _points(landmarks, eye_indices, w, h)
    v1 = _euclidean(pts[1], pts[5])
    v2 = _euclidean(pts[2], pts[4])
    horizontal = _euclidean(pts[0], pts[3])
    return (v1 + v2) / (2.0 * (horizontal + 1e-6))


def calculate_mar(landmarks, mouth_indices, w, h) -> float:
    pts = _points(landmarks, mouth_indices, w, h)
    v1 = _euclidean(pts[1], pts[7])
    v2 = _euclidean(pts[2], pts[6])
    v3 = _euclidean(pts[3], pts[5])
    horizontal = _euclidean(pts[0], pts[4])
    return (v1 + v2 + v3) / (2.0 * (horizontal + 1e-6))


def _detect_phone(result, model_names, frame_h, draw_on=None):
    """A phone must be the right size, upright, and in the driver's reach."""
    import cv2
    import numpy as np

    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return False

    for box, cls in zip(boxes.xyxy, boxes.cls):
        name = str(model_names[int(cls)]).lower()
        if not ("phone" in name or "cell" in name or int(cls) == 0):
            continue
        x1, y1, x2, y2 = (int(v) for v in np.ravel(box)[:4])
        bw, bh = x2 - x1, y2 - y1
        if bw <= 0 or bh <= 0:
            continue
        aspect = bh / float(bw + 1e-6)
        centre_y = (y1 + y2) / 2.0

        if not (PHONE_MIN_W < bw < PHONE_MAX_W and PHONE_MIN_H < bh < PHONE_MAX_H):
            continue
        if aspect <= PHONE_MIN_ASPECT:
            continue
        if not (centre_y < frame_h * PHONE_BOTTOM_MARGIN and y1 > frame_h * PHONE_TOP_MARGIN):
            continue

        if draw_on is not None:
            cv2.rectangle(draw_on, (x1, y1), (x2, y2), (0, 0, 255), 2)
            cv2.putText(draw_on, "Phone", (x1, max(65, y1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        return True
    return False


def _candidate_count(result) -> int:
    """How many raw boxes the model produced, before any filtering."""
    total = 0
    for attr in ("boxes", "obb"):
        container = getattr(result, attr, None)
        if container is not None:
            try:
                total += len(container)
            except TypeError:
                pass
    return total


def _detect_belt(result, model_names, chin_y, draw_on=None, rejected=None):
    """
    Decide whether a seatbelt is visibly worn.

    Two very different situations, and conflating them is what breaks this:

    A **single-class** model only ever emits "belt found here". There is
    nothing to disambiguate, so any detection above the confidence threshold
    means the belt is on, and geometric filtering can only lose true positives.

    A **multi-class** model can emit a negative class, and a confident
    `no_seatbelt` box must never be read as evidence the belt is on. The label
    is checked, and the geometry filters guard against a stray box being taken
    for a chest strap.

    `rejected` collects the reason each candidate was discarded, so a run that
    finds nothing can say why rather than silently reporting compliance.
    """
    import cv2
    import numpy as np

    single_class = len(model_names) <= 1

    def note(reason):
        if rejected is not None:
            rejected[reason] = rejected.get(reason, 0) + 1

    boxes = getattr(result, "boxes", None)
    if boxes is not None and len(boxes) > 0:
        for box, cls in zip(boxes.xyxy, boxes.cls):
            name = str(model_names[int(cls)]).strip().lower()
            x1, y1, x2, y2 = (int(v) for v in np.ravel(box)[:4])
            bw, bh = x2 - x1, y2 - y1

            if not single_class:
                if name in NEGATIVE_BELT_LABELS or "no" in name.split("_"):
                    note("labelled as a negative class")
                    continue
                if bh <= 0 or (bw / float(bh + 1e-6)) >= BELT_MAX_ASPECT:
                    note("box was wider than a chest strap should be")
                    continue
                if ((y1 + y2) / 2.0) <= chin_y * BELT_CHIN_FACTOR:
                    note("box sat above the chin")
                    continue

            if draw_on is not None:
                cv2.rectangle(draw_on, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(draw_on, "Seatbelt", (x1, max(65, y1 - 5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            return True

    obb = getattr(result, "obb", None)
    if obb is not None and len(obb) > 0:
        for polygon in obb.xyxyxyxy:
            pts = np.array(polygon.cpu() if hasattr(polygon, "cpu") else polygon).astype(np.int32)
            pts = pts.reshape(-1, 2)
            if not single_class and float(np.mean(pts[:, 1])) <= chin_y * BELT_CHIN_FACTOR:
                note("rotated box sat above the chin")
                continue
            if draw_on is not None:
                cv2.polylines(draw_on, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
            return True
    return False


class _Tracker:
    """Tracks one violation type across frames."""

    def __init__(self, kind: str, cooldown: float, latch: bool,
                 end_gap: float = END_GAP_SECONDS):
        self.kind = kind
        self.cooldown = cooldown
        self.latch = latch
        self.end_gap = end_gap
        self.active = False
        self.started_at: float | None = None
        self.last_seen: float | None = None
        self.last_logged: float = -1e9
        self.pending: Detection | None = None

    def update(self, present: bool, video_t: float) -> Detection | None:
        if present:
            self.last_seen = video_t
            if not self.active:
                self.active = True
                self.started_at = video_t
                if self.latch:
                    return self._make(video_t)
            if not self.latch and video_t - self.last_logged >= self.cooldown:
                return self._make(video_t)
            return None

        if self.active and self.last_seen is not None:
            if video_t - self.last_seen >= self.end_gap:
                self._close(self.last_seen, "")
                self.active = False
                self.started_at = None
        return None

    def close(self, video_t: float) -> None:
        if self.active:
            self._close(video_t, ", still ongoing at the end of the clip")
            self.active = False

    def _close(self, video_t: float, suffix: str) -> None:
        if self.pending is not None and self.started_at is not None:
            duration = round(video_t - self.started_at, 1)
            self.pending.duration_s = duration
            self.pending.note = f"{self.pending.note} (lasted {duration:g}s{suffix})"
        self.pending = None

    def _make(self, video_t: float) -> Detection:
        self.last_logged = video_t
        det = Detection(
            trip_id="",
            violation_type=self.kind,
            timestamp=datetime.now(),
            source="in_cab",
            severity=SEVERITY.get(self.kind, "medium"),
            note=NOTES[self.kind],
            video_second=round(video_t, 1),
        )
        if self.latch:
            self.pending = det
        return det


def analyse_incab(
    video_path: str,
    trip_id: str,
    start_time: datetime,
    models_dir: Path,
    output_dir: Path,
    confidence: float = PHONE_CONF,
    stride: int = 3,
    max_seconds: float | None = None,
    progress=None,
    belt_confidence: float = BELT_CONF,
) -> EngineReport:
    yolo = try_load_yolo()
    mp = _try_mediapipe()
    notes: list[str] = []

    if yolo is None and mp is None:
        return EngineReport(
            engine="unavailable",
            notes=[
                "Neither ultralytics nor mediapipe is installed, so nothing was analysed.",
                "Install them with: pip install -r requirements-cv.txt",
            ],
            detections=[],
        )

    phone_model = belt_model = None
    if yolo is not None:
        phone_path = _resolve(models_dir, PHONE_WEIGHTS)
        belt_path = _resolve(models_dir, BELT_WEIGHTS)

        if phone_path:
            phone_model, error = _load(yolo, str(phone_path))
            notes.append(
                f"Phone model: trained weights ({phone_path.name})." if phone_model
                else f"Phone model: {phone_path.name} would not load ({error}). DISABLED."
            )
        else:
            phone_model, error = _load(yolo, "yolov8n.pt")
            notes.append(
                "Phone model: no trained weights in models/ - using stock YOLOv8n and "
                "its COCO 'cell phone' class. Lower accuracy than the trained model."
                if phone_model else
                f"Phone model: no weights in models/ and YOLOv8n could not be "
                f"downloaded ({error}). Phone detection DISABLED - put "
                f"bestphonenew.pt in models/, or connect to the internet once."
            )

        if belt_path:
            belt_model, error = _load(yolo, str(belt_path))
            if belt_model:
                classes = ", ".join(str(v) for v in belt_model.names.values())
                mode = (
                    "single class, so any detection counts as the belt being worn"
                    if len(belt_model.names) <= 1
                    else "multiple classes, so labels and geometry are checked"
                )
                notes.append(
                    f"Seatbelt model: {belt_path.name} (classes: {classes}) - {mode}."
                )
            else:
                notes.append(f"Seatbelt model: {belt_path.name} would not load ({error}).")
        else:
            notes.append(
                "Seatbelt model: no weights in models/ - seatbelt detection is "
                "DISABLED. Zero no_seatbelt rows means 'not checked', not 'compliant'."
            )
    else:
        notes.append(
            "ultralytics is not installed - phone and seatbelt detection are DISABLED. "
            "Run: pip install -r requirements-cv.txt"
        )

    face_mesh = None
    if mp is not None:
        try:
            face_mesh = mp.solutions.face_mesh.FaceMesh(
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.35,
                min_tracking_confidence=0.35,
            )
            notes.append("Drowsiness and yawning: MediaPipe FaceMesh.")
        except Exception as exc:
            notes.append(
                f"MediaPipe is installed but would not start ({type(exc).__name__}) - "
                "drowsiness and yawning are DISABLED. Reinstall with: "
                "pip install --force-reinstall mediapipe"
            )
    else:
        notes.append(
            "mediapipe is not installed - drowsiness and yawning are DISABLED. "
            "Run: pip install -r requirements-cv.txt"
        )

    if phone_model is None and belt_model is None and face_mesh is None:
        return EngineReport(
            engine="unavailable",
            notes=["No detector could start, so the footage was not checked."] + notes,
            detections=[],
        )

    cap, fps, width, height, total_frames = open_video(video_path)
    if cap is None:
        if face_mesh is not None:
            face_mesh.close()
        return EngineReport(engine="error", notes=[f"Could not open {video_path}"],
                            detections=[])

    import cv2

    stride = max(1, int(stride))
    ear_consec = max(1, round(EAR_CONSEC_SECONDS * fps / stride))
    mar_consec = max(1, round(MAR_CONSEC_SECONDS * fps / stride))

    writer = VideoWriterSafe(
        output_dir / f"annotated_incab_{trip_id}.mp4", fps=fps / stride, size=(width, height)
    )

    phone = _Tracker("phone_use", PHONE_COOLDOWN_SEC, PHONE_LATCH)
    drowsy = _Tracker("drowsiness", DROWSY_COOLDOWN_SEC, DROWSY_LATCH)
    yawn = _Tracker("yawning", YAWN_COOLDOWN_SEC, latch=False)

    detections: list[Detection] = []
    counter_ear = counter_mar = 0
    unbuckled_since: float | None = None
    belt_violating = False
    last_belt_logged = -1e9
    faces_seen = samples = 0
    belt_frames = belt_found = belt_raw = 0
    belt_rejected: dict[str, int] = {}
    frame_idx = processed = 0
    video_t = 0.0
    frame_limit = int(fps * max_seconds) if max_seconds else None

    def log(det: Detection | None) -> str | None:
        if det is None:
            return None
        det.trip_id = trip_id
        det.timestamp = start_time + timedelta(seconds=det.video_second)
        detections.append(det)
        return det.note

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_limit and frame_idx > frame_limit:
            break
        if frame_idx % stride != 0:
            frame_idx += 1
            continue

        video_t = frame_idx / fps
        h, w = frame.shape[:2]
        annotated = frame.copy()
        alert = None

        # Face first: the chin position anchors the seatbelt geometry check.
        landmarks = None
        chin_y = h * 0.40
        if face_mesh is not None:
            mp_results = face_mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            samples += 1
            if mp_results.multi_face_landmarks:
                faces_seen += 1
                landmarks = mp_results.multi_face_landmarks[0].landmark
                chin_y = landmarks[CHIN_LANDMARK].y * h

        if phone_model is not None:
            result = phone_model.predict(source=frame, conf=confidence, verbose=False)[0]
            has_phone = _detect_phone(result, phone_model.names, h, draw_on=annotated)
            alert = log(phone.update(has_phone, video_t)) or alert

        if belt_model is not None:
            result = belt_model.predict(source=frame, conf=belt_confidence, verbose=False)[0]
            has_belt = _detect_belt(
                result, belt_model.names, chin_y, draw_on=annotated, rejected=belt_rejected
            )
            belt_frames += 1
            belt_found += 1 if has_belt else 0
            belt_raw += _candidate_count(result)

            if not has_belt:
                if unbuckled_since is None:
                    unbuckled_since = video_t
                elif (video_t - unbuckled_since) >= BELT_TRIGGER_SECONDS:
                    if not belt_violating and (video_t - last_belt_logged) > BELT_COOLDOWN_SEC:
                        det = Detection(
                            trip_id=trip_id,
                            violation_type="no_seatbelt",
                            timestamp=start_time + timedelta(seconds=video_t),
                            source="in_cab",
                            severity="high",
                            note=NOTES["no_seatbelt"],
                            video_second=round(video_t, 1),
                        )
                        detections.append(det)
                        alert = det.note
                        belt_violating = True
                        last_belt_logged = video_t
            else:
                unbuckled_since = None
                belt_violating = False

        if landmarks is not None:
            ear = max(
                calculate_ear(landmarks, LEFT_EYE, w, h),
                calculate_ear(landmarks, RIGHT_EYE, w, h),
            )
            mar = calculate_mar(landmarks, MOUTH, w, h)

            cv2.putText(
                annotated, f"EAR {ear:.2f} | MAR {mar:.2f}", (15, h - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (235, 235, 235), 2,
            )

            counter_ear = counter_ear + 1 if ear < EAR_THRESHOLD else 0
            counter_mar = counter_mar + 1 if mar > MAR_THRESHOLD else 0

            alert = log(drowsy.update(counter_ear >= ear_consec, video_t)) or alert
            alert = log(yawn.update(counter_mar >= mar_consec, video_t)) or alert
        elif face_mesh is not None:
            counter_ear = counter_mar = 0
            drowsy.update(False, video_t)
            yawn.update(False, video_t)

        if alert:
            draw_banner(annotated, alert)
            save_evidence(annotated, output_dir, trip_id, len(detections))

        writer.write(annotated)
        frame_idx += 1
        processed += 1
        if progress and processed % 5 == 0:
            progress(min(frame_idx / max(total_frames, 1), 0.99), len(detections))

    for tracker in (phone, drowsy, yawn):
        tracker.close(video_t)

    cap.release()
    writer.release()
    if face_mesh is not None:
        face_mesh.close()

    checked = round(frame_idx / fps, 1) if fps else 0.0
    if checked and checked < 10:
        notes.append(
            f"⚠ Only {checked:g}s of footage was checked. The seatbelt rule needs 3s "
            "and drowsiness needs sustained eye closure, so a very short clip can look "
            "clean simply because nothing had time to trigger."
        )

    if belt_model is not None and belt_frames:
        rate = belt_found / belt_frames * 100
        notes.append(
            f"Seatbelt visible in {rate:.0f}% of analysed frames "
            f"(model returned {belt_raw} candidate box(es) across {belt_frames} frames "
            f"at confidence {belt_confidence:g})."
        )
        if rate == 0:
            reasons = ", ".join(f"{k} ({v})" for k, v in belt_rejected.items())
            if belt_raw == 0:
                notes.append(
                    f"⚠ The seatbelt model returned nothing at confidence "
                    f"{belt_confidence:g}. Lower it under Detector settings and run "
                    f"again before treating any no_seatbelt row as a real violation."
                )
            else:
                notes.append(
                    f"⚠ The model found {belt_raw} candidate(s) but none were accepted: "
                    f"{reasons}. Every no_seatbelt row below reflects the filters, not "
                    f"an unfastened belt."
                )

    if face_mesh is not None and samples:
        face_rate = faces_seen / samples * 100
        if face_rate < 50:
            notes.append(
                f"⚠ A face was found in only {face_rate:.0f}% of analysed frames — "
                "drowsiness and yawning results are unreliable on this clip. Check "
                "the camera angle and the lighting."
            )
        else:
            notes.append(f"Face detected in {face_rate:.0f}% of analysed frames.")

    return EngineReport(
        engine="in_cab",
        notes=notes,
        detections=detections,
        annotated_video=writer.path_if_written(),
        frames_processed=processed,
        video_seconds=checked,
        safety_score=safety_score(detections),
    )


def safety_score(detections) -> int:
    """100 minus a penalty per violation, floored at zero."""
    score = 100 - sum(SCORE_PENALTY.get(d.violation_type, 0) for d in detections)
    return max(0, score)
