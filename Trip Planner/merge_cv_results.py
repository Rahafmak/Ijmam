"""
Ijmam - Merge the CV team's violation output into the shared trip data.

Expects a CSV with columns: trip_id, violation_type, timestamp
(exactly the shape of mock_violations.csv - that's the contract).
"""
import json
import csv


def load_trips(path="mock_trips.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_trips(trips, path="mock_trips.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(trips, f, ensure_ascii=False, indent=2)


def import_cv_csv(trips, csv_path):
    """
    Reads a CV-team output CSV and merges violations into the matching
    trip record. Rows with a trip_id that doesn't exist are skipped with
    a warning (not silently dropped) so mismatches get noticed fast.
    Returns the updated trips list.
    """
    trips_by_id = {t["trip_id"]: t for t in trips}
    imported, skipped = 0, 0

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trip_id = row.get("trip_id")
            if trip_id not in trips_by_id:
                print(f"WARNING: {trip_id} not found in trips - skipping row: {row}")
                skipped += 1
                continue
            trips_by_id[trip_id]["violations"].append({
                "type": row["violation_type"],
                "timestamp": row["timestamp"],
            })
            imported += 1

    print(f"Imported {imported} violation(s), skipped {skipped} unmatched row(s).")
    return list(trips_by_id.values())


def update_average_speed(trips, trip_id, new_avg_speed):
    for t in trips:
        if t["trip_id"] == trip_id:
            t["average_speed"] = new_avg_speed
            return True
    print(f"WARNING: {trip_id} not found - average speed not updated")
    return False


if __name__ == "__main__":
    trips = load_trips()
    trips = import_cv_csv(trips, "mock_violations.csv")  # swap for the CV team's real file
    save_trips(trips)
    print("Merged CV violations into mock_trips.json")
