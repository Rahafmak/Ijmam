"""
Ijmam - Fleet Safety Dashboard (NiceGUI edition)

Run with:   python ijmam_dashboard.py
Opens at:   http://localhost:8080

Why NiceGUI instead of Streamlit:
  - Free, open source (Apache 2.0), pure Python - no separate frontend build step.
  - Built on Quasar/Vue, so it looks like a real designed app out of the box
    (cards, proper typography, real theming) instead of the default Streamlit
    look every bootcamp project ends up with.
  - Fully themeable in a few lines (ui.colors + a small CSS block below), so
    the dashboard actually matches the Ijmam navy/amber brand from the deck.

This file is a drop-in replacement for dashboard_demo.py. All the actual
logic - routing, rest-stop scheduling, CV-result merging - is untouched and
imported exactly as before:
  - CV team          -> exports violations/average_speed into mock_trips.json's shape
  - Manager chatbot   -> reads the same mock_trips.json / dashboard CSV
  - This file         -> reads it all and renders the dashboard + maps
"""

import json
import tempfile
from pathlib import Path

import pandas as pd
import folium
from nicegui import ui, app, run

from routing import get_route
from rest_stops import compute_rest_schedule
from rest_stop_suggestions import get_curated_stops, match_stops_to_schedule, stop_coords
from merge_cv_results import import_cv_csv
from synthetic_adapter import load_synthetic_trips, CITY_COORDS

# ============================================================================
# BRAND / THEME  (v2 - full dark theme, matching the deck's actual identity
# instead of a light page with a dark header bolted on top)
# ============================================================================
NAVY = "#0A0E1A"           # page background - near-black, not mid-tone
PANEL = "#1A2338"          # card/panel surface - lifted noticeably off the page
PANEL_RECESSED = "#131A2B"  # inputs, table headers - between page and panel
PANEL_LINE = "#323D5C"     # borders on dark surfaces - brighter, more visible
AMBER = "#F2A93B"
AMBER_SOFT = "#C98A2E"     # muted amber for secondary accents on dark
AMBER_DEEP = AMBER_SOFT    # alias kept so existing call sites don't need touching
INK = "#EDEFF6"            # primary text - near-white, not literal black-on-white
MUTED = "#9AA3B8"          # secondary text - brightened for legibility on dark
GOOD = "#4FD1BE"
BAD = "#FF7A59"
PAGE_BG = NAVY
CARD_BG = PANEL
CARD_LINE = PANEL_LINE
NAVY_CARD = PANEL_RECESSED
NAVY_LINE = PANEL_LINE

app.colors(primary=AMBER, secondary=PANEL_LINE, positive=GOOD, negative=BAD, dark=NAVY)

