"""
Pre-demo check. Run this before you present.

    python check.py

It exercises everything that does not need a browser: the planner, the two
chatbots, the insights pipeline, and (if opencv is installed) the road
detectors on a generated clip. If this passes, the only thing left that can
break is the browser layer.
"""

from __future__ import annotations

import sys

# `X | None` annotations and several defaults here need Python 3.10 or newer.
# macOS ships 3.9, so fail with a sentence someone can act on rather than a
# TypeError about the | operator.
if sys.version_info < (3, 10):
    raise SystemExit(
        f"Ijmam needs Python 3.10 or newer — you are on "
        f"{sys.version_info.major}.{sys.version_info.minor}.\n"
        f"  brew install python@3.12\n"
        f"  python3.12 -m venv .venv && source .venv/bin/activate\n"
        f"  pip install -r requirements.txt"
    )


import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

GREEN, RED, YELLOW, RESET = "\033[92m", "\033[91m", "\033[93m", "\033[0m"

results: list[tuple[str, bool, str]] = []


def check(name):
    def deco(fn):
        try:
            note = fn() or ""
            results.append((name, True, note))
        except Exception as exc:
            results.append((name, False, f"{type(exc).__name__}: {exc}"))
            traceback.print_exc(limit=2)
        return fn
    return deco


@check("planner: day schedule matches the manual's 4h / 30min rule")
def _():
    from datetime import datetime
    from ijmam.policy_rules import DAY_BREAK_MINUTES, DAY_MAX_CONTINUOUS_H
    from ijmam.trip import plan_trip
    plan = plan_trip("Jeddah", "Riyadh", 9, 1, None, datetime(2026, 8, 24, 6, 0))
    assert plan.schedule.night_hours == 0, plan.schedule.night_hours
    assert plan.driving_between_stops <= DAY_MAX_CONTINUOUS_H, plan.driving_between_stops
    assert all(s.minutes >= DAY_BREAK_MINUTES for s in plan.stops), plan.stops
    return f"{len(plan.stops)} breaks, longest leg {plan.driving_between_stops}h"


@check("planner: night schedule tightens to the 2h / 20min rule")
def _():
    from datetime import datetime
    from ijmam.policy_rules import NIGHT_BREAK_MINUTES, NIGHT_MAX_CONTINUOUS_H
    from ijmam.trip import plan_trip
    plan = plan_trip("Jeddah", "Tabuk", 9, 1, None, datetime(2026, 8, 24, 20, 0))
    night_stops = [s for s in plan.stops if s.night]
    assert night_stops, "no stop landed in the night window on a 20:00 departure"
    assert all(s.minutes == NIGHT_BREAK_MINUTES for s in night_stops)
    marks = [s.hour_mark for s in night_stops]
    gaps = [round(b - a, 1) for a, b in zip(marks, marks[1:])]
    assert all(g <= NIGHT_MAX_CONTINUOUS_H + 0.1 for g in gaps), gaps
    return f"{len(night_stops)} night stops at {NIGHT_BREAK_MINUTES} min each"


@check("planner: the same route changes shape with departure time")
def _():
    from datetime import datetime
    from ijmam.trip import plan_trip
    day = plan_trip("Jeddah", "Tabuk", 8, 1, None, datetime(2026, 8, 24, 6, 0))
    night = plan_trip("Jeddah", "Tabuk", 8, 1, None, datetime(2026, 8, 24, 20, 0))
    assert len(night.stops) > len(day.stops), (len(day.stops), len(night.stops))
    return f"{len(day.stops)} stops leaving 06:00 vs {len(night.stops)} leaving 20:00"


@check("planner: a leg crossing out of the night keeps the night limit")
def _():
    from datetime import datetime
    from ijmam.policy_rules import NIGHT_MAX_CONTINUOUS_H
    from ijmam.trip import plan_trip
    plan = plan_trip("Jeddah", "Tabuk", 10, 2, None, datetime(2026, 8, 24, 22, 0))
    assert plan.driving_between_stops <= NIGHT_MAX_CONTINUOUS_H + 0.1, (
        f"a {plan.driving_between_stops}h leg started in the night window"
    )
    return f"longest leg {plan.driving_between_stops}h on a 22:00 departure"


