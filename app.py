"""Ijmam dashboard. Run with: python app.py"""

from __future__ import annotations

import os
import sys

if sys.version_info < (3, 10):
    raise SystemExit(
        f"Ijmam needs Python 3.10 or newer — you are on "
        f"{sys.version_info.major}.{sys.version_info.minor}.\n"
        f"  py -3.12 -m venv .venv\n"
        f"  .\\.venv\\Scripts\\Activate.ps1\n"
        f"  pip install -r requirements.txt"
    )

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from nicegui import app, run, ui

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from ijmam import brand, insights, trip  # noqa: E402
from ijmam import cv_incab  # noqa: E402
from ijmam.cv_runner import run_analysis, summarise, to_dataframe, write_csv  # noqa: E402
from ijmam.manager_bot import ManagerBot  # noqa: E402
from ijmam.mapping import build_map, show_map  # noqa: E402
from ijmam.policy_bot import PolicyBot  # noqa: E402

DATA = ROOT / "data"
UPLOADS = DATA / "uploads"
OUTPUTS = DATA / "outputs"
MODELS = ROOT / "models"
for d in (UPLOADS, OUTPUTS, MODELS):
    d.mkdir(parents=True, exist_ok=True)

app.add_static_files("/media", str(OUTPUTS))

POLICY_BOT = PolicyBot(DATA / "company_policy.txt")
MANAGER_BOT = ManagerBot(DATA / "synthetic_trips.json")

MAX_UPLOAD_MB = 500
VIDEO_TYPES = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm"}

DEPARTURE_CHOICES = {
    "now": "Leaving now",
    "05:00": "Early morning (05:00)",
    "08:00": "Morning (08:00)",
    "14:00": "Afternoon (14:00)",
    "18:00": "Evening (18:00)",
    "22:00": "Night (22:00)",
}


NAME_ATTRS = ("name", "file_name", "filename", "fileName", "names", "file_names")
DATA_ATTRS = ("content", "file", "data", "contents", "files", "body")


def _upload_name(event, fallback: str = "upload") -> str:
    """The uploaded filename, whichever attribute this NiceGUI version uses."""
    for attr in NAME_ATTRS:
        value = getattr(event, attr, None)
        if isinstance(value, (list, tuple)) and value:
            value = value[0]
        if isinstance(value, str) and value:
            return value
    for attr in DATA_ATTRS:
        holder = getattr(event, attr, None)
        if isinstance(holder, (list, tuple)) and holder:
            holder = holder[0]
        name = getattr(holder, "name", None)
        if isinstance(name, str) and name:
            return name
    return fallback


def _upload_bytes(event) -> bytes:
    """
    The uploaded file's bytes.

    NiceGUI has moved this between attributes across versions, so rather than
    betting on one, look for anything readable and fall back to scanning the
    event. If nothing works the error lists what the object actually has, so
    the next fix takes one look instead of three rounds.
    """
    candidates = [getattr(event, attr, None) for attr in DATA_ATTRS] + [event]
    for candidate in candidates:
        if isinstance(candidate, (list, tuple)) and candidate:
            candidate = candidate[0]
        if isinstance(candidate, (bytes, bytearray)):
            return bytes(candidate)
        if hasattr(candidate, "read"):
            try:
                candidate.seek(0)
            except Exception:
                pass
            data = candidate.read()
            if data:
                return data if isinstance(data, bytes) else bytes(data)

    for attr in dir(event):
        if attr.startswith("_"):
            continue
        value = getattr(event, attr, None)
        if isinstance(value, (bytes, bytearray)) and value:
            return bytes(value)
        if hasattr(value, "read"):
            try:
                data = value.read()
                if data:
                    return data if isinstance(data, bytes) else bytes(data)
            except Exception:
                continue

    available = ", ".join(a for a in dir(event) if not a.startswith("_"))
    raise AttributeError(
        f"could not find the file contents on this upload event. "
        f"It has: {available}"
    )


def _save_upload(event, folder: Path, fallback: str) -> tuple[Path, str]:
    original = _upload_name(event, fallback)
    destination = folder / _safe_name(original)
    destination.write_bytes(_upload_bytes(event))
    return destination, original


def _safe_name(name: str) -> str:
    """Strip anything a filesystem will refuse, keeping the extension."""
    cleaned = "".join(c for c in Path(name).name if c.isalnum() or c in " ._-").strip()
    return cleaned or "upload"