BRAND_HEAD_HTML = f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,680&family=Inter:wght@400;500;600&family=IBM+Plex+Sans+Arabic:wght@500;600;700&display=swap" rel="stylesheet">
<style>
  body {{ font-family: 'Inter', -apple-system, sans-serif; background: {PAGE_BG}; }}

  .ijmam-heading {{ font-family: 'Fraunces', serif; font-optical-sizing: auto; color: {INK}; }}
  .ijmam-arabic {{ font-family: 'IBM Plex Sans Arabic', sans-serif; }}

  .ijmam-card {{ background: {CARD_BG}; border: 1px solid {CARD_LINE}; border-radius: 14px;
                 box-shadow: 0 2px 10px rgba(0,0,0,.35); }}
  .ijmam-dark-card {{ background: {NAVY_CARD}; border: 1px solid {NAVY_LINE}; border-radius: 14px; }}

  /* Every plain NiceGUI label defaults to near-black text - since the whole
     page is now dark, force light text everywhere unless a style overrides it. */
  .nicegui-content, .q-page, .q-card, .q-field__label, .q-field__native,
  label, .q-item__label {{ color: {INK}; }}
  .q-field__control {{ color: {INK} !important; }}
  .q-field__label {{ color: {MUTED} !important; }}
  .q-field__bottom {{ color: {MUTED} !important; }}
  ::placeholder {{ color: {MUTED}; opacity: .7; }}

  /* Fix: dropdown/select popup menus keep Quasar's default light background,
     but the global light-text override above made the options unreadable
     (near-white text on a near-white popup). Style the popup itself dark. */
  .q-menu {{ background: {PANEL} !important; border: 1px solid {PANEL_LINE}; }}
  .q-menu .q-item {{ color: {INK} !important; }}
  .q-menu .q-item:hover, .q-menu .q-item--active {{ background: {PANEL_RECESSED} !important; }}

  .q-tab {{ font-family: 'Inter', sans-serif; font-weight: 600; font-size: 12.5px;
            letter-spacing: .04em; text-transform: uppercase; color: {MUTED} !important;
            min-height: 40px; }}
  .q-tab--active {{ color: {AMBER} !important; }}
  .q-tabs__content {{ border-bottom: 1px solid {CARD_LINE}; }}
  .q-tab-panels {{ background: transparent !important; }}
  .q-tabs .q-tab__indicator {{ background: {AMBER} !important; height: 2px !important; }}

  .q-table {{ background: transparent; color: {INK}; }}
  /* The actual row/cell elements have Quasar's own white background with
     higher specificity than the outer .q-table rule above - that's why
     rows were still rendering white with barely-visible light text. Force
     the real elements dark, not just the wrapper. */
  .q-table__card {{ background: {PANEL} !important; }}
  .q-table thead tr, .q-table tbody tr {{ background: {PANEL} !important; }}
  .q-table thead th {{ font-family: 'Inter', sans-serif; font-weight: 600; font-size: 11px;
                        letter-spacing: .04em; text-transform: uppercase; color: {MUTED};
                        background: {PANEL_RECESSED} !important; }}
  .q-table tbody td {{ color: {INK} !important; background: {PANEL} !important;
                        border-color: {PANEL_LINE} !important; }}
  .q-table tbody tr:nth-child(even) td {{ background: {PANEL_RECESSED} !important; }}
  .q-table tbody tr:hover td {{ background: {PANEL_LINE} !important; }}

  .folium-frame {{ border-radius: 14px; overflow: hidden; border: 1px solid {CARD_LINE}; }}
  .status-chip-taken {{ background: {GOOD}22; color: {GOOD}; border-radius: 20px; padding: 3px 12px;
                         font-size: 12px; font-weight: 600; display:inline-block; }}
  .status-chip-skipped {{ background: {BAD}22; color: {BAD}; border-radius: 20px; padding: 3px 12px;
                           font-size: 12px; font-weight: 600; display:inline-block; }}

  /* ---- Signature element: the rest-stop timeline, restyled for dark ---- */
  .ijmam-timeline {{ position: relative; width: 100%; padding: 34px 6px 26px 6px; }}
  .ijmam-timeline-track {{ position: absolute; left: 6px; right: 6px; top: 50%;
                            height: 2px; background: {PANEL_LINE}; }}
  .ijmam-timeline-point {{ position: absolute; top: 50%; transform: translate(-50%, -50%);
                            width: 13px; height: 13px; border-radius: 50%;
                            border: 2px solid {PAGE_BG}; box-shadow: 0 0 0 1px {PANEL_LINE}; }}
  .ijmam-timeline-point.endpoint {{ background: {AMBER}; width: 11px; height: 11px; }}
  .ijmam-timeline-point.taken {{ background: {GOOD}; }}
  .ijmam-timeline-point.skipped {{ background: {BAD}; }}
  .ijmam-timeline-label {{ position: absolute; top: calc(50% - 30px); transform: translateX(-50%);
                            text-align: center; white-space: nowrap; font-size: 11px;
                            font-weight: 600; color: {INK}; }}
  .ijmam-timeline-sub {{ position: absolute; top: calc(50% + 14px); transform: translateX(-50%);
                          text-align: center; white-space: nowrap; font-size: 10px;
                          color: {MUTED}; }}