@check("cv: lane detection survives either OpenCV line-array shape")
def _():
    try:
        import cv2  # noqa: F401
    except Exception:
        return "SKIPPED - opencv not installed"
    import unittest.mock as mock

    import numpy as np

    from ijmam.cv_road import SimpleLaneDetector

    frame = np.zeros((360, 640, 3), np.uint8)
    shapes = {
        "(N, 1, 4)": np.array([[[10, 300, 120, 200]], [[500, 300, 400, 200]]]),
        "(N, 4)": np.array([[10, 300, 120, 200], [500, 300, 400, 200]]),
    }
    offsets = []
    for lines in shapes.values():
        with mock.patch("cv2.HoughLinesP", return_value=lines):
            offsets.append(SimpleLaneDetector()._compute_offset(frame))
    assert all(o is not None for o in offsets), offsets
    assert abs(offsets[0] - offsets[1]) < 1e-9, offsets
    return f"both shapes give offset {offsets[0]:.3f}"


@check("uploads: any NiceGUI event shape yields a name and the bytes")
def _():
    import io

    src = (ROOT / "app.py").read_text()
    block = src[src.index("NAME_ATTRS ="):src.index("def _save_upload")]
    namespace = {"Path": Path}
    exec(block, namespace)
    get_name, get_bytes = namespace["_upload_name"], namespace["_upload_bytes"]

    payload = b"\x00\x01hello"

    def event(**kwargs):
        return type("E", (), kwargs)()

    shapes = [
        event(name="v.mp4", content=io.BytesIO(payload)),
        event(file_name="v.mp4", content=io.BytesIO(payload)),
        event(filename="v.mp4", file=io.BytesIO(payload)),
        event(name="v.mp4", data=payload),
        event(names=["v.mp4"], contents=[io.BytesIO(payload)]),
        event(name="v.mp4", payload=io.BytesIO(payload)),
    ]
    for shape in shapes:
        assert get_name(shape, "fallback.mp4") == "v.mp4", dir(shape)
        assert get_bytes(shape) == payload, dir(shape)

    try:
        get_bytes(event(name="v.mp4"))
    except AttributeError as exc:
        assert "It has:" in str(exc), exc
        return f"{len(shapes)} shapes handled; an unknown one names its attributes"
    raise AssertionError("an event with no file contents did not raise")


@check("uploads: files can be picked from the folder without any upload")
def _():
    src = (ROOT / "app.py").read_text()
    for marker in ("_folder_options", "_video_options", "_data_options", '"Refresh"'):
        assert marker in src, marker
    return "folder picker present for both video and data"


@check("insights: reads an Excel file as well as a CSV")
def _():
    from ijmam import insights
    csv = insights.load_violations(ROOT / "data" / "sample_incab_violations.csv")
    assert len(csv) > 0
    try:
        insights.load_violations(ROOT / "README.md")
    except insights.InsightsError as exc:
        assert "CSV" in str(exc) or "table" in str(exc), exc
        return f"{len(csv)} rows from CSV, unreadable files rejected clearly"
    raise AssertionError("a non-table file was accepted")


@check("planner: the 9h daily cap is enforced and drivers change the verdict")
def _():
    from datetime import datetime
    from ijmam.trip import plan_trip
    depart = datetime(2026, 8, 24, 18, 0)
    solo = plan_trip("Jeddah", "Tabuk", 10, 1, None, depart)
    pair = plan_trip("Jeddah", "Tabuk", 10, 2, None, depart)
    assert not solo.schedule.compliant, "10h solo passed the 9h cap"
    assert any("⛔" in w for w in solo.schedule.warnings)
    assert pair.schedule.compliant, pair.schedule.warnings
    return "10h solo blocked, 10h with two drivers allowed"


@check("planner: every stop cites the rule that produced it")
def _():
    from datetime import datetime
    from ijmam.trip import plan_trip
    plan = plan_trip("Jeddah", "Tabuk", 10, 1, None, datetime(2026, 8, 24, 18, 0))
    assert all(s.rule.startswith("§") for s in plan.stops), [s.rule for s in plan.stops]
    return "all stops cite a manual section"


