"""
Generate a synthetic road clip that provably triggers the road detectors.

    python scripts_make_demo_video.py

Use it to prove the pipeline works before you have real dashcam footage, and to
sanity-check the app on any machine. It is NOT a substitute for real footage in
the final presentation - say plainly that it is synthetic if you show it.

The clip has two phases: a slow drift out of lane (should log `lane_departure`)
and then fast oscillation (should log `fatigue` - weaving).
"""

import math
from pathlib import Path

import cv2
import numpy as np

W, H, FPS, SECONDS = 640, 360, 20, 22
OUT = Path(__file__).resolve().parents[1] / "data" / "uploads" / "demo_road.mp4"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(OUT), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for i in range(FPS * SECONDS):
        t = i / FPS
        frame = np.full((H, W, 3), 40, np.uint8)
        cv2.rectangle(frame, (0, 0), (W, int(H * 0.55)), (90, 110, 140), -1)
        offset = 150 * math.sin(t * 0.5) if t < 10 else 110 * math.sin((t - 10) * 8.0)
        cx = W / 2 + offset
        cv2.line(frame, (int(cx - 160), H), (int(cx - 40), int(H * 0.62)), (235, 235, 235), 6)
        cv2.line(frame, (int(cx + 160), H), (int(cx + 40), int(H * 0.62)), (235, 235, 235), 6)
        writer.write(frame)
    writer.release()
    print(f"Wrote {OUT} ({SECONDS}s). Upload it on the Camera Analysis tab, camera = Road-facing.")


if __name__ == "__main__":
    main()
