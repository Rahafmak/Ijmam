import json
from datetime import datetime
 
 
def _fmt_time(iso_str: str) -> str:
    """2026-08-02T11:12:00Z -> 'Aug 02, 2026 11:12'"""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return dt.strftime("%b %d, %Y %H:%M")
 
 
def load_trips(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
 
 
def get_drivers(trip: dict) -> list[dict]:
    """Normalize to a list of {'driver_id', 'driver_name'}, handling both
    the new multi-driver schema and the old single-driver schema."""
    if "drivers" in trip and trip["drivers"]:
        return trip["drivers"]
    return [{"driver_id": trip["driver_id"], "driver_name": trip["driver_name"]}]
 
 
def attribute_events(trip: dict) -> list[dict]:
    """Returns trip['events'] (sorted by time) with each event tagged with
    the driver who was active at that moment: adds 'driver_id' and
    'driver_name' keys to a copy of each event dict."""
    drivers = get_drivers(trip)
    events = sorted(trip["events"], key=lambda e: e["timestamp"])
 
    attributed = []
    active_idx = 0
    for e in events:
        e = dict(e)  # don't mutate the original
        e["driver_id"] = drivers[active_idx]["driver_id"]
        e["driver_name"] = drivers[active_idx]["driver_name"]
        attributed.append(e)
        if e["type"] == "rest" and active_idx + 1 < len(drivers):
            active_idx += 1  # handoff: next driver takes over after this rest
    return attributed
 
 
def build_segments(trip: dict) -> list[dict]:
    """Split one trip into per-driver segments. Each segment is:
        {
            "trip_id", "driver_id", "driver_name",
            "segment_index",           # 0-based order they drove in
            "is_solo_driver",          # True if trip had only 1 driver
            "events": [...],           # only this driver's attributed events
        }
    Segment order follows first appearance in the attributed event
    timeline; a driver with zero attributed events (e.g. listed but the
    handoff never actually happened in the log) still gets an empty
    segment so they aren't silently dropped from trip participation.
    """
    drivers = get_drivers(trip)
    attributed_events = attribute_events(trip)
 
    segments = []
    for idx, d in enumerate(drivers):
        seg_events = [e for e in attributed_events if e["driver_id"] == d["driver_id"]]
        segments.append(
            {
                "trip_id": trip["trip_id"],
                "driver_id": d["driver_id"],
                "driver_name": d["driver_name"],
                "segment_index": idx,
                "is_solo_driver": len(drivers) == 1,
                "events": seg_events,
            }
        )
    return segments
 
 
def _is_rest_violation(event: dict, planned_rest_stops: list[dict]) -> bool:
    """A rest event is a violation if the driver rested LESS than the
    planned duration for that stop (matched by scheduled_time ==
    event timestamp). Resting the planned amount or longer is fine.
    A rest event with no matching planned stop (unscheduled rest) is
    treated as compliant -- there's no plan to have violated."""
    match = next(
        (p for p in planned_rest_stops if p["scheduled_time"] == event["timestamp"]),
        None,
    )
    if match is None:
        return False
    return event.get("duration_minutes", 0) < match["planned_duration_minutes"]
 
 
def _violation_counts(events: list[dict], planned_rest_stops: list[dict]) -> dict:
    """Counts violations by category. Every category except `rest` is a
    straight count of that event type. `rest` is special: only an
    under-duration rest counts as a violation (see _is_rest_violation) --
    a rest event by itself is just a handoff point, not a violation."""
    counts = {
        "fatigue": 0,
        "speeding": 0,
        "phone": 0,
        "tailgating": 0,
        "seatbelt": 0,
        "lane_drift": 0,
        "rest": 0,
    }
    for e in events:
        if e["type"] == "rest":
            if _is_rest_violation(e, planned_rest_stops):
                counts["rest"] += 1
        elif e["type"] in counts:
            counts[e["type"]] += 1
    return counts
 
 
def segment_to_text(trip: dict, segment: dict) -> str:
    """Render one driver's segment of a trip as a searchable document."""
    drivers = get_drivers(trip)
    lines = []
    lines.append(f"Trip {trip['trip_id']} (driver segment)")
    lines.append(f"Driver: {segment['driver_name']}")
    if not segment["is_solo_driver"]:
        others = [d["driver_name"] for d in drivers if d["driver_id"] != segment["driver_id"]]
        lines.append(
            f"Co-drivers on this trip: {', '.join(others)} "
            f"(driver {segment['segment_index'] + 1} of {len(drivers)} in rotation)"
        )
    lines.append(f"Route: {trip['origin']} → {trip['destination']}")
    lines.append(f"Trip departure: {_fmt_time(trip['departure_time'])}")
    lines.append(f"Trip arrival: {_fmt_time(trip['arrival_time'])}")
    lines.append(f"Status: {trip['status']}")
 
    lines.append(f"Events during {segment['driver_name']}'s driving segment:")
    if segment["events"]:
        for e in segment["events"]:
            t = _fmt_time(e["timestamp"]).split(" ")[-1]
            etype = e["type"].capitalize()
            lines.append(f"- {etype} at {t}, {e['severity']} severity.")
            detail = e["details"]
            if e["type"] == "rest" and "duration_minutes" in e:
                detail += f" (rested {e['duration_minutes']} minutes, then handed off)"
            lines.append(f"  {detail}.")
    else:
        lines.append("- No events recorded during this segment")
 
    vb = _violation_counts(segment["events"], trip["planned_rest_stops"])
    lines.append(f"Violation summary for {segment['driver_name']} on this trip:")
    lines.append(f"- Fatigue: {vb['fatigue']}")
    lines.append(f"- Speeding: {vb['speeding']}")
    lines.append(f"- Phone: {vb['phone']}")
    lines.append(f"- Tailgating: {vb['tailgating']}")
    lines.append(f"- Seatbelt: {vb['seatbelt']}")
    lines.append(f"- Lane drift: {vb['lane_drift']}")
    lines.append(f"- Rest (under-duration): {vb['rest']}")
 
    return "\n".join(lines)
 
 
def segment_to_metadata(trip: dict, segment: dict) -> dict:
    """Flat, filter-friendly metadata for one driver's segment.
 
    NOTE: Chroma metadata values must be str/int/float/bool, so violation
    counts stay flattened as before.
    """
    vb = _violation_counts(segment["events"], trip["planned_rest_stops"])
    return {
        "trip_id": trip["trip_id"],
        "driver_id": segment["driver_id"],
        "driver_name": segment["driver_name"],
        "segment_index": segment["segment_index"],
        "is_solo_driver": segment["is_solo_driver"],
        "origin": trip["origin"],
        "destination": trip["destination"],
        "departure_time": trip["departure_time"],
        "arrival_time": trip["arrival_time"],
        "status": trip["status"],
        "fatigue_violations": vb["fatigue"],
        "speeding_violations": vb["speeding"],
        "phone_violations": vb["phone"],
        "tailgating_violations": vb["tailgating"],
        "seatbelt_violations": vb["seatbelt"],
        "lane_drift_violations": vb["lane_drift"],
        "rest_violations": vb["rest"],
        # Trip-level compliance is still one flag per trip (the schedule
        # either got followed or it didn't -- it isn't specific to one
        # driver's segment), so every segment of the same trip shares it.
        "followed_planned_rest": trip["report"]["followed_planned_rest"],
        "has_fatigue_event": vb["fatigue"] > 0,
        "has_phone_event": vb["phone"] > 0,
        "has_speeding_event": vb["speeding"] > 0,
        "has_tailgating_event": vb["tailgating"] > 0,
        "has_seatbelt_event": vb["seatbelt"] > 0,
        "has_lane_drift_event": vb["lane_drift"] > 0,
    }
 
 
def build_documents(path: str) -> tuple[list[str], list[dict], list[str]]:
    """Returns (documents, metadatas, ids) ready to hand to a vector store.
    One entry per (trip, driver) segment -- NOT one per trip."""
    trips = load_trips(path)
    documents, metadatas, ids = [], [], []
    for trip in trips:
        for segment in build_segments(trip):
            documents.append(segment_to_text(trip, segment))
            metadatas.append(segment_to_metadata(trip, segment))
            ids.append(f"{trip['trip_id']}_{segment['driver_id']}")
    return documents, metadatas, ids
 
 
if __name__ == "__main__":
    docs, metas, ids = build_documents("/data/synthetic_trips.json")
    print(f"Built {len(docs)} driver-segment documents from trips.\n")
    print(docs[0])
    print("\n--- metadata ---")
    print(metas[0])
 



