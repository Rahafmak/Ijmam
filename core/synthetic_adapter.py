"""
Ijmam - Adapter for the team's synthetic_trips.json schema

Converts the richer trip-log schema (driver_id, events, report,
supervisor_summary - built for the RAG/manager chatbot) into the flat
shape the dashboard/map/timeline code already knows how to render.

This is intentionally a one-way READ adapter: synthetic_trips.json stays
the single source of truth (the RAG team keeps building on it as-is), and
the dashboard just reshapes it in memory rather than needing its own
separate copy of the data.
"""
from datetime import datetime
import math

# Static city coordinates - NOT derived from any trip file, so the dropdown
# always has full coverage regardless of which cities show up in the data.
# Covers every city seen in both the original mock set and the team's
# synthetic_trips.json (including Tabuk and Jubail, which the old
# mock-derived lookup was missing).
CITY_COORDS = {
    "Jeddah": {"lat": 21.4858, "lon": 39.1925},
    "Riyadh": {"lat": 24.7136, "lon": 46.6753},
    "Dammam": {"lat": 26.4207, "lon": 50.0888},
    "Madinah": {"lat": 24.5247, "lon": 39.5692},
    "Abha": {"lat": 18.2164, "lon": 42.5053},
    "NEOM": {"lat": 28.0000, "lon": 35.3000},
    "Tabuk": {"lat": 28.3998, "lon": 36.5715},
    "Jubail": {"lat": 27.0046, "lon": 49.6607},
}


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _haversine_km(a, b):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [a["lat"], a["lon"], b["lat"], b["lon"]])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def normalize_trip(raw: dict) -> dict:
    """
    raw: one record from synthetic_trips.json
    Returns the dashboard's internal trip shape:
      trip_id, origin, destination, origin_coords, destination_coords,
      duration_hours, num_drivers, average_speed, rest_points, violations,
      driver_name, supervisor_summary   (the last two kept for future use -
      e.g. showing the driver name in Trip Detail, or feeding the chatbot)
    """
    dep = _parse_ts(raw["departure_time"])
    arr = _parse_ts(raw["arrival_time"])
    duration_hours = round((arr - dep).total_seconds() / 3600, 1)

    o_name, d_name = raw["origin"], raw["destination"]
    if o_name not in CITY_COORDS or d_name not in CITY_COORDS:
        missing = [c for c in (o_name, d_name) if c not in CITY_COORDS]
        raise KeyError(
            f"Trip {raw['trip_id']}: no coordinates for {missing} - "
            f"add it to CITY_COORDS in synthetic_adapter.py"
        )
    o_coords, d_coords = CITY_COORDS[o_name], CITY_COORDS[d_name]

    # This schema only ever logs one driver_id per trip - so num_drivers is
    # always 1 here. If the team later adds driver-swap trips, this is the
    # one line to change.
    num_drivers = 1

    # No distance/speed field exists in this schema - approximate average
    # speed from great-circle distance / duration. It's a real derived
    # estimate, not a stored fact, so it's rougher than a true telemetry
    # average speed would be (real roads aren't straight lines).
    distance_km = _haversine_km(o_coords, d_coords)
    average_speed = round(distance_km / duration_hours, 1) if duration_hours else 0

    rest_events = [e for e in raw["events"] if e["type"] == "rest"]

    rest_points = []
    for stop in raw.get("planned_rest_stops", []):
        scheduled = _parse_ts(stop["scheduled_time"])
        hour_mark = round((scheduled - dep).total_seconds() / 3600, 1)
        # Match this planned stop to an actual rest event within 5 minutes -
        # that's how "taken" vs "skipped" is derived, since the schema
        # doesn't store status directly on the planned stop itself.
        matched_event = next(
            (e for e in rest_events
             if abs((_parse_ts(e["timestamp"]) - scheduled).total_seconds()) <= 300),
            None,
        )
        if matched_event and "location" in matched_event:
            lat = matched_event["location"]["lat"]
            lon = matched_event["location"]["lng"]
        else:
            # No matching rest event (stop was skipped) - no real coordinate
            # exists for it, so interpolate along the straight line between
            # origin and destination based on how far into the trip it was
            # scheduled. An approximation, same spirit as the average_speed
            # estimate above - good enough for the map marker, not a real GPS fix.
            frac = min(1.0, max(0.0, hour_mark / duration_hours)) if duration_hours else 0.5
            lat = o_coords["lat"] + frac * (d_coords["lat"] - o_coords["lat"])
            lon = o_coords["lon"] + frac * (d_coords["lon"] - o_coords["lon"])

        rest_points.append({
            "location": stop["stop_name"],
            "type": "break",
            "taken": matched_event is not None,
            "hour_mark": hour_mark,
            "lat": lat,
            "lon": lon,
        })

    violations = [
        {"type": e["type"], "timestamp": e["timestamp"], "severity": e.get("severity")}
        for e in raw["events"]
        if e["type"] in ("fatigue", "speeding", "phone")
    ]

    return {
        "trip_id": raw["trip_id"],
        "origin": o_name,
        "destination": d_name,
        "origin_coords": o_coords,
        "destination_coords": d_coords,
        "duration_hours": duration_hours,
        "num_drivers": num_drivers,
        "average_speed": average_speed,
        "rest_points": rest_points,
        "violations": violations,
        "driver_name": raw.get("driver_name"),
        "supervisor_summary": raw.get("report", {}).get("supervisor_summary"),
    }


def load_synthetic_trips(path="synthetic_trips.json"):
    import json
    with open(path, "r", encoding="utf-8") as f:
        raw_trips = json.load(f)
    return [normalize_trip(r) for r in raw_trips]


if __name__ == "__main__":
    trips = load_synthetic_trips()
    print(f"Loaded and normalized {len(trips)} trips.")
    print(trips[0])
