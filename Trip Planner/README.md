
## What's inside

| File | Purpose |
|---|---|
| `ijmam_dashboard.py` | The app itself — run this |
| `routing.py` | Road routing (OpenRouteService, with a straight-line fallback) — unchanged |
| `rest_stops.py` | Rest-stop scheduling formula + real POI lookup (Overpass API) — unchanged |
| `merge_cv_results.py` | Merges the CV team's violation CSV into trip data — unchanged |
| `mock_trips.json` | Demo trip data (swap for real logs later — structure stays identical) |
| `mock_violations.csv` | Sample CV-team output CSV, for testing the import flow |
| `geocode_places.py` | One-off helper to turn place names into real lat/lon — run manually, needs real internet |

## How to run it

```bash
pip install -r requirements.txt
python ijmam_dashboard.py
```

Then open **http://localhost:8080** in your browser.

## What you'll see

Four tabs:

1. **Plan a Trip** — pick origin/destination/duration/drivers, get a rest
   schedule + a route map. Optional ORS API key for a real road-following route
   (falls back to a clean straight line without one). Includes the same
   "search real nearby rest stops" Overpass lookup, tucked into an expandable
   section so it doesn't clutter the main flow.
2. **Import CV Results** — upload the CV team's violations CSV, same
   `trip_id, violation_type, timestamp` contract as before. Updates the KPI
   cards, table, and chart immediately.
3. **Fleet Overview** — KPI cards (total trips, avg rest compliance, most
   common violation, fleet avg speed), a full trips table, and a violations
   breakdown chart.
4. **Trip Detail** — pick a trip, see its rest points (with a taken/skipped
   status chip), its violations log, and a map with color-coded rest markers
   (blue = taken, orange = skipped) — same logic as before, cleaner display.