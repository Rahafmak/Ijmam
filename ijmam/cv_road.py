"""Road-facing camera: lane departure, weaving and following distance."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from .cv_common import (
    Detection,
    EngineReport,
    VideoWriterSafe,
    draw_banner,
    open_video,
    save_evidence,
    try_cv2,
    try_load_yolo,
)

VEHICLE_CLASSES = [2, 5, 7]                    # car, bus, truck (COCO)
KNOWN_WIDTHS = {2: 1.8, 5: 2.5, 7: 2.5}        # metres
FOCAL_LENGTH = 750.0


class SimpleLaneDetector:
    def __init__(
        self,
        departure_threshold=0.28,
        approach_threshold=0.10,
        fast_change_frames=5,
        weave_window=10,
        weave_min_crossings=2,
        weave_cooldown_frames=15,
    ):
        self.departure_threshold = departure_threshold
        self.approach_threshold = approach_threshold
        self.fast_change_frames = fast_change_frames
        self.weave_min_crossings = weave_min_crossings
        self.weave_cooldown_frames = weave_cooldown_frames

        self.transit_frames = 0
        self.currently_departed = False
        self.missing_frames = 0
        self.weave_history = deque(maxlen=weave_window)
        self.frames_since_weave_alert = weave_cooldown_frames

    def _find_lane_lines(self, frame):
        cv2 = try_cv2()
        import numpy as np

        height, width = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 50, 150)

        mask = np.zeros_like(edges)
        polygon = np.array(
            [[
                (int(width * 0.1), height),
                (int(width * 0.45), int(height * 0.6)),
                (int(width * 0.55), int(height * 0.6)),
                (int(width * 0.9), height),
            ]],
            np.int32,
        )
        cv2.fillPoly(mask, polygon, 255)
        masked_edges = cv2.bitwise_and(edges, mask)

        lines = cv2.HoughLinesP(
            masked_edges, 1, np.pi / 180, threshold=40, minLineLength=50, maxLineGap=150
        )

        left_points, right_points = [], []
        if lines is not None:
            for line in lines:
                # OpenCV returns (N, 1, 4) on some builds and (N, 4) on others.
                coords = np.ravel(line)
                if coords.size < 4:
                    continue
                x1, y1, x2, y2 = (int(v) for v in coords[:4])
                if x2 == x1:
                    continue
                slope = (y2 - y1) / (x2 - x1)
                if slope < -0.5:
                    left_points.extend([x1, x2])
                elif slope > 0.5:
                    right_points.extend([x1, x2])
        return left_points, right_points, width, height

    def _compute_offset(self, frame):
        import numpy as np

        left_points, right_points, width, _ = self._find_lane_lines(frame)
        left_x = float(np.mean(left_points)) if left_points else None
        right_x = float(np.mean(right_points)) if right_points else None
        if left_x is None and right_x is None:
            return None

        frame_center = width / 2.0
        if left_x is not None and right_x is not None:
            lane_center = (left_x + right_x) / 2.0
        elif left_x is not None:
            lane_center = left_x + (width * 0.25)
        else:
            lane_center = right_x - (width * 0.25)

        offset = (lane_center - frame_center) / (width / 2.0)
        return max(-1.0, min(1.0, offset))

    def process_frame(self, frame):
        offset = self._compute_offset(frame)
        self.frames_since_weave_alert += 1

        if offset is None:
            self.missing_frames += 1
            if self.missing_frames == 8:
                return {
                    "event_type": "lane_markings_unclear",
                    "detected": False,
                    "severity": "low",
                    "note": "Lane markings are not clear",
                }
            return None

        self.missing_frames = 0
        self.weave_history.append(offset)
        return self._check_weaving() or self._check_departure(offset)

    def _check_weaving(self):
        if len(self.weave_history) < self.weave_history.maxlen:
            return None
        if self.frames_since_weave_alert < self.weave_cooldown_frames:
            return None

        direction_changes, last_sign = 0, 0
        values = list(self.weave_history)
        for i in range(1, len(values)):
            delta = values[i] - values[i - 1]
            if abs(delta) < 0.05:
                continue
            sign = 1 if delta > 0 else -1
            if last_sign != 0 and sign != last_sign:
                direction_changes += 1
            last_sign = sign

        if direction_changes >= self.weave_min_crossings:
            self.frames_since_weave_alert = 0
            return {
                "event_type": "fatigue",
                "detected": True,
                "severity": "high",
                "note": "Possible drowsiness - weaving detected",
            }
        return None

    def _check_departure(self, offset):
        abs_offset = abs(offset)
        if abs_offset >= self.departure_threshold:
            if self.currently_departed:
                return None
            self.currently_departed = True
            frames_it_took = self.transit_frames
            self.transit_frames = 0
            if frames_it_took <= self.fast_change_frames:
                return None
            direction = "right" if offset > 0 else "left"
            return {
                "event_type": "lane_departure",
                "detected": True,
                "severity": "medium",
                "note": f"Gradual drift to the {direction} (distraction or drowsiness)",
            }
        elif abs_offset >= self.approach_threshold:
            self.transit_frames += 1
            self.currently_departed = False
        else:
            self.transit_frames = 0
            self.currently_departed = False
        return None


class ProductionSafeDistanceTracker:
    def __init__(self, safe_distance_m=15.0, cooldown_frames=15):
        self.safe_distance_m = safe_distance_m
        self.cooldown_frames = cooldown_frames
        self.frames_since_alert = cooldown_frames
        self.dist_history = deque(maxlen=6)

    def reset(self):
        self.dist_history.clear()
        self.frames_since_alert = self.cooldown_frames

    def process(self, cls_id, box_pixel_width):
        self.frames_since_alert += 1
        real_w = KNOWN_WIDTHS.get(cls_id, 1.8)
        current_dist = (real_w * FOCAL_LENGTH) / max(box_pixel_width, 1)
        self.dist_history.append(current_dist)

        if len(self.dist_history) < self.dist_history.maxlen:
            return current_dist, None

        approach_speed = (self.dist_history[0] - self.dist_history[-1]) / len(self.dist_history)
        is_too_close = current_dist < self.safe_distance_m
        is_closing_fast = approach_speed > 0.4

        if (is_too_close or is_closing_fast) and self.frames_since_alert >= self.cooldown_frames:
            self.frames_since_alert = 0
            severity = "high" if (current_dist < 8.0 or (is_too_close and is_closing_fast)) else "medium"
            if is_too_close and is_closing_fast:
                note = f"Very close and closing fast ({current_dist:.1f} m)"
            elif is_too_close:
                note = f"Unsafe following distance ({current_dist:.1f} m)"
            else:
                note = f"Rapidly approaching the vehicle ahead ({current_dist:.1f} m)"
            return current_dist, {
                "event_type": "unsafe_distance",
                "detected": True,
                "severity": severity,
                "note": note,
            }
        return current_dist, None


def analyse_road(
    video_path: str,
    trip_id: str,
    start_time: datetime,
    models_dir: Path,
    output_dir: Path,
    confidence: float = 0.30,
    stride: int = 3,
    max_seconds: float | None = None,
    progress=None,
) -> EngineReport:
    cv2 = try_cv2()
    if cv2 is None:
        return EngineReport(
            engine="unavailable",
            notes=["OpenCV is not installed - run: pip install -r requirements-cv.txt"],
            detections=[],
        )

    notes: list[str] = ["Lane and weaving detection: no model weights needed."]
    yolo = try_load_yolo()
    vehicle_model = None
    if yolo is not None:
        try:
            vehicle_model = yolo("yolov8n.pt")
            notes.append("Following distance: YOLOv8n vehicle detection.")
        except Exception as exc:
            notes.append(
                f"Following distance DISABLED - YOLOv8n could not load "
                f"({type(exc).__name__}). It downloads on first use, so this usually "
                f"means no internet. Lane and weaving analysis still ran."
            )
    else:
        notes.append(
            "Following distance DISABLED - ultralytics is not installed. "
            "Lane and weaving analysis still ran."
        )

    cap, fps, width, height, total_frames = open_video(video_path)
    if cap is None:
        return EngineReport(engine="error", notes=[f"Could not open {video_path}"], detections=[])

    stride = max(1, int(stride))
    lane = SimpleLaneDetector()
    distance = ProductionSafeDistanceTracker(safe_distance_m=15.0)

    out_path = output_dir / f"annotated_road_{trip_id}.mp4"
    writer = VideoWriterSafe(out_path, fps=fps / stride, size=(width, height))

    detections: list[Detection] = []
    frame_idx = 0
    processed = 0
    frame_limit = int(fps * max_seconds) if max_seconds else None

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_limit and frame_idx > frame_limit:
            break
        if frame_idx % stride != 0:
            frame_idx += 1
            continue

        h, w = frame.shape[:2]
        timestamp = start_time + timedelta(seconds=frame_idx / fps)
        alert = None

        lane_alert = lane.process_frame(frame)
        if lane_alert and lane_alert.get("detected"):
            det = Detection(
                trip_id=trip_id,
                violation_type=lane_alert["event_type"],
                timestamp=timestamp,
                source="road",
                severity=lane_alert["severity"],
                note=lane_alert["note"],
                video_second=round(frame_idx / fps, 1),
            )
            detections.append(det)
            alert = det.note

        if vehicle_model is not None:
            results = vehicle_model.predict(source=frame, conf=confidence, verbose=False)
            closest, min_distance = None, 999.0
            for box in results[0].boxes:
                try:
                    cls_id = int(np.ravel(box.cls)[0])
                    x1, y1, x2, y2 = (int(v) for v in np.ravel(box.xyxy)[:4])
                except (IndexError, ValueError, TypeError):
                    continue
                if cls_id not in VEHICLE_CLASSES:
                    continue
                box_w = x2 - x1
                center_x = (x1 + x2) / 2
                if not (w * 0.35) < center_x < (w * 0.65):
                    continue
                approx = (KNOWN_WIDTHS.get(cls_id, 1.8) * FOCAL_LENGTH) / max(box_w, 1)
                if approx < min_distance:
                    min_distance = approx
                    closest = (cls_id, box_w, (x1, y1, x2, y2))

            if closest is not None:
                cls_id, box_w, (x1, y1, x2, y2) = closest
                dist_m, dist_alert = distance.process(cls_id, box_w)
                colour = (89, 122, 255) if dist_m < 15.0 else (190, 209, 79)
                cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)
                cv2.putText(
                    frame, f"{dist_m:.1f} m", (x1, max(y1 - 10, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2,
                )
                if dist_alert:
                    det = Detection(
                        trip_id=trip_id,
                        violation_type=dist_alert["event_type"],
                        timestamp=timestamp,
                        source="road",
                        severity=dist_alert["severity"],
                        note=dist_alert["note"],
                        video_second=round(frame_idx / fps, 1),
                    )
                    detections.append(det)
                    alert = det.note
            else:
                distance.reset()

        if alert:
            draw_banner(frame, alert)
            save_evidence(frame, output_dir, trip_id, len(detections))

        writer.write(frame)
        frame_idx += 1
        processed += 1
        if progress and processed % 5 == 0:
            progress(min(frame_idx / max(total_frames, 1), 0.99), len(detections))

    cap.release()
    writer.release()

    return EngineReport(
        engine="road",
        notes=notes,
        detections=detections,
        annotated_video=writer.path_if_written(),
        frames_processed=processed,
        video_seconds=round(frame_idx / fps, 1) if fps else 0.0,
    )
