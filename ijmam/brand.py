"""Colours, fonts and the shared UI pieces."""

from __future__ import annotations

from nicegui import ui

NAVY = "#0A0E1A"
PANEL = "#1A2338"
PANEL_RECESSED = "#131A2B"
PANEL_LINE = "#323D5C"
AMBER = "#F2A93B"
AMBER_SOFT = "#C98A2E"
INK = "#EDEFF6"
MUTED = "#9AA3B8"
GOOD = "#4FD1BE"
BAD = "#FF7A59"
WARN = "#F2A93B"

SEVERITY_COLOUR = {"high": BAD, "medium": AMBER, "low": MUTED}


def apply_colors() -> None:

    ui.colors(primary=AMBER, secondary=PANEL_LINE, positive=GOOD, negative=BAD, dark=NAVY)


HEAD_HTML = f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,680&family=Inter:wght@400;500;600&family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  body {{ font-family: 'Inter', -apple-system, sans-serif; background: {NAVY}; }}

  .ijmam-heading {{ font-family: 'Fraunces', serif; font-optical-sizing: auto; color: {INK}; }}
  .ijmam-arabic {{ font-family: 'IBM Plex Sans Arabic', sans-serif; }}
  .ijmam-rtl {{ direction: rtl; text-align: right; font-family: 'IBM Plex Sans Arabic', sans-serif; }}
  .ijmam-mono {{ font-family: ui-monospace, 'SF Mono', Menlo, monospace;
                 font-variant-numeric: tabular-nums; }}

  .ijmam-card {{ background: {PANEL}; border: 1px solid {PANEL_LINE}; border-radius: 14px;
                 box-shadow: 0 2px 10px rgba(0,0,0,.35); }}
  .ijmam-dark-card {{ background: {PANEL_RECESSED}; border: 1px solid {PANEL_LINE};
                      border-radius: 14px; }}

  .nicegui-content, .q-page, .q-card, .q-field__label, .q-field__native,
  label, .q-item__label {{ color: {INK}; }}
  .q-field__control {{ color: {INK} !important; }}
  .q-field__label {{ color: {MUTED} !important; }}
  .q-field__bottom {{ color: {MUTED} !important; }}
  ::placeholder {{ color: {MUTED}; opacity: .7; }}


  .q-menu {{ background: {PANEL} !important; border: 1px solid {PANEL_LINE}; }}
  .q-menu .q-item {{ color: {INK} !important; }}
  .q-menu .q-item:hover, .q-menu .q-item--active {{ background: {PANEL_RECESSED} !important; }}

  .q-tab {{ font-family: 'Inter', sans-serif; font-weight: 600; font-size: 12.5px;
            letter-spacing: .04em; text-transform: uppercase; color: {MUTED} !important;
            min-height: 42px; }}
  .q-tab--active {{ color: {AMBER} !important; }}
  .q-tabs__content {{ border-bottom: 1px solid {PANEL_LINE}; }}
  .q-tab-panels {{ background: transparent !important; }}
  .q-tabs .q-tab__indicator {{ background: {AMBER} !important; height: 2px !important; }}


  .q-table {{ background: transparent; color: {INK}; }}
  .q-table__card {{ background: {PANEL} !important; }}
  .q-table thead tr, .q-table tbody tr {{ background: {PANEL} !important; }}
  .q-table thead th {{ font-weight: 600; font-size: 11px; letter-spacing: .04em;
                        text-transform: uppercase; color: {MUTED};
                        background: {PANEL_RECESSED} !important; }}
  .q-table tbody td {{ color: {INK} !important; background: {PANEL} !important;
                        border-color: {PANEL_LINE} !important; }}
  .q-table tbody tr:nth-child(even) td {{ background: {PANEL_RECESSED} !important; }}
  .q-table tbody tr:hover td {{ background: {PANEL_LINE} !important; }}

  .q-uploader {{ background: {PANEL_RECESSED} !important; border: 1px dashed {PANEL_LINE};
                 border-radius: 12px; width: 100% !important; max-width: 100% !important; }}
  .q-uploader__header {{ background: {PANEL_RECESSED} !important; color: {INK} !important; }}
  .q-uploader__list {{ background: {PANEL_RECESSED} !important; color: {INK} !important; }}

  .folium-frame {{ border-radius: 14px; overflow: hidden; border: 1px solid {PANEL_LINE}; }}

  .chip {{ border-radius: 20px; padding: 3px 12px; font-size: 12px; font-weight: 600;
           display: inline-block; }}
  .chip-good {{ background: {GOOD}22; color: {GOOD}; }}
  .chip-warn {{ background: {AMBER}22; color: {AMBER}; }}
  .chip-bad {{ background: {BAD}22; color: {BAD}; }}
  .chip-muted {{ background: {MUTED}22; color: {MUTED}; }}

  .evidence-img {{ border-radius: 10px; border: 1px solid {PANEL_LINE};
                   width: 220px; height: 132px; object-fit: cover; }}


  .ijmam-timeline {{ position: relative; width: 100%; padding: 34px 6px 26px 6px; }}
  .ijmam-timeline-track {{ position: absolute; left: 6px; right: 6px; top: 50%;
                            height: 2px; background: {PANEL_LINE}; }}
  .ijmam-timeline-point {{ position: absolute; top: 50%; width: 13px; height: 13px;
                            border-radius: 50%; background: {AMBER};
                            border: 2px solid {NAVY}; transform: translate(-50%, -50%); }}
  .ijmam-timeline-point.endpoint {{ background: {INK}; }}
  .ijmam-timeline-point.taken {{ background: {GOOD}; }}
  .ijmam-timeline-point.skipped {{ background: {BAD}; }}

  .ijmam-timeline-point.night {{ background: {NAVY}; border-color: {AMBER};
                                  box-shadow: 0 0 0 3px {AMBER}44; }}
  .ijmam-timeline-label {{ position: absolute; top: 6px; transform: translateX(-50%);
                            font-size: 11.5px; font-weight: 600; color: {INK};
                            white-space: nowrap; }}
  .ijmam-timeline-sub {{ position: absolute; bottom: 2px; transform: translateX(-50%);
                          font-size: 10.5px; color: {MUTED}; white-space: nowrap;
                          max-width: 150px; overflow: hidden; text-overflow: ellipsis; }}
