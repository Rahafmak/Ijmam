"""Shared pieces for both camera engines: detections, video IO, evidence frames."""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# The CSV contract. Extra columns are additive - anything reading only the
# first three still works.
CSV_COLUMNS = [
    "trip_id",
    "violation_type",
    "timestamp",
    "source",
    "severity",
    "note",
    "video_second",
    "duration_s",
]


@dataclass
class Detection:
    trip_id: str
    violation_type: str
    timestamp: datetime
    source: str            # "in_cab" | "road"
    severity: str          # "high" | "medium" | "low"
    note: str
    video_second: float
    # How long a sustained violation lasted, if it ended before the clip did.
    duration_s: float | None = None

    def as_row(self) -> dict:
        return {
            "trip_id": self.trip_id,
            "violation_type": self.violation_type,
            "timestamp": self.timestamp.strftime("%Y-%m-%dT%H:%M:%S"),
            "source": self.source,
            "severity": self.severity,
            "note": self.note,
            "video_second": self.video_second,
            "duration_s": self.duration_s,
        }


@dataclass
class EngineReport:
    engine: str
    notes: list[str]
    detections: list[Detection]
    annotated_video: Path | None = None
    evidence_frames: list[Path] = field(default_factory=list)
    frames_processed: int = 0
    video_seconds: float = 0.0
    safety_score: int | None = None

    @property
    def ok(self) -> bool:
        return self.engine not in {"unavailable", "error"}


@contextlib.contextmanager
def _quiet_stderr():
    """Silence FFmpeg's stderr while probing codecs.

    It prints red ERROR lines before falling back to mp4v and working fine.
    """
    fd = os.dup(2)
    try:
        with open(os.devnull, "w") as devnull:
            os.dup2(devnull.fileno(), 2)
            yield
    finally:
        os.dup2(fd, 2)
        os.close(fd)


def try_load_yolo():
    """Return the YOLO class, or None if ultralytics/opencv aren't installed."""
    try:
        import cv2  # noqa: F401
        from ultralytics import YOLO

        return YOLO
    except Exception:
        return None


def try_cv2():
    try:
        import cv2

        return cv2
    except Exception:
        return None


def open_video(path: str):
    cv2 = try_cv2()
    if cv2 is None:
        return None, 0, 0, 0, 0
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None, 0, 0, 0, 0
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 360
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    return cap, fps, width, height, total


class VideoWriterSafe:
    """Writes an annotated MP4, falling back through codecs.

    If none work the run still completes and the evidence frames carry the
    visual proof instead.
    """

    def __init__(self, path: Path, fps: float, size: tuple[int, int]):
        self.path = Path(path)
        self._writer = None
        cv2 = try_cv2()
        if cv2 is None:
            return
        for codec in ("avc1", "mp4v"):
            try:
                with _quiet_stderr():
                    fourcc = cv2.VideoWriter_fourcc(*codec)
                    writer = cv2.VideoWriter(str(self.path), fourcc, max(fps, 1.0), size)
                    opened = writer.isOpened()
                if opened:
                    self._writer = writer
                    self.codec = codec
                    break
            except Exception:
                continue

    def write(self, frame) -> None:
        if self._writer is not None:
            self._writer.write(frame)

    def release(self) -> None:
        if self._writer is not None:
            self._writer.release()

    def path_if_written(self) -> Path | None:
        if self._writer is not None and self.path.exists() and self.path.stat().st_size > 1024:
            return self.path
        return None


def draw_banner(frame, text: str) -> None:
    cv2 = try_cv2()
    if cv2 is None:
        return
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w, 46), (10, 14, 26), -1)
    cv2.putText(
        frame, text[:80], (16, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (59, 169, 242), 2
    )


def save_evidence(frame, output_dir: Path, trip_id: str, index: int) -> Path | None:
    cv2 = try_cv2()
    if cv2 is None:
        return None
    evidence_dir = Path(output_dir) / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / f"{trip_id}_{index:03d}.jpg"
    try:
        cv2.imwrite(str(path), frame)
        return path
    except Exception:
        return None
