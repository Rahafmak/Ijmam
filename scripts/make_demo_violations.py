"""
Build the demo violations file used by the Insights tab.

The numbers are synthetic, but the shape is deliberate: a small fleet over one
week, where fatigue clusters in the small hours and one driver is clearly worse
than the rest. Those are the two things a fleet manager actually looks for, and
a flat random file shows neither.

Run: python scripts/make_demo_violations.py
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "data" / "fleet_violations.csv"
random.seed(11)

DRIVERS = [
    # name, how risky they are, how much of their driving is at night
    ("Ahmed Ali", 2.6, 0.85),
    ("Tariq Mansour", 1.7, 0.70),
    ("Youssef Hassan", 1.2, 0.55),
    ("Omar Nasser", 0.9, 0.45),
    ("Khalid Saeed", 0.7, 0.35),
    ("Faisal Al-Harbi", 0.5, 0.30),
]

ROUTES = [
    ("Jeddah", "Tabuk", 10),
    ("Jeddah", "Riyadh", 9),
    ("Riyadh", "Dammam", 4),
    ("Jeddah", "Madinah", 4),
    ("Madinah", "Tabuk", 8),
    ("Jeddah", "NEOM", 12),
]

# Fatigue signs dominate at night; phone use is a daytime habit.
NIGHT_MIX = [
    ("drowsiness", 4), ("yawning", 4), ("lane_departure", 3),
    ("unsafe_distance", 2), ("phone_use", 1), ("no_seatbelt", 1),
]
DAY_MIX = [
    ("phone_use", 4), ("unsafe_distance", 2), ("no_seatbelt", 2),
    ("lane_departure", 1), ("yawning", 1), ("drowsiness", 1),
]


def pick(mix):
    kinds = [k for k, _ in mix]
    weights = [w for _, w in mix]
    return random.choices(kinds, weights=weights)[0]


def main() -> None:
    rows = []
    week_start = datetime(2026, 8, 17, 0, 0)
    trip_no = 101

    for day in range(7):
        for name, risk, night_share in DRIVERS:
            if random.random() > 0.75:      # not every driver runs every day
                continue

            origin, destination, hours = random.choice(ROUTES)
            at_night = random.random() < night_share
            depart_hour = random.choice([21, 22, 23]) if at_night else random.choice([6, 7, 8, 10])
            departure = week_start + timedelta(days=day, hours=depart_hour)

            trip_id = f"TRP-{trip_no}"
            trip_no += 1

            # Longer trips and riskier drivers accumulate more.
            count = max(0, int(random.gauss(risk * hours / 3.0, 1.2)))
            for _ in range(count):
                # weight events toward the second half of the trip, which is
                # where fatigue actually shows up
                offset = random.uniform(0.5, hours) ** 0.7 * (hours ** 0.3)
                offset = min(offset, hours)
                moment = departure + timedelta(hours=offset)
                night = moment.hour >= 23 or moment.hour < 5
                rows.append({
                    "trip_id": trip_id,
                    "driver": name,
                    "route": f"{origin} - {destination}",
                    "violation_type": pick(NIGHT_MIX if night else DAY_MIX),
                    "timestamp": moment.strftime("%Y-%m-%dT%H:%M:%S"),
                })

    df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    df.to_csv(OUT, index=False)

    night = df["timestamp"].str.slice(11, 13).astype(int)
    print(f"Wrote {OUT}")
    print(f"  {len(df)} violations across {df['trip_id'].nunique()} trips, "
          f"{df['driver'].nunique()} drivers")
    print(f"  {(night.isin([23, 0, 1, 2, 3, 4])).mean() * 100:.0f}% between 23:00 and 05:00")
    print("  by type:", df["violation_type"].value_counts().to_dict())
    print("  worst driver:", df["driver"].value_counts().idxmax())


if __name__ == "__main__":
    main()