</style>
"""


def header() -> None:
    with ui.row().classes("w-full items-center justify-between").style(
        f"background:{PANEL_RECESSED}; border-bottom:1px solid {PANEL_LINE}; padding:14px 26px;"
    ):
        with ui.row().classes("items-center gap-3"):
            with ui.column().classes("gap-0"):
                ui.label("IJMAM").classes("ijmam-heading").style(
                    "color:white; font-size:20px; font-weight:700; letter-spacing:3px; line-height:1.2;"
                )
                ui.label("FLEET SAFETY").style(
                    f"color:{AMBER}; font-size:10px; letter-spacing:2px; line-height:1.2; font-weight:600;"
                )
        ui.label("إجمام").classes("ijmam-arabic").style(
            f"color:{AMBER}; font-size:22px; font-weight:600; direction:rtl;"
        )


def kpi_card(label: str, value: str, accent: str = AMBER, sub: str | None = None):
    with ui.card().tight().classes("ijmam-card").style(
        "padding:16px 22px; min-width:180px; box-shadow:none;"
    ):
        ui.label(label.upper()).style(
            f"font-size:10.5px; letter-spacing:1.2px; color:{MUTED}; font-weight:600;"
        )
        ui.label(value).classes("ijmam-heading").style(
            f"font-size:26px; font-weight:700; color:{accent}; margin-top:2px;"
        )
        if sub:
            ui.label(sub).style(f"font-size:11px; color:{MUTED}; margin-top:2px;")


def section_title(kicker: str, title: str) -> None:
    ui.label(kicker.upper()).style(
        f"color:{AMBER_SOFT}; font-size:11px; font-weight:700; letter-spacing:1.5px;"
    )
    ui.label(title).classes("ijmam-heading").style(
        f"color:{INK}; font-size:21px; font-weight:700; margin-top:2px; margin-bottom:14px;"
    )


def chip(text: str, kind: str = "muted") -> None:
    ui.html(f'<span class="chip chip-{kind}">{text}</span>', sanitize=False)


def note_line(text: str, colour: str | None = None) -> None:
    ui.label(text).style(f"color:{colour or MUTED}; font-size:12px; line-height:1.55;")


def build_timeline_html(duration_hours: float, points: list, height: int = 92) -> str:
    """The trip as a horizontal timeline: depart, stops, arrive."""

    def pct(h):
        return max(2, min(98, (h / duration_hours) * 100)) if duration_hours else 50

    dots = []
    for p in points:
        left = pct(p["hour_mark"])
        cls = "endpoint" if p.get("endpoint") else (p.get("status") or "")
        dots.append(f'<div class="ijmam-timeline-point {cls}" style="left:{left}%;"></div>')
        dots.append(f'<div class="ijmam-timeline-label" style="left:{left}%;">{p["label"]}</div>')
        if p.get("sub"):
            dots.append(f'<div class="ijmam-timeline-sub" style="left:{left}%;">{p["sub"]}</div>')

    return (
        f'<div class="ijmam-timeline" style="height:{height}px;">'
        f'<div class="ijmam-timeline-track"></div>' + "".join(dots) + "</div>"
    )
