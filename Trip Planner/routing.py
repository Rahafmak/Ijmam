"""
Ijmam - Real road routing via OpenRouteService
Free API key: https://openrouteservice.org/dev/#/signup (instant, no card needed)

Design choice: get_route() NEVER crashes your app. If there's no API key,
or the request fails for any reason (no internet, rate limit, bad coords),
it silently falls back to a straight line so the map still renders.
"""
import requests

ORS_BASE_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"


def get_road_route(origin, destination, api_key):
    """
    origin/destination: dicts like {"lat": 21.48, "lon": 39.19}
    Returns a list of [lat, lon] points following the real road,
    or None if it fails (caller falls back to a straight line).
    """
    if not api_key:
        return None

    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    body = {
        "coordinates": [
            [origin["lon"], origin["lat"]],
            [destination["lon"], destination["lat"]],
        ]
    }
    try:
        resp = requests.post(ORS_BASE_URL, json=body, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        coords = data["features"][0]["geometry"]["coordinates"]
        # GeoJSON gives [lon, lat] - flip to [lat, lon] for folium
        return [[lat, lon] for lon, lat in coords]
    except Exception as e:
        print(f"ORS routing failed ({e}), falling back to a straight line.")
        return None


def straight_line_fallback(origin, destination):
    return [[origin["lat"], origin["lon"]], [destination["lat"], destination["lon"]]]


def get_route(origin, destination, api_key=None):
    """The one function the dashboard should call. Always returns *something* drawable."""
    route = get_road_route(origin, destination, api_key)
    if route is None:
        route = straight_line_fallback(origin, destination)
    return route


if __name__ == "__main__":
    # Quick self-test - no API key, so this should fall back cleanly
    jeddah = {"lat": 21.4858, "lon": 39.1925}
    riyadh = {"lat": 24.7136, "lon": 46.6753}
    result = get_route(jeddah, riyadh, api_key=None)
    print("Route (no API key, expect straight-line fallback):", result)
    assert len(result) == 2, "fallback should be a 2-point straight line"
    print("Self-test passed.")
