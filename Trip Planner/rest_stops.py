"""
Ijmam - Rest stop scheduling + real POI lookup

Two independent pieces:
  1. compute_rest_schedule() - pure formula, no internet needed, works right now.
  2. find_real_rest_stops() - queries OpenStreetMap's Overpass API for real
     fuel stations / rest areas / mosques along a route (needs internet;
     degrades gracefully to an empty list if unreachable).
"""
import requests


def compute_rest_schedule(duration_hours, num_drivers):
    """
    Rule-based rest planning (no risk model - just spacing logic):
      - Solo driver: a break every ~2 hours.
      - Multiple drivers: driver-swap points every ~3.5 hours. A swap point
        already functions as a rest point (the incoming driver takes over
        while the other rests), so no separate break is added on top of it.
      - A supplementary break is only added if there's a genuinely long
        stretch (>= MIN_GAP_HOURS from every existing stop) with nothing
        scheduled - this is what previously caused a "Rest" stop to appear
        awkwardly close to a "Swap" stop (e.g. 3.5h and 4.0h back to back).
    Returns a list of {"hour_mark": float, "type": "break" | "driver_swap"},
    sorted by hour_mark, with no two stops closer than MIN_GAP_HOURS.
    """
    MIN_GAP_HOURS = 1.5
    stops = []

    if num_drivers <= 1:
        interval = 2.0
        hour = interval
        while hour < duration_hours:
            stops.append({"hour_mark": round(hour, 1), "type": "break"})
            hour += interval
    else:
        swap_interval = 3.5
        hour = swap_interval
        while hour < duration_hours:
            stops.append({"hour_mark": round(hour, 1), "type": "driver_swap"})
            hour += swap_interval

        # Only add a midpoint break if it wouldn't land too close to a swap
        candidate = round(duration_hours / 2, 1)
        if duration_hours > 5 and all(
            abs(candidate - s["hour_mark"]) >= MIN_GAP_HOURS for s in stops
        ):
            stops.append({"hour_mark": candidate, "type": "break"})

    stops.sort(key=lambda s: s["hour_mark"])
    return stops


def find_real_rest_stops(route_coords, buffer_meters=3000, amenity_types=None):
    """
    route_coords: list of [lat, lon] points along the route (e.g. from routing.get_route)
    Queries the Overpass API for real fuel stations, rest areas, and mosques
    near a handful of sampled points along the route.
    Returns a list of {"name":..., "lat":..., "lon":..., "amenity":...}.
    NOTE: needs real internet access - returns [] if unreachable, never crashes.
    """
    if amenity_types is None:
        amenity_types = ["fuel", "rest_area", "place_of_worship"]

    step = max(1, len(route_coords) // 5)
    sample_points = route_coords[::step]

    overpass_url = "https://overpass-api.de/api/interpreter"
    results = []
    seen = set()

    for lat, lon in sample_points:
        amenity_filter = "".join(
            f'node["amenity"="{a}"](around:{buffer_meters},{lat},{lon});'
            for a in amenity_types
        )
        query = f"[out:json][timeout:25];({amenity_filter});out center;"

        try:
            resp = requests.post(overpass_url, data={"data": query}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            for el in data.get("elements", []):
                name = el.get("tags", {}).get("name", "Unnamed")
                key = (name, round(el["lat"], 4), round(el["lon"], 4))
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    "name": name,
                    "lat": el["lat"],
                    "lon": el["lon"],
                    "amenity": el.get("tags", {}).get("amenity", "unknown"),
                })
        except Exception as e:
            print(f"Overpass query failed for point ({lat},{lon}): {e} - skipping this point")
            continue

    return results


if __name__ == "__main__":
    # Self-test for the formula (no internet needed)
    print("Solo driver, 10hr trip:", compute_rest_schedule(10, 1))
    print("2 drivers, 10hr trip:  ", compute_rest_schedule(10, 2))
    print("Solo driver, 4hr trip: ", compute_rest_schedule(4, 1))

    # Self-test for the POI lookup (expected to gracefully return [] if
    # this machine can't reach overpass-api.de - that's the fallback working)
    test_route = [[21.4858, 39.1925], [24.7136, 46.6753]]
    poi_result = find_real_rest_stops(test_route)
    print("Overpass result (may be [] if offline/blocked):", poi_result)
