"""Folium map rendering."""

from __future__ import annotations

import folium
from nicegui import ui

from .brand import AMBER, NAVY, PANEL_LINE


def _numbered_icon(number: int) -> folium.DivIcon:
    return folium.DivIcon(
        html=(
            f'<div style="background:{AMBER};color:{NAVY};width:26px;height:26px;'
            f'border-radius:50%;border:2px solid white;font:700 13px/22px Inter,sans-serif;'
            f'text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.4);">{number}</div>'
        ),
        icon_size=(26, 26),
        icon_anchor=(13, 13),
    )


def build_map(origin, destination, route_coords, origin_label, destination_label, stops=None):
    m = folium.Map(
        location=[(origin["lat"] + destination["lat"]) / 2,
                  (origin["lon"] + destination["lon"]) / 2],
        zoom_start=6,
        tiles="CartoDB positron",
    )
    folium.PolyLine(route_coords, color=NAVY, weight=4, opacity=0.85).add_to(m)
    folium.Marker([origin["lat"], origin["lon"]], popup=f"Start: {origin_label}",
                  icon=folium.Icon(color="green", icon="play")).add_to(m)
    folium.Marker([destination["lat"], destination["lon"]], popup=f"End: {destination_label}",
                  icon=folium.Icon(color="red", icon="flag")).add_to(m)

    for i, stop in enumerate(stops or [], start=1):
        folium.Marker(
            [stop["lat"], stop["lon"]],
            popup=folium.Popup(stop["popup"], max_width=260),
            tooltip=stop["popup"],
            icon=_numbered_icon(i),
        ).add_to(m)
    return m


def show_map(m, height: int = 430) -> None:
    with ui.element("div").classes("folium-frame").style(
        f"width:100%; height:{height}px; border-color:{PANEL_LINE};"
    ):
        ui.html(m._repr_html_(), sanitize=False).style("width:100%; height:100%; border:0;")
