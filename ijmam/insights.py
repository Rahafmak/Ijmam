"""Turn a violations CSV into the numbers the dashboard shows."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED = ["trip_id", "violation_type", "timestamp"]

# The night shift as the company manual defines it.
NIGHT_HOURS = set(list(range(23, 24)) + list(range(0, 5)))

SEVERITY_BY_TYPE = {
    "drowsiness": "high",
    "yawning": "medium",
    "fatigue": "high",
    "no_seatbelt": "high",
    "phone_use": "high",
    "unsafe_distance": "high",
    "lane_departure": "medium",
    "speeding": "medium",
    "harsh_braking": "medium",
    "lane_markings_unclear": "low",
}

# Three measurements of the same underlying state, grouped for the
# "is this driver tired" question but kept separate in the charts.
FATIGUE_FAMILY = {"drowsiness", "yawning", "fatigue"}

PRETTY = {
    "phone_use": "Phone use",
    "drowsiness": "Drowsiness",
    "yawning": "Yawning",
    "no_seatbelt": "No seatbelt",
    "lane_departure": "Lane departure",
    "unsafe_distance": "Unsafe distance",
    "fatigue": "Fatigue (weaving)",
    "speeding": "Speeding",
    "lane_markings_unclear": "Lane markings unclear",
}


class InsightsError(ValueError):
    pass


SPREADSHEET_SUFFIXES = {".xlsx", ".xlsm", ".xls"}


def _read_any(path) -> pd.DataFrame:
    """Read a CSV or an Excel file, whichever it actually is."""
    suffix = Path(str(path)).suffix.lower()
    if suffix in SPREADSHEET_SUFFIXES:
        try:
            return pd.read_excel(path)
        except ImportError as exc:
            raise InsightsError(
                "That is an Excel file and the reader is missing. "
                "Run: pip install openpyxl"
            ) from exc
    try:
        return pd.read_csv(path)
    except UnicodeDecodeError:
        try:
            return pd.read_excel(path)
        except Exception as exc:
            raise InsightsError(
                "That file is not readable as a CSV. If it came from Excel, save "
                "it as CSV first (File → Save As → CSV UTF-8)."
            ) from exc
    except pd.errors.ParserError as exc:
        raise InsightsError(
            "That file could not be read as a table. Check it opens as a "
            "spreadsheet and has a header row."
        ) from exc


def load_violations(path: str | Path) -> pd.DataFrame:
    df = _read_any(path)
    df.columns = [str(c).strip().lower() for c in df.columns]

    aliases = {"type": "violation_type", "violation": "violation_type",
               "time": "timestamp", "datetime": "timestamp", "trip": "trip_id"}
    df = df.rename(columns={c: aliases.get(c, c) for c in df.columns})

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise InsightsError(
            "CSV is missing required column(s): " + ", ".join(missing)
            + ". Expected at least: trip_id, violation_type, timestamp."
        )

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", format="mixed")
    bad = int(df["timestamp"].isna().sum())
    df = df.dropna(subset=["timestamp"])
    if df.empty:
        raise InsightsError("No rows with a readable timestamp were found in that CSV.")

    df["violation_type"] = df["violation_type"].astype(str).str.strip().str.lower()
    if "severity" not in df.columns:
        df["severity"] = df["violation_type"].map(SEVERITY_BY_TYPE).fillna("medium")
    if "source" not in df.columns:
        df["source"] = "unknown"
    df["hour"] = df["timestamp"].dt.hour
    df["is_night"] = df["hour"].isin(NIGHT_HOURS)
    df.attrs["dropped_rows"] = bad
    return df.sort_values("timestamp").reset_index(drop=True)


def kpis(df: pd.DataFrame) -> dict:
    total = len(df)
    night = int(df["is_night"].sum())
    high = int((df["severity"] == "high").sum())
    top_type = df["violation_type"].value_counts().idxmax() if total else "none"
    worst_trip = df["trip_id"].value_counts().idxmax() if total else "none"
    fatigue = int(df["violation_type"].isin(FATIGUE_FAMILY).sum())
    return {
        "fatigue": fatigue,
        "fatigue_share": round(fatigue / total * 100, 1) if total else 0.0,
        "total": total,
        "trips": int(df["trip_id"].nunique()),
        "night": night,
        "night_share": round(night / total * 100, 1) if total else 0.0,
        "high_severity": high,
        "top_type": PRETTY.get(top_type, str(top_type).replace("_", " ").title()),
        "worst_trip": worst_trip,
    }


def by_type(df: pd.DataFrame) -> pd.DataFrame:
    counts = df["violation_type"].value_counts()
    return pd.DataFrame(
        {
            "label": [PRETTY.get(t, t.replace("_", " ").title()) for t in counts.index],
            "count": counts.values,
        }
    )


def by_hour(df: pd.DataFrame) -> pd.DataFrame:
    counts = df["hour"].value_counts().reindex(range(24), fill_value=0).sort_index()
    return pd.DataFrame({"hour": counts.index, "count": counts.values})


def by_driver(df: pd.DataFrame) -> pd.DataFrame:
    """Per-driver totals. Empty when the file has no driver column."""
    if "driver" not in df.columns:
        return pd.DataFrame(columns=["driver", "violations", "fatigue", "night"])
    out = (
        df.groupby("driver")
        .agg(
            violations=("violation_type", "count"),
            fatigue=("violation_type", lambda s: int(s.isin(FATIGUE_FAMILY).sum())),
            night=("is_night", "sum"),
        )
        .reset_index()
        .sort_values("violations", ascending=False)
    )
    out["night"] = out["night"].astype(int)
    return out


def by_trip(df: pd.DataFrame) -> pd.DataFrame:
    extra = {"driver": ("driver", "first")} if "driver" in df.columns else {}
    out = (
        df.groupby("trip_id")
        .agg(
            **extra,
            violations=("violation_type", "count"),
            high=("severity", lambda s: int((s == "high").sum())),
            night=("is_night", "sum"),
            first_seen=("timestamp", "min"),
            worst_type=("violation_type", lambda s: s.value_counts().idxmax()),
        )
        .reset_index()
        .sort_values("violations", ascending=False)
    )
    out["worst_type"] = out["worst_type"].map(lambda t: PRETTY.get(t, t.replace("_", " ").title()))
    out["first_seen"] = out["first_seen"].dt.strftime("%Y-%m-%d %H:%M")
    out["night"] = out["night"].astype(int)
    return out


def table_rows(df: pd.DataFrame, limit: int = 300) -> list[dict]:
    shown = df.tail(limit).copy()
    shown["time"] = shown["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    shown["violation"] = shown["violation_type"].map(
        lambda t: PRETTY.get(t, t.replace("_", " ").title())
    )
    cols = ["trip_id", "violation", "time", "severity", "source"]
    if "note" in shown.columns:
        cols.append("note")
    return shown[cols].to_dict("records")


def safety_score(df: pd.DataFrame) -> int:
    """The in-cab scoring, applied to whatever is in the file."""
    from .cv_incab import SCORE_PENALTY

    penalty = df["violation_type"].map(SCORE_PENALTY).fillna(0).sum()
    return max(0, int(100 - penalty))


def headline(df: pd.DataFrame) -> str:
    """One sentence summarising the file."""
    k = kpis(df)
    if not k["total"]:
        return "No violations in this file."
    if k["fatigue_share"] >= 40:
        return (
            f"Most of what was found is tiredness — {k['fatigue']} of {k['total']} "
            "problems were drowsiness, yawning or weaving. That points to the rest "
            "schedule rather than to the driver."
        )
    if k["night_share"] >= 40:
        return (
            f"{k['night_share']:.0f}% of the {k['total']} problems happened between "
            "23:00 and 05:00, so the rest stops matter most before that window, "
            "not after it."
        )
    return (
        f"{k['total']} problems across {k['trips']} trip(s). The most common was "
        f"{k['top_type'].lower()}."
    )