</style>
"""

DATA_DIR = Path(__file__).parent


# ============================================================================
# DATA LAYER
# ============================================================================
def load_trips():
    # Now reads from the team's synthetic_trips.json (the richer schema built
    # for RAG) through the adapter, instead of the old flat mock file.
    return load_synthetic_trips(DATA_DIR / "synthetic_trips.json")


state = {"trips": load_trips()}


def city_coords():
    # Static lookup, not derived from whichever trips happen to be loaded -
    # this is what was actually broken before: Tabuk/Jubail never showed up
    # because the old version only knew about cities present in mock_trips.json.
    return CITY_COORDS


def summary_dataframe() -> pd.DataFrame:
    rows = []
    for t in state["trips"]:
        total_stops = len(t["rest_points"])
        taken_stops = sum(1 for r in t["rest_points"] if r["taken"])
        compliance = round(taken_stops / total_stops * 100, 1) if total_stops else 0
        rows.append({
            "Trip ID": t["trip_id"],
            "Route": f"{t['origin']} \u2192 {t['destination']}",
            "Duration (hrs)": t["duration_hours"],
            "Drivers": t["num_drivers"],
            "Rest Compliance %": compliance,
            "Violations": len(t["violations"]),
            "Avg Speed (km/h)": t["average_speed"],
        })
    return pd.DataFrame(rows)


# ============================================================================
# UI HELPERS
# ============================================================================
def app_header():
    with ui.row().classes("w-full items-center justify-between no-wrap").style(
        f"background:{NAVY}; padding:18px 32px; margin:0; border-bottom: 2px solid {AMBER};"
    ):
        with ui.row().classes("items-center gap-3"):
            # Signature mark: a rest-stop on a route - a small line with a paused
            # dot, echoing the timeline component used throughout the app. This
            # ties the logo directly to what the product actually does, rather
            # than a generic abstract shape.
            ui.html(
                f"""
                <svg width="42" height="18" viewBox="0 0 42 18">
                    <line x1="3" y1="9" x2="39" y2="9" stroke="{NAVY_LINE}" stroke-width="2"/>
                    <circle cx="3" cy="9" r="3" fill="white"/>
                    <circle cx="21" cy="9" r="4.5" fill="{AMBER}"/>
                    <circle cx="39" cy="9" r="3" fill="white"/>
                </svg>
                """,
                sanitize=False,
            )
            with ui.column().classes("gap-0"):
                ui.label("IJMAM").classes("ijmam-heading").style(
                    "color:white; font-size:20px; font-weight:700; letter-spacing:3px; line-height:1.2;"
                )
                ui.label("FLEET SAFETY").style(
                    f"color:{AMBER}; font-size:10px; letter-spacing:2px; line-height:1.2; font-weight:600;"
                )
        ui.label("\u0625\u062c\u0645\u0627\u0645").classes("ijmam-arabic").style(
            f"color:{AMBER}; font-size:20px; font-weight:600; direction:rtl;"
        )


def kpi_card(label: str, value: str, accent: str = AMBER):
    with ui.card().tight().classes("ijmam-card").style("padding:16px 22px; min-width:190px; box-shadow:none;"):
        ui.label(label.upper()).style(
            f"font-size:10.5px; letter-spacing:1.2px; color:{MUTED}; font-weight:600;"
        )
        ui.label(value).classes("ijmam-heading").style(
            f"font-size:26px; font-weight:700; color:{accent}; margin-top:2px;"
        )


def section_title(kicker: str, title: str):
    ui.label(kicker.upper()).style(
        f"color:{AMBER_DEEP}; font-size:11px; font-weight:700; letter-spacing:1.5px;"
    )
    ui.label(title).classes("ijmam-heading").style(
        f"color:{INK}; font-size:21px; font-weight:700; margin-top:2px; margin-bottom:14px;"
    )


def build_map(origin_coords, dest_coords, route_coords, origin_label, dest_label, extra_markers=None):
    m = folium.Map(
        location=[
            (origin_coords["lat"] + dest_coords["lat"]) / 2,
            (origin_coords["lon"] + dest_coords["lon"]) / 2,
        ],
        zoom_start=6,
        tiles="CartoDB positron",
    )
    folium.Marker(
        [origin_coords["lat"], origin_coords["lon"]], popup=origin_label,
        icon=folium.Icon(color="green", icon="play"),
    ).add_to(m)
    folium.Marker(
        [dest_coords["lat"], dest_coords["lon"]], popup=dest_label,
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(m)
    folium.PolyLine(route_coords, color=NAVY, weight=4, opacity=0.85).add_to(m)
    for mk in (extra_markers or []):
        folium.Marker(
            [mk["lat"], mk["lon"]], popup=mk.get("popup", ""),
            icon=folium.Icon(color=mk.get("color", "blue"), icon=mk.get("icon", "info-sign")),
        ).add_to(m)
    return m


def show_map(m: folium.Map, height: int = 440):
    with ui.element("div").classes("folium-frame").style(f"width:100%; height:{height}px;"):
        ui.html(m._repr_html_(), sanitize=False).style("width:100%; height:100%; border:0;")


def build_timeline_html(duration_hours: float, points: list, height: int = 90) -> str:
    """
    The signature visual: a horizontal timeline like the one in the Ijmam deck
    (Depart -o----o----o- Arrive). `points` is a list of dicts:
      {"hour_mark": float, "label": str, "sub": str, "status": "taken"/"skipped"/None}
    hour_mark=0 and hour_mark=duration_hours are drawn as dark endpoint dots.
    """
    def pct(h):
        return max(2, min(98, (h / duration_hours) * 100)) if duration_hours else 50

    dots = []
    for p in points:
        left = pct(p["hour_mark"])
        cls = "endpoint" if p.get("endpoint") else (p.get("status") or "")
        dots.append(f'<div class="ijmam-timeline-point {cls}" style="left:{left}%;"></div>')
        dots.append(
            f'<div class="ijmam-timeline-label" style="left:{left}%;">{p["label"]}</div>'
        )
        if p.get("sub"):
            dots.append(
                f'<div class="ijmam-timeline-sub" style="left:{left}%;">{p["sub"]}</div>'
            )

    return (
        f'<div class="ijmam-timeline" style="height:{height}px;">'
        f'<div class="ijmam-timeline-track"></div>'
        + "".join(dots) +
        f'</div>'
    )


def status_chip(taken: bool):
    if taken:
        ui.html('<span class="status-chip-taken">&#10003; Taken</span>', sanitize=False)
    else:
        ui.html('<span class="status-chip-skipped">&#10007; Skipped</span>', sanitize=False)


# ============================================================================
# PAGE
# ============================================================================
@ui.page("/")
def main_page():
    ui.page_title("Ijmam \u2014 Fleet Dashboard")
    ui.add_head_html(BRAND_HEAD_HTML)
    app_header()

    with ui.column().classes("w-full items-center").style(f"background:{PAGE_BG}; padding:28px 0 60px 0;"):
        with ui.column().style("width:100%; max-width:1180px; padding:0 24px;"):

            # -------- KPI strip (always visible, reflects current state) ----
            kpi_row = ui.row().classes("gap-4 w-full").style("margin-bottom:26px;")

            @ui.refreshable
            def kpi_strip():
                kpi_row.clear()
                df = summary_dataframe()
                all_violations = [v["type"] for t in state["trips"] for v in t["violations"]]
                most_common = (
                    pd.Series(all_violations).value_counts().idxmax() if all_violations else "None"
                )
                with kpi_row:
                    kpi_card("Total Trips", str(len(state["trips"])))
                    kpi_card("Avg Rest Compliance", f"{df['Rest Compliance %'].mean():.1f}%")
                    kpi_card("Most Common Violation", most_common.replace("_", " ").title())
                    kpi_card("Fleet Avg Speed", f"{df['Avg Speed (km/h)'].mean():.0f} km/h")

            with kpi_row:
                pass
            kpi_strip()

            # -------------------------------------------------------------- TABS
            with ui.tabs().classes("w-full").props(
                'indicator-color="orange-9" active-color="dark" no-caps'
            ) as tabs:
                tab_plan = ui.tab("Plan a Trip")
                tab_import = ui.tab("Import CV Results")
                tab_overview = ui.tab("Fleet Overview")
                tab_detail = ui.tab("Trip Detail")

            with ui.tab_panels(tabs, value=tab_plan).classes("w-full").style("background:transparent;"):

                # ============================================================ TAB: PLAN A TRIP
                with ui.tab_panel(tab_plan):
                    with ui.card().classes("ijmam-card w-full").style("padding:24px;"):
                        section_title("New Trip", "Plan a Trip & Get a Rest Schedule")

                        coords = city_coords()
                        cities = sorted(coords.keys())

                        with ui.row().classes("gap-4 w-full items-end"):
                            origin_sel = ui.select(cities, value=cities[0], label="Origin").classes("w-40")
                            dest_sel = ui.select(cities, value=cities[1] if len(cities) > 1 else cities[0],
                                                  label="Destination").classes("w-40")
                            duration_in = ui.number("Duration (hours)", value=8, min=1, max=24).classes("w-40")
                            drivers_in = ui.number("Number of drivers", value=1, min=1, max=5).classes("w-40")

                        ors_key_in = ui.input(
                            "OpenRouteService API key (optional \u2014 leave blank for a straight-line preview)",
                        ).props("type=password").classes("w-full")

                        result_box = ui.column().classes("w-full").style("margin-top:18px;")

                        async def compute_trip():
                            result_box.clear()
                            if origin_sel.value == dest_sel.value:
                                with result_box:
                                    ui.label("Origin and destination can't be the same.").style(f"color:{BAD};")
                                return

                            with result_box:
                                ui.label("Computing route\u2026").style(f"color:{MUTED};")
                            ui.notify("Computing route\u2026", type="ongoing", timeout=1500)

                            schedule = compute_rest_schedule(duration_in.value, drivers_in.value)
                            o_coords = coords[origin_sel.value]
                            d_coords = coords[dest_sel.value]
                            # This can block on a slow/unreachable network for up to ~15s.
                            # Running it in a background thread keeps the UI (and every
                            # other connected client) responsive instead of freezing the
                            # whole event loop, which is what was causing "Connection lost".
                            route_coords = await run.io_bound(
                                get_route, o_coords, d_coords, ors_key_in.value or None
                            )

                            result_box.clear()
                            with result_box:
                                ui.label("Rest Schedule").classes("ijmam-heading").style(
                                    f"font-weight:600; font-size:15px; color:{INK}; margin-bottom:2px;"
                                )
                                curated_stops = get_curated_stops(origin_sel.value, dest_sel.value)
                                matched = match_stops_to_schedule(curated_stops, schedule, duration_in.value)
                                if schedule:
                                    timeline_points = (
                                        [{"hour_mark": 0, "label": "Depart", "sub": origin_sel.value, "endpoint": True}]
                                        + [
                                            {
                                                "hour_mark": s["hour_mark"],
                                                "label": "Swap" if s["type"] == "driver_swap" else "Rest",
                                                "sub": m["name"] if m else f'{s["hour_mark"]}h in',
                                                "status": "taken",
                                            }
                                            for s, m in matched
                                        ]
                                        + [{"hour_mark": duration_in.value, "label": "Arrive",
                                            "sub": dest_sel.value, "endpoint": True}]
                                    )
                                    if not curated_stops:
                                        ui.label(
                                            "No curated real-world stops for this route yet - "
                                            "showing generic timing instead."
                                        ).style(f"color:{MUTED}; font-size:11px; margin-bottom:6px;")
                                    ui.html(
                                        build_timeline_html(duration_in.value, timeline_points),
                                        sanitize=False,
                                    ).classes("w-full")
                                else:
                                    ui.label("Trip is short enough that no stop is required.").style(
                                        f"color:{MUTED}; margin-top:8px;"
                                    )

                                with ui.row().classes("w-full gap-6 items-start no-wrap").style("margin-top:6px;"):
                                    with ui.column().style("flex: 0 0 320px;"):
                                        caption = (
                                            "Real road-following route (OpenRouteService)."
                                            if ors_key_in.value else
                                            "Straight-line preview \u2014 add an ORS API key above for a real road path."
                                        )
                                        ui.label(caption).style(f"color:{MUTED}; font-size:11.5px;")

                                    with ui.column().style("flex:1;"):
                                        stop_markers = [
                                            {
                                                "lat": stop_coords(o_coords, d_coords, s["fraction"])["lat"],
                                                "lon": stop_coords(o_coords, d_coords, s["fraction"])["lon"],
                                                "popup": f'{s["name"]} ({s["type"]})',
                                                "color": "orange" if s["type"] == "fuel" else "purple",
                                                "icon": "tint" if s["type"] == "fuel" else "cutlery",
                                            }
                                            for s in curated_stops
                                        ]
                                        m = build_map(o_coords, d_coords, route_coords,
                                                       origin_sel.value, dest_sel.value,
                                                       extra_markers=stop_markers)
                                        show_map(m)

                        ui.button("Compute Rest Schedule + Route", on_click=compute_trip).props(
                            "color=primary unelevated"
                        ).classes("ijmam-heading").style(f"margin-top:16px; font-weight:700; color:{NAVY};")

                # ============================================================ TAB: IMPORT CV RESULTS
                with ui.tab_panel(tab_import):
                    with ui.card().classes("ijmam-card w-full").style("padding:24px;"):
                        section_title("Computer Vision Team", "Import Violation Results")
                        ui.label(
                            "Upload the CV team's violation CSV (columns: trip_id, violation_type, timestamp)."
                        ).style(f"color:{MUTED}; margin-bottom:14px;")

                        def handle_upload(e):
                            with tempfile.NamedTemporaryFile(
                                mode="wb", suffix=".csv", delete=False
                            ) as tmp:
                                tmp.write(e.content.read())
                                tmp_path = tmp.name
                            state["trips"] = import_cv_csv(state["trips"], tmp_path)
                            kpi_strip.refresh()
                            overview_table.refresh()
                            violation_chart.refresh()
                            ui.notify("Merged into the trip data \u2014 dashboard updated.", color="positive")

                        ui.upload(on_upload=handle_upload, auto_upload=True).props(
                            'accept=".csv" label="Upload violations CSV"'
                        ).classes("w-full")

                # ============================================================ TAB: FLEET OVERVIEW
                with ui.tab_panel(tab_overview):
                    with ui.card().classes("ijmam-card w-full").style("padding:24px; margin-bottom:20px;"):
                        section_title("Trips", "Fleet Overview")

                        @ui.refreshable
                        def overview_table():
                            df = summary_dataframe()
                            ui.table.from_pandas(df).classes("w-full")

                        overview_table()

                    with ui.card().classes("ijmam-card w-full").style("padding:24px;"):
                        section_title("Violations", "Breakdown by Type")

                        @ui.refreshable
                        def violation_chart():
                            all_violations = [v["type"] for t in state["trips"] for v in t["violations"]]
                            counts = pd.Series(all_violations).value_counts()
                            if counts.empty:
                                ui.label("No violations recorded yet.").style(f"color:{MUTED};")
                                return
                            ui.echart({
                                "grid": {"left": 90, "right": 20, "top": 20, "bottom": 20},
                                "xAxis": {"type": "value"},
                                "yAxis": {
                                    "type": "category",
                                    "data": [c.replace("_", " ").title() for c in counts.index.tolist()],
                                },
                                "series": [{
                                    "type": "bar",
                                    "data": counts.values.tolist(),
                                    "itemStyle": {"color": AMBER_DEEP, "borderRadius": [0, 6, 6, 0]},
                                }],
                            }).classes("w-full").style("height:260px;")

                        violation_chart()

                # ============================================================ TAB: TRIP DETAIL
                with ui.tab_panel(tab_detail):
                    with ui.card().classes("ijmam-card w-full").style("padding:24px;"):
                        section_title("Deep Dive", "Trip Detail")

                        trip_ids = [t["trip_id"] for t in state["trips"]]
                        trip_select = ui.select(trip_ids, value=trip_ids[0] if trip_ids else None,
                                                 label="Select a trip").classes("w-64")

                        detail_box = ui.column().classes("w-full").style("margin-top:16px;")

                        @ui.refreshable
                        def render_detail():
                            detail_box.clear()
                            trip = next((t for t in state["trips"] if t["trip_id"] == trip_select.value), None)
                            if not trip:
                                return
                            with detail_box:
                                ui.label(f"{trip['origin']} \u2192 {trip['destination']}").classes(
                                    "ijmam-heading"
                                ).style(f"font-weight:700; font-size:19px; color:{INK};")
                                ui.label(
                                    f"{trip['duration_hours']}h \u00b7 {trip['num_drivers']} driver(s) "
                                    f"\u00b7 {trip['average_speed']} km/h avg"
                                ).style(f"color:{MUTED}; font-size:12.5px; margin-bottom:4px;")

                                # NOTE: exact hour-of-trip isn't stored per rest point in this
                                # schema yet (only location/type/taken) - spacing them evenly
                                # across the duration is a display approximation. Worth adding
                                # a real "hour_mark" field to rest_points once P1/P2's logic
                                # produces it, so this timeline reflects true timing.
                                n = len(trip["rest_points"])
                                timeline_points = (
                                    [{"hour_mark": 0, "label": "Depart", "sub": trip["origin"], "endpoint": True}]
                                    + [
                                        {
                                            "hour_mark": round((i + 1) / (n + 1) * trip["duration_hours"], 1),
                                            "label": "Swap" if r["type"] == "driver_swap" else "Rest",
                                            "sub": r["location"],
                                            "status": "taken" if r["taken"] else "skipped",
                                        }
                                        for i, r in enumerate(trip["rest_points"])
                                    ]
                                    + [{"hour_mark": trip["duration_hours"], "label": "Arrive",
                                        "sub": trip["destination"], "endpoint": True}]
                                )
                                ui.html(
                                    build_timeline_html(trip["duration_hours"], timeline_points, height=100),
                                    sanitize=False,
                                ).classes("w-full")
                                with ui.row().classes("items-center gap-4").style("margin-bottom:10px;"):
                                    ui.html(f'<span class="status-chip-taken">Taken</span>', sanitize=False)
                                    ui.html(f'<span class="status-chip-skipped">Skipped</span>', sanitize=False)

                                with ui.row().classes("w-full gap-6 items-start no-wrap"):
                                    with ui.column().style("flex: 0 0 340px;"):
                                        ui.label("Rest Points").classes("ijmam-heading").style(
                                            f"font-weight:600; color:{INK}; margin-top:2px; margin-bottom:6px;"
                                        )
                                        for r in trip["rest_points"]:
                                            with ui.row().classes("items-center justify-between w-full").style(
                                                "margin-bottom:6px;"
                                            ):
                                                ui.label(f"{r['location']} ({r['type']})").style(
                                                    f"color:{INK}; font-size:13px;"
                                                )
                                                status_chip(r["taken"])

                                        ui.label("Violations Log").classes("ijmam-heading").style(
                                            f"font-weight:600; color:{INK}; margin-top:14px; margin-bottom:6px;"
                                        )
                                        if trip["violations"]:
                                            ui.table(
                                                columns=[
                                                    {"name": "type", "label": "Type", "field": "type"},
                                                    {"name": "timestamp", "label": "Time", "field": "timestamp"},
                                                ],
                                                rows=trip["violations"], row_key="timestamp",
                                            ).classes("w-full")
                                        else:
                                            ui.label("No violations recorded for this trip. \u2705").style(
                                                f"color:{GOOD};"
                                            )

                                    with ui.column().style("flex:1;"):
                                        o, d = trip["origin_coords"], trip["destination_coords"]
                                        route_coords = [[o["lat"], o["lon"]]]
                                        extra_markers = []
                                        for r in trip["rest_points"]:
                                            route_coords.append([r["lat"], r["lon"]])
                                            extra_markers.append({
                                                "lat": r["lat"], "lon": r["lon"],
                                                "popup": f"{r['location']} ({r['type']}) "
                                                         f"- {'Taken' if r['taken'] else 'Skipped'}",
                                                "color": "blue" if r["taken"] else "orange",
                                                "icon": "pause" if r["type"] == "break" else "exchange",
                                            })
                                        route_coords.append([d["lat"], d["lon"]])
                                        m = build_map(o, d, route_coords, trip["origin"], trip["destination"],
                                                       extra_markers=extra_markers)
                                        show_map(m, height=480)
                                        ui.label(
                                            "Blue = rest point taken, Orange = skipped."
                                        ).style(f"color:{MUTED}; font-size:11.5px; margin-top:8px;")

                        trip_select.on("update:model-value", lambda _: render_detail.refresh())
                        render_detail()


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="Ijmam Dashboard", port=8080, reload=False, show=False)
