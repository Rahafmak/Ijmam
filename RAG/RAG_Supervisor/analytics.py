"""
analytics.py
-------------
Structured (non-vector) layer over the same trip data.

Vector similarity search is good at "find trips that talk about X" -- it is
NOT good at counting, ranking, or "most recent" questions, because:
  - "top 3 violators" requires aggregating across ALL trips, not just the
    ones that happen to score highest similarity to the query text.
  - "how many fatigue violations did Ahmed have" requires an exact sum,
    not the N most-similar documents.
  - "Ahmed's last trip" requires sorting by departure_time, a property
    embeddings know nothing about.

These questions are answered by direct computation over the trip records
(here via pandas), and this is what a supervisor is really asking for --
usually an exact number, not "vibes-similar" text.
"""

import pandas as pd
from data_loader import load_trips


def load_trips_df(json_path: str) -> pd.DataFrame:
    trips = load_trips(json_path)
    rows = []
    for t in trips:
        vb = t["report"]["violations_breakdown"]
        rows.append(
            {
                "trip_id": t["trip_id"],
                "driver_id": t["driver_id"],
                "driver_name": t["driver_name"],
                "origin": t["origin"],
                "destination": t["destination"],
                "departure_time": pd.to_datetime(t["departure_time"]),
                "arrival_time": pd.to_datetime(t["arrival_time"]),
                "status": t["status"],
                "total_violations": t["report"]["total_violations"],
                "fatigue": vb.get("fatigue", 0),
                "speeding": vb.get("speeding", 0),
                "phone": vb.get("phone", 0),
                "rest": vb.get("rest", 0),
                "followed_planned_rest": t["report"]["followed_planned_rest"],
            }
        )
    return pd.DataFrame(rows)


def last_trip(df: pd.DataFrame, driver_name: str) -> pd.Series | None:
    d = df[df["driver_name"].str.lower() == driver_name.lower()]
    if d.empty:
        return None
    return d.sort_values("departure_time", ascending=False).iloc[0]


def violation_count(df: pd.DataFrame, driver_name: str, violation_type: str) -> int:
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
    return df[df[violation_type] > 0][
        ["trip_id", "driver_name", "departure_time", violation_type]
    ]


def rest_compliance(df: pd.DataFrame, driver_name: str) -> pd.DataFrame:
    d = df[df["driver_name"].str.lower() == driver_name.lower()]
    return d[["trip_id", "departure_time", "followed_planned_rest"]].sort_values(
        "departure_time"
    )


def recurring_fatigue(df: pd.DataFrame, driver_name: str, threshold: int = 2) -> dict:
    """Flags a driver as having a recurring fatigue issue if fatigue events
    show up across multiple separate trips (not just one bad trip)."""
    d = df[df["driver_name"].str.lower() == driver_name.lower()]
    trips_with_fatigue = d[d["fatigue"] > 0]
    return {
        "driver_name": driver_name,
        "trips_with_fatigue": len(trips_with_fatigue),
        "total_trips": len(d),
        "total_fatigue_events": int(d["fatigue"].sum()),
        "is_recurring": len(trips_with_fatigue) >= threshold,
        "trip_ids": trips_with_fatigue["trip_id"].tolist(),
    }


if __name__ == "__main__":
    df = load_trips_df("/mnt/user-data/uploads/synthetic_trips.json")

    print("Top 3 violators:")
    print(top_violators(df, 3), "\n")

    print("Ahmed's fatigue violations:", violation_count(df, "Ahmed Ali", "fatigue"))

    print("\nAhmed's last trip:")
    print(last_trip(df, "Ahmed Ali"))

    print("\nRecurring fatigue check for Ahmed:")
    print(recurring_fatigue(df, "Ahmed Ali"))

    print("\nTrips with phone violations:")
    print(trips_with_violation(df, "phone"))
