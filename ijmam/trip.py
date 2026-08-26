"""Trip planning: route, rest schedule and the stops along the way."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from rest_stop_suggestions import (  # noqa: E402
    get_curated_stops,
    match_stops_to_schedule,
    stop_coords,
)
from routing import get_route  # noqa: E402
from synthetic_adapter import CITY_COORDS  # noqa: E402

from .policy_rules import Schedule, compute_rest_schedule, departure_advice  # noqa: E402


@dataclass
class TripPlan:
    origin: str
    destination: str
    duration_hours: float
    num_drivers: int
    departure: datetime
    origin_coords: dict
    destination_coords: dict
    route_coords: list
    schedule: Schedule
    matched: list
    curated_stops: list
    used_real_routing: bool
    advice: str | None = None
    timeline_points: list = field(default_factory=list)

    @property
    def stops(self) -> list:
        return self.schedule.stops

    @property
    def breaks(self) -> int:
        return sum(1 for s in self.schedule.stops if s.type == "break")

    @property
    def swaps(self) -> int:
        return sum(1 for s in self.schedule.stops if s.type == "driver_swap")

    @property
    def driving_between_stops(self) -> float:
        return self.schedule.longest_leg

    @property
    def arrival(self) -> datetime:
        from datetime import timedelta

        return self.departure + timedelta(hours=self.schedule.total_hours)


def cities() -> list[str]:
    return sorted(CITY_COORDS.keys())


def plan_trip(
    origin: str,
    destination: str,
    duration_hours: float,
    num_drivers: int,
    ors_key: str | None,
    departure: datetime | None = None,
) -> TripPlan:
    departure = departure or datetime.now()
    o_coords = CITY_COORDS[origin]
    d_coords = CITY_COORDS[destination]

    schedule = compute_rest_schedule(duration_hours, num_drivers, departure)
    route_coords = get_route(o_coords, d_coords, ors_key or None)
    curated = get_curated_stops(origin, destination)
    matched = match_stops_to_schedule(curated, schedule.as_legacy_dicts(), duration_hours)

    # A real ORS response follows the road and returns many points; the
    # fallback returns exactly two. That's how we know which one we got,
    # without trusting whether a key was merely *entered*.
    used_real_routing = len(route_coords) > 2

    timeline_points = (
        [{"hour_mark": 0, "label": f"{departure:%H:%M}", "sub": origin, "endpoint": True}]
        + [
            {
                "hour_mark": stop.hour_mark,
                "label": f"{stop.label} {stop.minutes}m",
                "sub": (match["name"] if match else f"{stop.clock:%H:%M}"),
                "status": "night" if stop.night else "taken",
            }
            for stop, match in zip(schedule.stops, [m for _, m in matched])
        ]
        + [
            {
                "hour_mark": duration_hours,
                "label": f"{departure + timedelta(hours=schedule.total_hours):%H:%M}",
                "sub": destination,
                "endpoint": True,
            }
        ]
    )

    return TripPlan(
        origin=origin,
        destination=destination,
        duration_hours=float(duration_hours),
        num_drivers=int(num_drivers),
        departure=departure,
        advice=departure_advice(duration_hours, departure),
        origin_coords=o_coords,
        destination_coords=d_coords,
        route_coords=route_coords,
        schedule=schedule,
        matched=matched,
        curated_stops=curated,
        used_real_routing=used_real_routing,
        timeline_points=timeline_points,
    )


def stop_markers(plan: TripPlan) -> list[dict]:
    """The stops actually scheduled for this trip, in order, for the map."""
    markers = []
    matches = [m for _, m in plan.matched]
    for stop, match in zip(plan.stops, matches):
        fraction = min(stop.hour_mark / plan.duration_hours, 1.0)
        coords = (
            stop_coords(plan.origin_coords, plan.destination_coords, match["fraction"])
            if match
            else stop_coords(plan.origin_coords, plan.destination_coords, fraction)
        )
        name = match["name"] if match else f"Stop at {stop.hour_mark:g} h"
        kind = "Driver swap" if stop.type == "driver_swap" else "Rest break"
        markers.append(
            {
                "lat": coords["lat"],
                "lon": coords["lon"],
                "popup": f"{name}<br>{kind}, {stop.minutes} min, around {stop.clock:%H:%M}",
            }
        )
    return markers