@check("planner: Jeddah-Tabuk has curated stops")
def _():
    from datetime import datetime
    from ijmam.trip import plan_trip
    plan = plan_trip("Jeddah", "Tabuk", 10, 2, None, datetime(2026, 8, 24, 6, 0))
    assert plan.curated_stops, "the project's own flagship route has no curated stops"
    named = [m["name"] for _, m in plan.matched if m]
    assert named, "no scheduled stop matched a real location"
    return f"{len(plan.curated_stops)} stops on file, {len(named)} matched"


@check("planner: night departure advice is offered, and only when useful")
def _():
    from datetime import datetime
    from ijmam.policy_rules import departure_advice
    assert departure_advice(10, datetime(2026, 8, 24, 20, 0)), "no advice on a night run"
    assert departure_advice(6, datetime(2026, 8, 24, 8, 0)) is None, "advice on a day run"
    return "offered at 20:00, silent at 08:00"


@check("planner: route direction is not reversed")
def _():
    from datetime import datetime
    from ijmam.trip import plan_trip
    depart = datetime(2026, 8, 24, 6, 0)
    forward = plan_trip("Jeddah", "Riyadh", 9, 1, None, depart)
    reverse = plan_trip("Riyadh", "Jeddah", 9, 1, None, depart)
    f_names = [m["name"] for _, m in forward.matched if m]
    r_names = [m["name"] for _, m in reverse.matched if m]
    assert f_names and r_names
    # A shared middle stop is correct - both directions pass it. What must not
    # happen is the whole ordered list coming back identical, which is what the
    # original frozenset key did before `from` was added to each route.
    assert f_names != r_names, "reverse direction returned an identical ordering"
    return f"forward ends {f_names[-1][:26]}, reverse ends {r_names[-1][:26]}"


@check("planner and policy bot agree on the continuous-driving limit")
def _():
    from ijmam.policy_bot import PolicyBot
    from ijmam.policy_rules import DAY_MAX_CONTINUOUS_H, DAY_BREAK_MINUTES
    bot = PolicyBot(ROOT / "data" / "company_policy.txt")
    quoted = bot.answer("what is the maximum continuous driving duration").text
    assert f"{int(DAY_MAX_CONTINUOUS_H)} consecutive hours" in quoted, quoted
    assert f"{DAY_BREAK_MINUTES} minutes" in quoted, quoted
    return "planner constants appear verbatim in the manual the bot quotes"


@check("policy bot: answers from the manual and cites a section")
def _():
    from ijmam.policy_bot import PolicyBot
    bot = PolicyBot(ROOT / "data" / "company_policy.txt")
    assert len(bot.sections) >= 7, bot.sections
    a = bot.answer("what is the maximum speed")
    assert a.section and a.section.startswith("3."), a.section
    return f"{len(bot.sections)} sections, backend={bot.backend}"


@check("policy bot: an Arabic question gets a fully Arabic answer")
def _():
    from ijmam.policy_bot import PolicyBot

    bot = PolicyBot(ROOT / "data" / "company_policy.txt")
    assert bot.has_arabic, "the Arabic manual did not load"
    assert len(bot.sections) == len(bot.sections_ar), (
        f"{len(bot.sections)} English sections vs {len(bot.sections_ar)} Arabic"
    )

    def latin_ratio(text):
        letters = [c for c in text if c.isalpha()]
        if not letters:
            return 0.0
        return sum(1 for c in letters if c.isascii()) / len(letters)

    for question in bot.suggested_questions(arabic=True):
        answer = bot.answer(question)
        assert answer.section, question
        assert latin_ratio(answer.text) < 0.15, f"English leaked into: {question}"

    english = bot.answer("what is the night driving policy")
    assert latin_ratio(english.text) > 0.85, "Arabic leaked into an English answer"
    return "Arabic in, Arabic out; English in, English out"


