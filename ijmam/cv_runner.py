"""Turn a video into a violations CSV."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from .cv_common import CSV_COLUMNS, EngineReport
from .cv_incab import analyse_incab
from .cv_road import analyse_road


def run_analysis(
    video_path: str,
    camera: str,
    trip_id: str,
    start_time: datetime,
    models_dir: Path,
    output_dir: Path,
    confidence: float = 0.30,
    stride: int = 3,
    max_seconds: float | None = 90.0,
    progress=None,
    belt_confidence: float | None = None,
) -> EngineReport:
    """Run the detectors for one camera. `max_seconds` caps how much is checked."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    kwargs = dict(
        video_path=video_path,
        trip_id=trip_id,
        start_time=start_time,
        models_dir=Path(models_dir),
        output_dir=Path(output_dir),
        confidence=confidence,
        stride=stride,
        max_seconds=max_seconds,
        progress=progress,
    )
    if camera == "in_cab":
        if belt_confidence is not None:
            kwargs["belt_confidence"] = belt_confidence
        report = analyse_incab(**kwargs)
    else:
        report = analyse_road(**kwargs)
    evidence_dir = Path(output_dir) / "evidence"
    if evidence_dir.exists():
        report.evidence_frames = sorted(evidence_dir.glob(f"{trip_id}_*.jpg"))
    return report


def to_dataframe(report: EngineReport) -> pd.DataFrame:
    rows = [d.as_row() for d in report.detections]
    if not rows:
        return pd.DataFrame(columns=CSV_COLUMNS)
    return pd.DataFrame(rows)[CSV_COLUMNS]


def write_csv(report: EngineReport, output_dir: Path, trip_id: str) -> Path:
    path = Path(output_dir) / f"violations_{trip_id}.csv"
    to_dataframe(report).to_csv(path, index=False)
    return path


def summarise(report: EngineReport) -> dict:
    df = to_dataframe(report)
    by_type = (
        df["violation_type"].value_counts().to_dict() if not df.empty else {}
    )
    return {
        "total": len(df),
        "by_type": by_type,
        "high_severity": int((df["severity"] == "high").sum()) if not df.empty else 0,
        "frames_processed": report.frames_processed,
        "video_seconds": report.video_seconds,
        "engine": report.engine,
        "safety_score": report.safety_score,
    }
