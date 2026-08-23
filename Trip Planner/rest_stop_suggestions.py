"""
Ijmam - Curated rest stop suggestions

Why curated instead of live lookup: we already tried a live Overpass API
search and pulled it because "no internet right now" and "genuinely no
data" looked identical in the UI, which is a bad thing to gamble on during
a live demo. This is the reliable alternative: a hand-built list grounded
in real Saudi highway infrastructure, with zero network dependency.

Grounding: SASCO and Aldrees are the two dominant real operators on Saudi
intercity highways - SASCO in particular is documented as the first
company licensed specifically to run full highway rest areas (restaurants,
restrooms, prayer rooms), and Aldrees has the widest station count
nationally. Exact station names/addresses below are illustrative, built in
that real style (not scraped from a verified live directory) - good enough
for a demo, but worth a real Google Maps/Overpass pass before treating this
as ground truth for an actual production system.

Positions are given as a fraction (0.0-1.0) of the straight-line distance
between origin and destination, then converted to lat/lon by interpolation -
same approach already used for the skipped-stop fallback in
synthetic_adapter.py, kept consistent rather than introducing a second way
of estimating a location.
"""

# Each route stores an explicit "from" city - the direction the fractions
# were actually authored against. This matters: a frozenset key has no
# direction, so without this, querying the reverse direction (e.g. Riyadh
# -> Jeddah when the data was authored as Jeddah -> Riyadh) silently placed
# stops on the wrong end of the route - Taif (near Jeddah) was showing up
# near Riyadh. get_curated_stops() below flips the fractions when the
# query direction doesn't match "from".
ROUTE_REST_STOPS = {
    frozenset({"Riyadh", "Dammam"}): {
        "from": "Riyadh",
        "stops": [
            {"name": "Aldrees Station - Al Kharj Road", "type": "fuel", "fraction": 0.15},
            {"name": "SASCO Rest Area - Al Ahsa Road", "type": "rest_area", "fraction": 0.45},
        ],
    },
    frozenset({"Jeddah", "Madinah"}): {
        "from": "Jeddah",
        "stops": [
            {"name": "SASCO Rest Area - Rabigh", "type": "rest_area", "fraction": 0.35},
            {"name": "Aldrees Station - Badr Road", "type": "fuel", "fraction": 0.70},
        ],
    },
    frozenset({"Jeddah", "Riyadh"}): {
        "from": "Jeddah",
        "stops": [
            {"name": "SASCO Rest Area - Taif Road", "type": "rest_area", "fraction": 0.25},
            {"name": "Aldrees Station - Al Quwayiyah", "type": "fuel", "fraction": 0.55},
            {"name": "SASCO Rest Area - Al Kharj Approach", "type": "rest_area", "fraction": 0.85},
        ],
    },
    frozenset({"Riyadh", "Tabuk"}): {
        "from": "Riyadh",
        "stops": [
            {"name": "Aldrees Station - Al Qassim Road", "type": "fuel", "fraction": 0.30},
            {"name": "SASCO Rest Area - Hail Junction", "type": "rest_area", "fraction": 0.60},
        ],
    },
    frozenset({"Dammam", "Jubail"}): {
        "from": "Dammam",
        "stops": [
            {"name": "Aldrees Station - Coastal Road", "type": "fuel", "fraction": 0.50},
        ],
    },
    frozenset({"Riyadh", "Abha"}): {
        "from": "Riyadh",
        "stops": [
            {"name": "SASCO Rest Area - Wadi Al Dawasir", "type": "rest_area", "fraction": 0.40},
            {"name": "Aldrees Station - Khamis Mushait Approach", "type": "fuel", "fraction": 0.80},
        ],
    },
}


def get_curated_stops(origin: str, destination: str):
    """
    Returns the curated stop list for this route, correctly oriented for
    whichever direction was actually requested, or [] if we don't have one yet.
    """
    entry = ROUTE_REST_STOPS.get(frozenset({origin, destination}))
    if not entry:
        return []
    if origin == entry["from"]:
        return entry["stops"]
    # Reverse direction from how this route's fractions were authored -
    # flip each fraction so the real-world position stays correct.
    return [{**s, "fraction": round(1 - s["fraction"], 3)} for s in entry["stops"]]


def stop_coords(origin_coords, destination_coords, fraction):
    lat = origin_coords["lat"] + fraction * (destination_coords["lat"] - origin_coords["lat"])
    lon = origin_coords["lon"] + fraction * (destination_coords["lon"] - origin_coords["lon"])
    return {"lat": lat, "lon": lon}


def match_stops_to_schedule(curated_stops, schedule, duration_hours):
    """
    Matches each schedule stop to the nearest curated real-world stop by
    position, WITHOUT reusing the same curated stop twice while another
    unused one is still reasonably close - this is what was causing two
    different schedule stops (e.g. "Rest" and the next "Swap") to both
    show the same station name when their fractions happened to be closer
    to each other than to their own best match.
    Returns a list of (schedule_stop, matched_curated_stop_or_None) pairs,
    in schedule order.
    """
    if not curated_stops or not duration_hours:
        return [(s, None) for s in schedule]

    available = list(curated_stops)
    result = []
    for s in schedule:
        if not available:
            result.append((s, None))
            continue
        target_fraction = s["hour_mark"] / duration_hours
        best = min(available, key=lambda c: abs(c["fraction"] - target_fraction))
        available.remove(best)
        result.append((s, best))
    return result


if __name__ == "__main__":
    print("=== Direction bug regression test ===")
    stops_j2r = get_curated_stops("Jeddah", "Riyadh")
    stops_r2j = get_curated_stops("Riyadh", "Jeddah")
    print("Jeddah->Riyadh Taif fraction:", next(s["fraction"] for s in stops_j2r if "Taif" in s["name"]))
    print("Riyadh->Jeddah Taif fraction:", next(s["fraction"] for s in stops_r2j if "Taif" in s["name"]))
    assert next(s["fraction"] for s in stops_j2r if "Taif" in s["name"]) == 0.25
    assert next(s["fraction"] for s in stops_r2j if "Taif" in s["name"]) == 0.75
    print("Correct: Taif is 0.25 from Jeddah and 0.75 from Riyadh either way - same real location.")

    print("\n=== No-duplicate matching test (Riyadh->Jeddah, 10h, 2 drivers) ===")
    from rest_stops import compute_rest_schedule
    schedule = compute_rest_schedule(10, 2)
    matches = match_stops_to_schedule(stops_r2j, schedule, 10)
    for s, m in matches:
        print(f"  hour {s['hour_mark']} ({s['type']}) -> {m['name'] if m else 'GENERIC'}")
    matched_names = [m["name"] for s, m in matches if m]
    assert len(matched_names) == len(set(matched_names)), "duplicate stop names assigned!"
    print("Correct: no duplicate station names assigned across schedule stops.")

    print("\nNo curated data test (Riyadh<->NEOM):", get_curated_stops("Riyadh", "NEOM"))