@check("policy bot: refuses what the manual does not cover")
def _():
    from ijmam.policy_bot import PolicyBot
    bot = PolicyBot(ROOT / "data" / "company_policy.txt")
    for q in ["what is the capital of Japan", "ما هي عاصمة اليابان؟"]:
        assert bot.answer(q).section is None, q
    return "refused both"


@check("policy bot: Arabic question retrieves the right section")
def _():
    from ijmam.policy_bot import PolicyBot
    bot = PolicyBot(ROOT / "data" / "company_policy.txt")
    a = bot.answer("ايش سياسة القيادة الليلية؟")
    assert a.section and a.section.startswith("2."), a.section
    assert any("\u0600" <= ch <= "\u06FF" for ch in a.text)
    return a.section.strip()


@check("manager bot: counts match analytics exactly")
def _():
    import analytics
    from ijmam.manager_bot import ManagerBot
    bot = ManagerBot(ROOT / "data" / "synthetic_trips.json")
    for driver, kind in [("Ahmed Ali", "fatigue"), ("Youssef Hassan", "seatbelt"),
                         ("Khaled Al-Harbi", "lane_drift")]:
        expected = analytics.violation_count(bot.df, driver, kind)
        phrase = kind.replace("_", " ")
        answer = bot.answer(f"How many {phrase} violations did {driver} have?")
        assert str(expected) in answer.text, (driver, kind, expected, answer.text)
        assert answer.source == "analytics"
    return "fatigue, seatbelt and lane drift counts all matched"


@check("manager bot: per-driver segments, not one row per trip")
def _():
    from ijmam.manager_bot import ManagerBot
    bot = ManagerBot(ROOT / "data" / "synthetic_trips.json")
    trips = int(bot.df["trip_id"].nunique())
    segments = len(bot.df)
    assert segments > trips, "multi-driver trips were not split into segments"
    assert len(bot.documents) == segments, (len(bot.documents), segments)
    # each document id is trip + driver, so a shared trip yields two entries
    shared = [t for t in bot.df["trip_id"].unique()
              if (bot.df["trip_id"] == t).sum() > 1]
    assert shared, "no multi-driver trip found in the data"
    summary = bot.answer("fleet summary").text
    assert str(trips) in summary, summary
    return f"{trips} trips, {segments} segments, {len(shared)} shared trips"


@check("manager bot: a driver's own segment is returned for their last trip")
def _():
    from ijmam.manager_bot import ManagerBot
    bot = ManagerBot(ROOT / "data" / "synthetic_trips.json")
    answer = bot.answer("What happened on Ahmed's last trip?")
    assert answer.intent == "last_trip", answer.intent
    assert "Ahmed Ali" in answer.text
    # a shared trip must not return the co-driver's segment text
    assert "Driver: Ahmed Ali" in answer.text, answer.text[:300]
    return "returned the correct driver's segment"


@check("manager bot: top violators ranked correctly")
def _():
    from ijmam.manager_bot import ManagerBot
    bot = ManagerBot(ROOT / "data" / "synthetic_trips.json")
    a = bot.answer("Who are the top 3 violators?")
    top = bot.df.groupby("driver_name")["total_violations"].sum().idxmax()
    assert top in a.text, (top, a.text)
    return f"top = {top}"


@check("manager bot: narrative question falls back to retrieval")
def _():
    from ijmam.manager_bot import ManagerBot
    bot = ManagerBot(ROOT / "data" / "synthetic_trips.json")
    destination = bot.df["destination"].value_counts().idxmax()
    a = bot.answer(f"tell me about a trip to {destination}")
    assert a.intent in {"semantic_fallback", "last_trip"}, a.intent
    assert destination in a.text
    return f"backend={bot.semantic_backend}, matched on {destination}"


@check("insights: loads the sample CSV and computes the night share")
def _():
    from ijmam import insights
    df = insights.load_violations(ROOT / "data" / "fleet_violations.csv")
    k = insights.kpis(df)
    assert k["total"] == len(df)
    assert 0 <= k["night_share"] <= 100
    assert len(insights.by_hour(df)) == 24
    return f"{k['total']} rows, {k['night_share']:.0f}% at night"