def _folder_hint() -> None:
    """Show the uploads folder as a short relative path, full path on hover."""
    try:
        shown = UPLOADS.relative_to(ROOT)
    except ValueError:
        shown = UPLOADS
    label = ui.label(str(shown)).classes("ijmam-mono").style(
        f"color:{brand.AMBER}; font-size:12px; background:{brand.PANEL_RECESSED};"
        f"padding:6px 10px; border-radius:6px; margin:6px 0 12px 0; display:inline-block;"
    )
    label.tooltip(str(UPLOADS))


def _folder_options(suffixes: set[str]) -> dict[str, str]:
    """Files sitting in the uploads folder, newest first, as {path: label}."""
    files = sorted(
        (f for f in UPLOADS.iterdir() if f.is_file() and f.suffix.lower() in suffixes),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    return {str(f): f"{f.name}  ({f.stat().st_size / 1e6:.1f} MB)" for f in files}


def _video_options() -> dict[str, str]:
    return _folder_options(VIDEO_TYPES)


def _data_options() -> dict[str, str]:
    return _folder_options({".csv", ".xlsx", ".xls", ".xlsm"})


def _latest_upload(suffixes: set[str]) -> Path | None:
    files = [f for f in UPLOADS.iterdir()
             if f.is_file() and f.suffix.lower() in suffixes]
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def resolve_departure(choice: str) -> datetime:
    now = datetime.now().replace(second=0, microsecond=0)
    if choice == "now":
        return now
    hour, minute = (int(x) for x in choice.split(":"))
    when = now.replace(hour=hour, minute=minute)
    return when + timedelta(days=1) if when < now else when


@ui.page("/")
def main_page():
    ui.page_title("Ijmam — Fleet Safety")
    ui.add_head_html(brand.HEAD_HTML)
    brand.apply_colors()
    brand.header()

    state: dict = {"video": None, "report": None, "csv": None, "violations": None}

    with ui.column().classes("w-full items-center").style(
        f"background:{brand.NAVY}; padding:26px 0 70px 0; min-height:100vh;"
    ):
        with ui.column().style("width:100%; max-width:1180px; padding:0 24px;"):
            with ui.tabs().classes("w-full").props("no-caps") as tabs:
                tab_plan = ui.tab("Plan a trip")
                tab_camera = ui.tab("Check footage")
                tab_insights = ui.tab("Insights")
                tab_ask = ui.tab("Ask Ijmam")

            with ui.tab_panels(tabs, value=tab_plan).classes("w-full").style(
                "background:transparent;"
            ):
                with ui.tab_panel(tab_plan):
                    _plan_tab()
                with ui.tab_panel(tab_camera):
                    _camera_tab(state, tabs, tab_insights)
                with ui.tab_panel(tab_insights):
                    _insights_tab(state)
                with ui.tab_panel(tab_ask):
                    _ask_tab()


# --------------------------------------------------------------------------
# Plan a trip
# --------------------------------------------------------------------------
def _plan_tab() -> None:
    with ui.card().classes("ijmam-card w-full").style("padding:24px;"):
        brand.section_title("Plan a trip", "Where are you driving?")

        cities = trip.cities()
        with ui.row().classes("gap-4 w-full items-end"):
            origin = ui.select(cities, value="Jeddah", label="From").classes("w-40")
            destination = ui.select(cities, value="Tabuk", label="To").classes("w-40")
            duration = ui.number("Hours on the road", value=10, min=1, max=24,
                                 step=0.5).classes("w-44")
            drivers = ui.number("Drivers", value=1, min=1, max=5).classes("w-28")
            leaving = ui.select(DEPARTURE_CHOICES, value="18:00",
                                label="Leaving").classes("w-52")

        with ui.expansion("Route options").classes("w-full").style("margin-top:6px;"):
            ors_key = ui.input(
                "OpenRouteService API key",
                placeholder="Leave blank for a straight-line preview",
            ).props("type=password").classes("w-full")

        results = ui.column().classes("w-full").style("margin-top:18px;")

        async def compute():
            results.clear()
            if origin.value == destination.value:
                with results:
                    brand.note_line("Pick two different cities.", brand.BAD)
                return
            with results:
                brand.note_line("Working out the route…")

            plan = await run.io_bound(
                trip.plan_trip, origin.value, destination.value, float(duration.value),
                int(drivers.value), ors_key.value or None, resolve_departure(leaving.value),
            )
            results.clear()
            with results:
                _render_plan(plan)

        ui.button("Plan the trip", on_click=compute).props("color=primary unelevated").style(
            f"margin-top:16px; font-weight:700; color:{brand.NAVY};"
        )


def _render_plan(plan) -> None:
    sched = plan.schedule
    _verdict(plan)

    with ui.row().classes("gap-4 w-full").style("margin:16px 0;"):
        brand.kpi_card(
            "Total trip time", f"{sched.total_hours:g} h", brand.INK,
            sub=f"{plan.duration_hours:g} h driving + {sched.rest_minutes} min resting",
        )
        brand.kpi_card(
            "Arriving", f"{plan.arrival:%H:%M}", brand.INK,
            sub=f"leaving {plan.departure:%H:%M}",
        )
        brand.kpi_card(
            "Stops along the way", str(len(sched.stops)), brand.AMBER,
            sub=f"{plan.breaks} rest break(s), {plan.swaps} driver swap(s)",
        )
        brand.kpi_card(
            "Driving after dark", f"{sched.night_hours:g} h",
            brand.BAD if sched.night_hours > 2 else brand.GOOD,
            sub="between 23:00 and 05:00",
        )

    if sched.stops:
        ui.html(brand.build_timeline_html(plan.duration_hours, plan.timeline_points),
                sanitize=False).classes("w-full")

    with ui.row().classes("w-full gap-6 items-start no-wrap").style("margin-top:14px;"):
        with ui.column().style("flex:0 0 340px;"):
            ui.label("Where to stop").classes("ijmam-heading").style(
                f"font-size:15px; font-weight:600; color:{brand.INK}; margin-bottom:8px;"
            )
            if not sched.stops:
                brand.note_line("Short enough to drive in one go.", brand.GOOD)

            matches = [m for _, m in plan.matched]
            for i, (stop, match) in enumerate(zip(plan.stops, matches), start=1):
                kind = "Swap drivers" if stop.type == "driver_swap" else "Rest"
                with ui.row().classes("items-start w-full gap-3").style(
                    f"padding:9px 0; border-bottom:1px solid {brand.PANEL_LINE};"
                ):
                    ui.label(str(i)).style(
                        f"background:{brand.AMBER}; color:{brand.NAVY}; min-width:22px;"
                        f"height:22px; border-radius:50%; text-align:center;"
                        f"font-weight:700; font-size:12px; line-height:22px;"
                    )
                    with ui.column().classes("gap-0 flex-1"):
                        ui.label(match["name"] if match else f"{stop.hour_mark:g} h in").style(
                            f"color:{brand.INK}; font-size:13px;"
                        )
                        ui.label(f"Around {stop.clock:%H:%M} · {kind} for {stop.minutes} min").style(
                            f"color:{brand.MUTED}; font-size:11.5px;"
                        )
                    if stop.night:
                        brand.chip("after dark", "bad")

            if not plan.used_real_routing:
                brand.note_line(
                    "The line on the map is a straight-line preview. Add a routing key "
                    "under Route options for the real road path.", brand.MUTED,
                )

        with ui.column().style("flex:1;"):
            show_map(
                build_map(
                    plan.origin_coords, plan.destination_coords, plan.route_coords,
                    plan.origin, plan.destination, stops=trip.stop_markers(plan),
                )
            )

    with ui.expansion("Which rule produced each stop").classes("w-full").style(
        "margin-top:14px;"
    ):
        for i, stop in enumerate(plan.stops, start=1):
            brand.note_line(f"{i}. {stop.clock:%H:%M} — {stop.rule}")


def _verdict(plan) -> None:
    sched = plan.schedule
    blocking = [w for w in sched.warnings if w.startswith("⛔")]
    colour = brand.BAD if blocking else brand.GOOD

    with ui.card().classes("ijmam-dark-card w-full").style(
        f"padding:18px; border-color:{colour};"
    ):
        if blocking:
            ui.label("This trip is not allowed as planned").classes("ijmam-heading").style(
                f"color:{brand.BAD}; font-size:17px; font-weight:700;"
            )
            for warning in blocking:
                brand.note_line(warning.replace("⛔ ", ""), brand.INK)
        else:
            ui.label("This trip fits the company driving rules").classes(
                "ijmam-heading"
            ).style(f"color:{brand.GOOD}; font-size:17px; font-weight:700;")
            brand.note_line(
                f"Longest stretch behind the wheel is {plan.driving_between_stops:g} h, "
                f"and {sched.per_driver_hours:g} h per driver overall.", brand.INK,
            )

        for warning in sched.warnings:
            if not warning.startswith("⛔"):
                brand.note_line(warning.replace("⚠ ", "").replace("🌙 ", ""), brand.WARN)
        if plan.advice:
            brand.note_line(plan.advice, brand.AMBER)


# --------------------------------------------------------------------------
# Check footage
# --------------------------------------------------------------------------
def _camera_tab(state: dict, tabs, tab_insights) -> None:
    with ui.card().classes("ijmam-card w-full").style("padding:24px;"):
        brand.section_title("Check footage", "Upload a video and let the models watch it")
        brand.note_line(
            "In-cab footage is checked for phone use, seatbelts, drowsiness and yawning. "
            "Road-facing footage is checked for drifting out of lane, weaving and "
            "following too closely."
        )

        with ui.row().classes("gap-4 w-full items-end").style("margin-top:14px;"):
            camera = ui.select(
                {"in_cab": "Camera facing the driver", "road": "Camera facing the road"},
                value="in_cab", label="Which camera",
            ).classes("w-64")
            trip_id = ui.input("Trip ID", value="TRIP-001").classes("w-40")

        brand.note_line(
            "Put your video files in this folder inside the app, then press Refresh.",
            brand.MUTED,
        )
        _folder_hint()

        with ui.row().classes("w-full gap-3 items-end"):
            video_choice = ui.select(
                _video_options(), label="Video file"
            ).classes("flex-1")
            ui.button("Refresh", on_click=lambda: _refresh_video_choices()).props(
                "outline color=primary"
            )

        def _refresh_video_choices():
            options = _video_options()
            video_choice.options = options
            if options and video_choice.value not in options:
                video_choice.value = list(options)[0]
            video_choice.update()

        def on_choice(_=None):
            if video_choice.value:
                state["video"] = Path(video_choice.value)
                selected.text = f"Ready to check: {Path(video_choice.value).name}"
                selected.style(f"color:{brand.GOOD};")

        video_choice.on_value_change(on_choice)

        selected = ui.label("No video chosen yet.").style(
            f"color:{brand.MUTED}; font-size:12.5px; margin-top:10px;"
        )
        status = ui.column().classes("w-full").style("margin-top:6px;")

        def on_upload(e):
            try:
                destination, original = _save_upload(e, UPLOADS, "video.mp4")
                if destination.suffix.lower() not in VIDEO_TYPES:
                    destination.unlink(missing_ok=True)
                    selected.text = f"{original} is not a video. Use MP4, MOV, AVI or MKV."
                    selected.style(f"color:{brand.BAD};")
                    return
                state["video"] = destination
                _refresh_video_choices()
                selected.text = (
                    f"Ready to check: {original} "
                    f"({destination.stat().st_size / 1e6:.1f} MB)"
                )
                selected.style(f"color:{brand.GOOD};")
            except Exception as exc:
                selected.text = f"Could not read that file: {type(exc).__name__}: {exc}"
                selected.style(f"color:{brand.BAD};")

        with ui.expansion("Or drag a video into the browser").classes("w-full").style(
            "margin-top:10px;"
        ):
            ui.upload(
                on_upload=on_upload,
                auto_upload=True,
                max_file_size=MAX_UPLOAD_MB * 1024 * 1024,
                label="Drop a video here",
            ).classes("w-full")

        with ui.expansion("Detector settings").classes("w-full").style("margin-top:10px;"):
            brand.note_line(
                "Defaults match how the models were trained. Only change these if you "
                "know why you are changing them."
            )
            with ui.row().classes("gap-4 w-full items-end").style("margin-top:8px;"):
                confidence = ui.number("Phone / vehicle confidence",
                                       value=cv_incab.PHONE_CONF, min=0.05,
                                       max=0.95, step=0.05).classes("w-52")
                belt_conf = ui.number("Seatbelt confidence", value=cv_incab.BELT_CONF,
                                      min=0.05, max=0.95, step=0.05).classes("w-44")
                stride = ui.number("Check every Nth frame", value=3, min=1,
                                   max=15).classes("w-48")
                cap_seconds = ui.number("Minutes to check", value=1, min=0.5, max=30,
                                        step=0.5).classes("w-40")
            start_time = ui.input(
                "When the footage was recorded",
                value=datetime.now().strftime("%Y-%m-%dT%H:%M"),
            ).classes("w-72")

        results = ui.column().classes("w-full")

        async def analyse():
            video = state.get("video") or _latest_upload(VIDEO_TYPES)
            if not video or not Path(video).exists():
                ui.notify("Choose a video first.", color="warning")
                return
            state["video"] = video

            results.clear()
            status.clear()
            with status:
                brand.note_line("Watching the footage — this takes about as long as the clip.")
                bar = ui.linear_progress(value=0.0, show_value=False).classes("w-full").props(
                    'color="orange-6" track-color="grey-9"'
                )
                counter = ui.label("nothing found yet").style(
                    f"color:{brand.MUTED}; font-size:12px;"
                )

            progress_state = {"pct": 0.0, "n": 0}
            timer = ui.timer(
                0.4,
                lambda: (
                    setattr(bar, "value", progress_state["pct"]),
                    setattr(counter, "text", f"{progress_state['n']} found so far"),
                ),
            )

            try:
                recorded_at = datetime.fromisoformat(start_time.value.strip().replace(" ", "T"))
            except ValueError:
                recorded_at = datetime.now()

            try:
                report = await run.io_bound(
                    run_analysis, str(video), camera.value,
                    trip_id.value.strip() or "TRIP-001", recorded_at, MODELS, OUTPUTS,
                    float(confidence.value), int(stride.value),
                    float(cap_seconds.value) * 60, None, float(belt_conf.value),
                )
            except Exception as exc:
                timer.deactivate()
                status.clear()
                with status:
                    brand.note_line(
                        f"Something went wrong while checking the footage: "
                        f"{type(exc).__name__}: {exc}", brand.BAD,
                    )
                return
            finally:
                timer.deactivate()
            bar.value = 1.0

            state["report"] = report
            if report.ok:
                state["csv"] = write_csv(report, OUTPUTS, trip_id.value.strip() or "TRIP-001")
            results.clear()
            with results:
                _render_report(report, state, tabs, tab_insights)

        ui.button("Check the footage", on_click=analyse).props(
            "color=primary unelevated"
        ).style(f"margin-top:14px; font-weight:700; color:{brand.NAVY};")


def _render_report(report, state, tabs, tab_insights) -> None:
    if not report.ok:
        with ui.card().classes("ijmam-dark-card w-full").style("padding:18px; margin-top:16px;"):
            ui.label("Could not check this footage").classes("ijmam-heading").style(
                f"color:{brand.BAD}; font-size:16px; font-weight:700;"
            )
            for note in report.notes:
                brand.note_line(note)
        return

    stats = summarise(report)
    ui.element("div").style("height:18px;")

    with ui.row().classes("gap-4 w-full"):
        brand.kpi_card("Problems found", str(stats["total"]),
                       brand.BAD if stats["total"] else brand.GOOD)
        if stats.get("safety_score") is not None:
            score = stats["safety_score"]
            brand.kpi_card(
                "Safety score", f"{score}%",
                brand.GOOD if score >= 80 else (brand.WARN if score >= 50 else brand.BAD),
            )
        brand.kpi_card("Footage checked", f"{stats['video_seconds']:g} s", brand.INK)

    warnings = [n for n in report.notes if "not found" in n.lower() or "disabled" in n.lower()
                or n.startswith("⚠")]
    if warnings:
        with ui.card().classes("ijmam-dark-card w-full").style(
            f"padding:16px; margin-top:16px; border-color:{brand.WARN};"
        ):
            ui.label("Read this before trusting the numbers").classes("ijmam-heading").style(
                f"color:{brand.WARN}; font-size:14px; font-weight:700; margin-bottom:6px;"
            )
            for warning in warnings:
                brand.note_line(warning, brand.INK)

    if report.annotated_video:
        with ui.card().classes("ijmam-card w-full").style("padding:18px; margin-top:16px;"):
            brand.section_title("Playback", "The footage with the detections drawn on")
            ui.video(f"/media/{report.annotated_video.name}").classes("w-full").style(
                "max-height:460px; border-radius:12px;"
            )

    if report.evidence_frames:
        with ui.card().classes("ijmam-card w-full").style("padding:18px; margin-top:16px;"):
            brand.section_title("Evidence", "The exact moment of each problem")
            with ui.row().classes("gap-3 flex-wrap"):
                for i, frame in enumerate(report.evidence_frames[:12]):
                    detection = report.detections[i] if i < len(report.detections) else None
                    with ui.column().classes("gap-1"):
                        ui.image(f"/media/evidence/{frame.name}").classes("evidence-img")
                        if detection:
                            ui.label(
                                f"{detection.video_second:g}s · "
                                f"{insights.PRETTY.get(detection.violation_type, detection.violation_type)}"
                            ).style(f"color:{brand.MUTED}; font-size:11px;")

    df = to_dataframe(report)
    with ui.card().classes("ijmam-card w-full").style("padding:18px; margin-top:16px;"):
        brand.section_title("Results", "What was found")
        if df.empty:
            brand.note_line(
                "Nothing was flagged in the part of the video that was checked.", brand.GOOD
            )
        else:
            shown = df[["video_second", "violation_type", "note"]].copy()
            shown.columns = ["At (seconds)", "Problem", "Detail"]
            shown["Problem"] = shown["Problem"].map(
                lambda t: insights.PRETTY.get(t, t.replace("_", " ").title())
            )
            ui.table.from_pandas(shown).classes("w-full").props("dense flat")

        with ui.row().classes("gap-3").style("margin-top:14px;"):
            if state.get("csv"):
                ui.button("Download the results",
                          on_click=lambda: _download(state["csv"])).props("outline color=primary")

            def send_to_insights():
                if not state.get("csv"):
                    return
                try:
                    state["violations"] = insights.load_violations(state["csv"])
                except insights.InsightsError as exc:
                    ui.notify(str(exc), color="negative", timeout=8000)
                    return
                MANAGER_BOT.attach_cv_violations(state["violations"])
                state["insights_refresh"]()
                tabs.set_value(tab_insights)

            ui.button("See the insights →", on_click=send_to_insights).props(
                "color=primary unelevated"
            ).style(f"font-weight:700; color:{brand.NAVY};")


def _download(path: Path) -> None:
    try:
        ui.download.file(str(path))
    except AttributeError:
        ui.download(str(path))


# --------------------------------------------------------------------------
# Insights
# --------------------------------------------------------------------------
def _insights_tab(state: dict) -> None:
    with ui.card().classes("ijmam-card w-full").style("padding:24px;"):
        brand.section_title("Insights", "What the footage says about the fleet")

        body = ui.column().classes("w-full").style("margin-top:16px;")

        def refresh():
            body.clear()
            with body:
                if state.get("violations") is None:
                    brand.note_line(
                        "Load a file below, or check some footage first.", brand.MUTED
                    )
                    return
                _render_insights(state["violations"])

        state["insights_refresh"] = refresh

        def on_upload(e):
            try:
                destination, original = _save_upload(e, UPLOADS, "data.csv")
                state["violations"] = insights.load_violations(destination)
            except insights.InsightsError as exc:
                ui.notify(str(exc), color="negative", timeout=10000)
                return
            except Exception as exc:
                ui.notify(f"Could not read that file: {exc}", color="negative", timeout=12000)
                return
            original = destination.name
            MANAGER_BOT.attach_cv_violations(state["violations"])
            refresh()
            ui.notify(
                f"Loaded {len(state['violations'])} rows from {original}", color="positive"
            )

        def load(filename: str):
            state["violations"] = insights.load_violations(DATA / filename)
            refresh()

        with ui.row().classes("w-full gap-3 items-center"):
            ui.button("Open a real in-cab session",
                      on_click=lambda: load("sample_incab_violations.csv")).props(
                "color=primary unelevated"
            ).style(f"font-weight:700; color:{brand.NAVY};")
            ui.button("Open a week of fleet data",
                      on_click=lambda: load("fleet_violations.csv")).props("outline color=primary")

        with ui.expansion("Or use your own file").classes("w-full").style("margin-top:12px;"):
            brand.note_line(
                "Needs three columns: trip_id, violation_type, timestamp. CSV or Excel "
                "both work. Drop files in the folder below and press Refresh, or drag "
                "one into the box."
            )
            _folder_hint()

            with ui.row().classes("w-full gap-3 items-end"):
                data_choice = ui.select(_data_options(), label="Data file").classes("flex-1")

                def refresh_choices():
                    options = _data_options()
                    data_choice.options = options
                    if options and data_choice.value not in options:
                        data_choice.value = list(options)[0]
                    data_choice.update()

                ui.button("Refresh", on_click=refresh_choices).props("outline color=primary")

                def open_choice():
                    if not data_choice.value:
                        ui.notify("No file selected.", color="warning")
                        return
                    try:
                        state["violations"] = insights.load_violations(data_choice.value)
                    except Exception as exc:
                        ui.notify(str(exc), color="negative", timeout=12000)
                        return
                    MANAGER_BOT.attach_cv_violations(state["violations"])
                    refresh()
                    ui.notify(f"Loaded {len(state['violations'])} rows", color="positive")

                ui.button("Open it", on_click=open_choice).props(
                    "color=primary unelevated"
                ).style(f"font-weight:700; color:{brand.NAVY};")

            ui.upload(on_upload=on_upload, auto_upload=True,
                      label="Or drop a file here").classes("w-full").style("margin-top:10px;")

        refresh()


def _render_insights(df: pd.DataFrame) -> None:
    k = insights.kpis(df)
    score = insights.safety_score(df)

    with ui.card().classes("ijmam-dark-card w-full").style("padding:18px;"):
        ui.label(insights.headline(df)).classes("ijmam-heading").style(
            f"color:{brand.INK}; font-size:16px; font-weight:600; line-height:1.6;"
        )

    with ui.row().classes("gap-4 w-full").style("margin-top:16px;"):
        brand.kpi_card("Problems found", str(k["total"]), brand.BAD,
                       sub=f"across {k['trips']} trip(s)")
        brand.kpi_card("Signs of tiredness", str(k["fatigue"]), brand.WARN,
                       sub="drowsiness, yawning, weaving")
        brand.kpi_card("Happened after dark", f"{k['night_share']:.0f}%", brand.AMBER,
                       sub="between 23:00 and 05:00")
        brand.kpi_card(
            "Safety score", f"{score}%",
            brand.GOOD if score >= 80 else (brand.WARN if score >= 50 else brand.BAD),
        )

    with ui.card().classes("ijmam-card w-full").style("padding:20px; margin-top:16px;"):
        brand.section_title("Timing", "What time of day problems happen")
        hours = insights.by_hour(df)
        ui.echart({
            "backgroundColor": "transparent",
            "grid": {"left": 40, "right": 16, "top": 20, "bottom": 34},
            "xAxis": {
                "type": "category",
                "data": [f"{h:02d}" for h in hours["hour"]],
                "axisLabel": {"color": brand.MUTED, "fontSize": 10},
                "axisLine": {"lineStyle": {"color": brand.PANEL_LINE}},
            },
            "yAxis": {
                "type": "value", "minInterval": 1,
                "axisLabel": {"color": brand.MUTED, "fontSize": 10},
                "splitLine": {"lineStyle": {"color": brand.PANEL_LINE}},
            },
            "series": [{
                "type": "bar",
                "data": [
                    {"value": int(c), "itemStyle": {
                        "color": brand.BAD if h in insights.NIGHT_HOURS else brand.AMBER_SOFT,
                        "borderRadius": [4, 4, 0, 0]}}
                    for h, c in zip(hours["hour"], hours["count"])
                ],
            }],
        }).classes("w-full").style("height:230px;")
        brand.note_line("Red bars are the night hours, 23:00 to 05:00.")

    with ui.card().classes("ijmam-card w-full").style("padding:20px; margin-top:16px;"):
        brand.section_title("Breakdown", "What kind of problems")
        types = insights.by_type(df)
        biggest = int(types["count"].max())
        for row in types.itertuples():
            with ui.row().classes("items-center w-full gap-3").style("padding:5px 0;"):
                ui.label(row.label).style(
                    f"color:{brand.INK}; font-size:13px; min-width:150px;"
                )
                ui.element("div").style(
                    f"height:14px; border-radius:7px; background:{brand.AMBER};"
                    f"width:{row.count / biggest * 55}%;"
                )
                ui.label(str(row.count)).classes("ijmam-mono").style(
                    f"color:{brand.MUTED}; font-size:12px;"
                )

    drivers = insights.by_driver(df)
    if not drivers.empty:
        with ui.card().classes("ijmam-card w-full").style("padding:20px; margin-top:16px;"):
            brand.section_title("Drivers", "Who needs attention first")
            table = drivers.copy()
            table.columns = ["Driver", "Problems", "Signs of tiredness", "After dark"]
            ui.table.from_pandas(table).classes("w-full").props("dense flat")

    with ui.expansion("Trip by trip").classes("w-full").style("margin-top:14px;"):
        columns = ["trip_id"] + (["driver"] if "driver" in df.columns else []) + [
            "violations", "night", "worst_type"]
        table = insights.by_trip(df)[columns]
        table.columns = (["Trip"] + (["Driver"] if "driver" in df.columns else [])
                         + ["Problems", "After dark", "Most common"])
        ui.table.from_pandas(table).classes("w-full").props("dense flat")

    with ui.expansion("Every event").classes("w-full").style("margin-top:8px;"):
        rows = insights.table_rows(df)
        columns = [
            {"name": key, "label": key.replace("_", " ").title(), "field": key,
             "align": "left"}
            for key in rows[0]
        ] if rows else []
        ui.table(columns=columns, rows=rows, row_key="time").classes("w-full").props(
            "dense flat"
        )


# --------------------------------------------------------------------------
# Ask Ijmam
# --------------------------------------------------------------------------
def _ask_tab() -> None:
    with ui.row().classes("w-full gap-4 no-wrap items-stretch"):
        with ui.card().classes("ijmam-card").style("padding:22px; flex:1;"):
            brand.section_title("For drivers", "Company rules · قوانين الشركة")
            backend_note = (
                "Powered by Gemini over the full policy manual."
                if POLICY_BOT.backend.startswith("gemini")
                else "Running offline from the policy manual. Set GEMINI_API_KEY "
                     "for Gemini-phrased answers."
            )
            brand.note_line(
                "Answers come straight from the company policy manual, in Arabic or "
                "English. If it is not in the manual, it will say so. " + backend_note
            )
            _chat(_policy_reply, POLICY_BOT.suggested_questions()[:3]
                  + POLICY_BOT.suggested_questions(arabic=True)[:2])

        with ui.card().classes("ijmam-card").style("padding:22px; flex:1;"):
            brand.section_title("For managers", "The fleet")
            brand.note_line("Counts and rankings are worked out from the trip records.")
            _chat(_manager_reply, [
                "Who needs a shift change?",
                "Who are the top 3 violators?",
                "How many fatigue violations did Ahmed have?",
                "What happened on Tariq's last trip?",
            ])


def _policy_reply(question: str) -> tuple[str, str | None]:
    answer = POLICY_BOT.answer(question)
    return answer.text, answer.section


def _manager_reply(question: str) -> tuple[str, str | None]:
    answer = MANAGER_BOT.answer(question)
    return answer.text, None


def _chat(reply_fn, suggestions: list[str]) -> None:
    log = ui.column().classes("w-full gap-3").style(
        "margin-top:8px; min-height:170px; max-height:400px; overflow-y:auto;"
    )

    def arabic(text: str) -> bool:
        return any("\u0600" <= ch <= "\u06FF" for ch in text)

    def ask(question: str):
        question = question.strip()
        if not question:
            return
        with log:
            ui.label(question).classes("ijmam-rtl" if arabic(question) else "").style(
                f"color:{brand.INK}; font-size:13.5px; font-weight:600;"
            )
            text, source = reply_fn(question)
            with ui.card().classes("ijmam-dark-card w-full").style("padding:12px 14px;"):
                ui.markdown(text.replace("\n", "  \n")).classes(
                    "ijmam-rtl" if arabic(text) else ""
                ).style(f"color:{brand.INK}; font-size:13px;")
                if source:
                    ui.label(source).style(
                        f"color:{brand.MUTED}; font-size:10.5px; margin-top:6px;"
                    )
        try:
            log.scroll_to(percent=1.0)
        except Exception:
            pass

    with ui.row().classes("w-full no-wrap gap-2").style("margin-top:12px;"):
        box = ui.input(placeholder="Ask a question…").classes("flex-1").props("outlined dense")
        box.on("keydown.enter", lambda: (ask(box.value), box.set_value("")))
        ui.button("Ask", on_click=lambda: (ask(box.value), box.set_value(""))).props(
            "color=primary unelevated"
        ).style(f"font-weight:700; color:{brand.NAVY};")

    with ui.row().classes("gap-2 flex-wrap").style("margin-top:10px;"):
        for suggestion in suggestions:
            ui.button(suggestion, on_click=lambda s=suggestion: ask(s)).props(
                "flat dense no-caps"
            ).style(
                f"color:{brand.MUTED}; font-size:11.5px; border:1px solid {brand.PANEL_LINE};"
                f"border-radius:20px; padding:2px 12px;"
            )


if __name__ in {"__main__", "__mp_main__"}:
    # Hosts set PORT and expect the app on 0.0.0.0. Locally both default sanely.
    ui.run(
        title="Ijmam — Fleet Safety",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8080")),
        reload=False,
        show=False,
        dark=True,
        storage_secret=os.getenv("STORAGE_SECRET", "ijmam-local"),
    )
