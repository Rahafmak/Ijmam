"""
data_loader.py
--------------
Loads synthetic_trips.json and converts each trip into:
  1. a human-readable text "document" (what gets embedded)
  2. a metadata dict (what gets used for filtering / structured lookups)

This is step 2-3 of the pipeline: "load trips" -> "convert each trip into searchable text".
"""

import json
from datetime import datetime


def _fmt_time(iso_str: str) -> str:
    """2026-08-02T11:12:00Z -> 'Aug 02, 2026 11:12'"""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return dt.strftime("%b %d, %Y %H:%M")


def load_trips(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def trip_to_text(trip: dict) -> str:
    """Render one trip as the exact style block the user specified."""
    lines = []
    lines.append(f"Trip {trip['trip_id']}")
    lines.append(f"Driver: {trip['driver_name']}")
    lines.append(f"Route: {trip['origin']} → {trip['destination']}")
    lines.append(f"Departure: {_fmt_time(trip['departure_time'])}")
    lines.append(f"Arrival: {_fmt_time(trip['arrival_time'])}")
    lines.append(f"Status: {trip['status']}")

    lines.append("Planned rest stops:")
    if trip["planned_rest_stops"]:
        for stop in trip["planned_rest_stops"]:
            t = _fmt_time(stop["scheduled_time"]).split(" ")[-1]
            lines.append(
                f"- {stop['stop_name']} at {t}, "
                f"planned duration {stop['planned_duration_minutes']} minutes"
            )
    else:
        lines.append("- None scheduled")

    lines.append("Events:")
    if trip["events"]:
        for e in trip["events"]:
            t = _fmt_time(e["timestamp"]).split(" ")[-1]
            etype = e["type"].capitalize()
            lines.append(f"- {etype} at {t}, {e['severity']} severity.")
            detail = e["details"]
            if e["type"] == "rest" and "duration_minutes" in e:
                detail += f" (rested {e['duration_minutes']} minutes)"
            lines.append(f"  {detail}.")
    else:
        lines.append("- No events recorded")

    vb = trip["report"]["violations_breakdown"]
    lines.append("Violation summary:")
    lines.append(f"- Fatigue: {vb.get('fatigue', 0)}")
    lines.append(f"- Speeding: {vb.get('speeding', 0)}")
    lines.append(f"- Phone: {vb.get('phone', 0)}")
    if "rest" in vb:
        lines.append(f"- Rest: {vb.get('rest', 0)}")

    compliance = "Followed" if trip["report"]["followed_planned_rest"] else "Not followed"
    lines.append(f"Planned rest compliance: {compliance}.")

    # Include the ready-made supervisor summary too -- it's short, dense,
    # and often the best-matching span for a semantic query.
    lines.append(f"Summary: {trip['report']['supervisor_summary']}")

    return "\n".join(lines)


def trip_to_metadata(trip: dict) -> dict:
    """Flat, filter-friendly metadata for every trip.

    NOTE: Chroma metadata values must be str/int/float/bool (no nested
    dicts/lists), so violation counts are flattened into top-level fields
    instead of the nested violations_breakdown dict.
    """
    vb = trip["report"]["violations_breakdown"]
    return {
        "trip_id": trip["trip_id"],
        "driver_id": trip["driver_id"],
        "driver_name": trip["driver_name"],
        "origin": trip["origin"],
        "destination": trip["destination"],
        "departure_time": trip["departure_time"],
        "arrival_time": trip["arrival_time"],
        "status": trip["status"],
        "total_violations": trip["report"]["total_violations"],
        "fatigue_violations": vb.get("fatigue", 0),
        "speeding_violations": vb.get("speeding", 0),
        "phone_violations": vb.get("phone", 0),
        "rest_violations": vb.get("rest", 0),
        "followed_planned_rest": trip["report"]["followed_planned_rest"],
        "has_fatigue_event": vb.get("fatigue", 0) > 0,
        "has_phone_event": vb.get("phone", 0) > 0,
        "has_speeding_event": vb.get("speeding", 0) > 0,
    }


def build_documents(path: str) -> tuple[list[str], list[dict], list[str]]:
    """Returns (documents, metadatas, ids) ready to hand to a vector store."""
    trips = load_trips(path)
    documents = [trip_to_text(t) for t in trips]
    metadatas = [trip_to_metadata(t) for t in trips]
    ids = [t["trip_id"] for t in trips]
    return documents, metadatas, ids


if __name__ == "__main__":
    docs, metas, ids = build_documents("/mnt/user-data/uploads/synthetic_trips.json")
    print(f"Built {len(docs)} trip documents.\n")
    print(docs[0])
    print("\n--- metadata ---")
    print(metas[0])