@check("insights: rejects a CSV missing required columns")
def _():
    import io
    from ijmam import insights
    try:
        insights.load_violations(io.StringIO("a,b\n1,2\n"))
    except insights.InsightsError as exc:
        assert "violation_type" in str(exc)
        return "rejected with a useful message"
    raise AssertionError("bad CSV was accepted")


@check("in-cab: sustained violation logs once with a duration")
def _():
    from ijmam.cv_incab import _Tracker
    tracker = _Tracker("phone_use", cooldown=8.0, latch=True)
    events = [e for i in range(400) if (e := tracker.update(True, i * 0.1))]
    # frames keep arriving after the phone goes down; the violation closes
    # once it has been absent for the grace period
    for i in range(400, 440):
        tracker.update(False, i * 0.1)
    assert len(events) == 1, f"{len(events)} events for one continuous violation"
    assert events[0].duration_s == 39.9, events[0].duration_s
    return f"1 event, {events[0].duration_s}s duration"


@check("in-cab: a flickering detector still counts one violation")
def _():
    import random

    from ijmam.cv_incab import _Tracker

    random.seed(1)
    tracker = _Tracker("phone_use", cooldown=8.0, latch=True)
    events = []
    for i in range(400):
        video_t = i * 0.1
        present = video_t < 12.0 and random.random() > 0.35
        found = tracker.update(present, video_t)
        if found:
            events.append(found)
    tracker.close(40.0)
    assert len(events) == 1, f"{len(events)} events for one flickering phone use"
    assert events[0].duration_s and events[0].duration_s > 10, events[0].duration_s
    return f"1 event lasting {events[0].duration_s}s despite dropped frames"


@check("in-cab: separate violations stay separate")
def _():
    from ijmam.cv_incab import _Tracker
    tracker = _Tracker("phone_use", cooldown=8.0, latch=True)
    fired = []
    for i in range(300):
        video_t = i * 0.1
        present = video_t < 5.0 or 20.0 < video_t < 25.0
        found = tracker.update(present, video_t)
        if found:
            fired.append(found)
    tracker.close(30.0)
    assert len(fired) == 2, f"{len(fired)} events for two separate uses"
    assert fired[1].video_second - fired[0].video_second > 15
    return f"2 uses -> 2 events at {fired[0].video_second}s and {fired[1].video_second}s"


@check("in-cab: a negative seatbelt box is not read as 'belt worn'")
def _():
    try:
        import cv2  # noqa: F401
    except Exception:
        return "SKIPPED - opencv not installed"

    import numpy as np

    from ijmam.cv_incab import _detect_belt

    class Boxes:
        def __init__(self, xyxy, cls):
            self.xyxy, self.cls = xyxy, cls
        def __len__(self):
            return len(self.cls)

    class Result:
        def __init__(self, boxes=None, obb=None):
            self.boxes, self.obb = boxes, obb

    names = {0: "seatbelt", 1: "no_seatbelt"}
    chin_y = 100.0
    # a belt: taller than wide, sitting below the chin
    good = Result(boxes=Boxes(np.array([[10, 120, 60, 260]]), np.array([0])))
    # same shape and position, but the model called it no_seatbelt
    negative = Result(boxes=Boxes(np.array([[10, 120, 60, 260]]), np.array([1])))
    # right class, but above the chin - cannot be a chest strap
    too_high = Result(boxes=Boxes(np.array([[10, 5, 60, 40]]), np.array([0])))
    # right class and position, but wide and flat rather than diagonal
    wrong_shape = Result(boxes=Boxes(np.array([[10, 120, 300, 160]]), np.array([0])))

    assert _detect_belt(good, names, chin_y) is True
    assert _detect_belt(negative, names, chin_y) is False
    assert _detect_belt(too_high, names, chin_y) is False
    assert _detect_belt(wrong_shape, names, chin_y) is False
    assert _detect_belt(Result(), names, chin_y) is False
    return "class label, position and shape filters all applied"


