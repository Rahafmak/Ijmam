"""
analytics.py
-------------
Structured (non-vector) layer over the same trip data.

answers analytics questions by direct computation over the trip records
(here via pandas).
"""

import pandas as pd
from data_loader import load_trips, build_segments, _violation_counts
 
VIOLATION_TYPES = [
    "fatigue", "speeding", "phone", "tailgating", "seatbelt", "lane_drift", "rest",
]
 
 
def load_trips_df(json_path: str) -> pd.DataFrame:
    """One row per (trip, driver) segment -- NOT one row per trip."""
    trips = load_trips(json_path)
    rows = []
    for t in trips:
        for seg in build_segments(t):
            vb = _violation_counts(seg["events"], t["planned_rest_stops"])
            rows.append(
                {
                    "trip_id": t["trip_id"],
                    "driver_id": seg["driver_id"],
                    "driver_name": seg["driver_name"],
                    "segment_index": seg["segment_index"],
                    "is_solo_driver": seg["is_solo_driver"],
                    "origin": t["origin"],
                    "destination": t["destination"],
                    "departure_time": pd.to_datetime(t["departure_time"]),
                    "arrival_time": pd.to_datetime(t["arrival_time"]),
                    "status": t["status"],
                    "total_violations": sum(vb.values()),
                    "fatigue": vb["fatigue"],
                    "speeding": vb["speeding"],
                    "phone": vb["phone"],
                    "tailgating": vb["tailgating"],
                    "seatbelt": vb["seatbelt"],
                    "lane_drift": vb["lane_drift"],
                    "rest": vb["rest"],
                    # Trip-wide compliance flag -- shared by every segment
                    # of the same trip (see data_loader.segment_to_metadata).
                    "followed_planned_rest": t["report"]["followed_planned_rest"],
                }
            )
    return pd.DataFrame(rows)
 
 
def last_trip(df: pd.DataFrame, driver_name: str) -> pd.Series | None:
    """Most recent trip this driver participated in (as any segment,
    solo or co-driver)."""
    d = df[df["driver_name"].str.lower() == driver_name.lower()]
    if d.empty:
        return None
    return d.sort_values("departure_time", ascending=False).iloc[0]
 
 
def violation_count(df: pd.DataFrame, driver_name: str, violation_type: str) -> int:
    """Exact sum, counting only events attributed to this driver's own
    segments -- a co-driver's speeding doesn't get credited here."""
    d = df[df["driver_name"].str.lower() == driver_name.lower()]
    return int(d[violation_type].sum())
 
 
def top_violators(df: pd.DataFrame, n: int = 3) -> pd.DataFrame:
    grouped = (
        df.groupby("driver_name")["total_violations"]
        .sum()
        .sort_values(ascending=False)
        .head(n)
    )
    return grouped.reset_index()
 
 
def trips_with_violation(df: pd.DataFrame, violation_type: str) -> pd.DataFrame:
    """Trips where the given violation occurred, with the specific driver
    it's attributed to (not just 'someone on this trip')."""
    return df[df[violation_type] > 0][
        ["trip_id", "driver_name", "departure_time", violation_type]
    ]
 
 
def rest_compliance(df: pd.DataFrame, driver_name: str) -> pd.DataFrame:
    """Trip-level compliance for every trip this driver participated in.
    NOTE: on a multi-driver trip this reflects whether the TRIP as a whole
    followed its schedule, not this driver's segment specifically -- there
    is no such thing as "half the trip complied"."""
    d = df[df["driver_name"].str.lower() == driver_name.lower()]
    return d[["trip_id", "departure_time", "followed_planned_rest"]].sort_values(
        "departure_time"
    )
 
 
def recurring_violation(df: pd.DataFrame, driver_name: str, violation_type: str, threshold: int = 2) -> dict:
    """Flags a driver as having a recurring issue in `violation_type` if it
    shows up across multiple separate trip segments (not just one bad trip).
    Generalizes recurring_fatigue to any of VIOLATION_TYPES, since the new
    schema tracks several behavior categories (tailgating, seatbelt,
    lane_drift) the same way fatigue always was."""
    d = df[df["driver_name"].str.lower() == driver_name.lower()]
    segments_with_violation = d[d[violation_type] > 0]
    return {
        "driver_name": driver_name,
        "violation_type": violation_type,
        "trips_with_violation": len(segments_with_violation),
        "total_trips": len(d),
        "total_violation_events": int(d[violation_type].sum()),
        "is_recurring": len(segments_with_violation) >= threshold,
        "trip_ids": segments_with_violation["trip_id"].tolist(),
    }
 
 
def recurring_fatigue(df: pd.DataFrame, driver_name: str, threshold: int = 2) -> dict:
    """Backward-compatible wrapper for the fatigue-specific case."""
    r = recurring_violation(df, driver_name, "fatigue", threshold)
    return {
        "driver_name": r["driver_name"],
        "trips_with_fatigue": r["trips_with_violation"],
        "total_trips": r["total_trips"],
        "total_fatigue_events": r["total_violation_events"],
        "is_recurring": r["is_recurring"],
        "trip_ids": r["trip_ids"],
    }
 
 
if __name__ == "__main__":
    df = load_trips_df("/data/synthetic_trips.json")
 
    print("Top 3 violators:")
    print(top_violators(df, 3), "\n")
 
    print("Ahmed's fatigue violations:", violation_count(df, "Ahmed Ali", "fatigue"))
 
    print("\nAhmed's last trip:")
    print(last_trip(df, "Ahmed Ali"))
 
    print("\nRecurring fatigue check for Ahmed:")
    print(recurring_fatigue(df, "Ahmed Ali"))
 
    print("\nTrips with phone violations:")
    print(trips_with_violation(df, "phone"))
 