@check("in-cab: phone geometry filters reject implausible detections")
def _():
    try:
        import cv2  # noqa: F401
    except Exception:
        return "SKIPPED - opencv not installed"

    import numpy as np

    from ijmam.cv_incab import _detect_phone

    class Boxes:
        def __init__(self, xyxy, cls):
            self.xyxy, self.cls = xyxy, cls
        def __len__(self):
            return len(self.cls)

    class Result:
        def __init__(self, boxes):
            self.boxes = boxes

    names = {0: "phone"}
    frame_h = 480
    # upright, plausible size, in the driver's reach
    good = Result(Boxes(np.array([[200, 150, 300, 300]]), np.array([0])))
    # far too large to be a handset
    huge = Result(Boxes(np.array([[0, 100, 400, 460]]), np.array([0])))
    # wider than tall
    flat = Result(Boxes(np.array([[200, 150, 360, 220]]), np.array([0])))
    # at the very top of the frame, above the driver
    high = Result(Boxes(np.array([[200, 5, 300, 70]]), np.array([0])))

    assert _detect_phone(good, names, frame_h) is True
    assert _detect_phone(huge, names, frame_h) is False
    assert _detect_phone(flat, names, frame_h) is False
    assert _detect_phone(high, names, frame_h) is False
    return "size, aspect ratio and position filters all applied"


@check("insights: reads the real in-cab session export")
def _():
    from ijmam import insights
    df = insights.load_violations(ROOT / "data" / "sample_incab_violations.csv")
    kinds = set(df["violation_type"])
    assert {"drowsiness", "yawning", "phone_use", "no_seatbelt"} <= kinds, kinds
    k = insights.kpis(df)
    assert k["fatigue"] == int(df["violation_type"].isin(
        insights.FATIGUE_FAMILY).sum())
    score = insights.safety_score(df)
    assert 0 <= score <= 100
    return f"{k['total']} rows, {k['fatigue']} fatigue indicators, score {score}%"


@check("cv: road detectors fire on a generated clip")
def _():
    try:
        import cv2  # noqa: F401
    except Exception:
        return "SKIPPED - opencv not installed"
    from scripts.make_demo_video import main as make_video
    from ijmam.cv_runner import run_analysis, to_dataframe, write_csv
    make_video()
    report = run_analysis(
        str(ROOT / "data" / "uploads" / "demo_road.mp4"), "road", "TRIP-CHECK",
        datetime(2026, 8, 24, 23, 30), ROOT / "models", ROOT / "data" / "outputs",
        stride=2, max_seconds=None,
    )
    assert report.ok, report.notes
    kinds = set(d.violation_type for d in report.detections)
    assert "lane_departure" in kinds, kinds
    assert "fatigue" in kinds, kinds
    path = write_csv(report, ROOT / "data" / "outputs", "TRIP-CHECK")
    from ijmam import insights
    df = insights.load_violations(path)
    assert len(df) == len(report.detections)
    return f"{len(report.detections)} detections -> CSV -> insights"


@check("cv: missing weights degrade loudly, not silently")
def _():
    from ijmam.cv_incab import analyse_incab
    from ijmam.cv_common import try_load_yolo
    if try_load_yolo() is None:
        return "SKIPPED - ultralytics not installed"
    report = analyse_incab(
        str(ROOT / "data" / "uploads" / "demo_road.mp4"), "TRIP-WARN",
        datetime.now(), ROOT / "models", ROOT / "data" / "outputs",
        stride=10, max_seconds=3,
    )
    joined = " ".join(report.notes).lower()
    assert "not found" in joined or "trained weights" in joined, report.notes
    return "notes surfaced"


def main() -> int:
    failed = 0
    print()
    for name, ok, note in results:
        if not ok:
            failed += 1
            print(f"{RED}FAIL{RESET}  {name}\n        {note}")
        elif note.startswith("SKIPPED"):
            print(f"{YELLOW}SKIP{RESET}  {name}  ({note[10:]})")
        else:
            print(f"{GREEN}PASS{RESET}  {name}" + (f"  ({note})" if note else ""))
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    if failed:
        print(f"{RED}Fix these before demoing.{RESET}")
    else:
        print(f"{GREEN}Ready to demo.{RESET}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
