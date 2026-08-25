"""
query_router.py
----------------
Ties the two layers together:

  - analytics.py    -> exact answers for counting/ranking/"most recent"/
                       compliance questions (aggregates over ALL trips)
  - vector_store.py -> semantic answers for open-ended "what happened"
                       narrative questions (best-matching trip text)

"""

import re

import analytics
import vector_store

DATA_PATH = r"/data/synthetic_trips.json"
_df = None  # lazy-loaded singleton


def _get_df():
    global _df
    if _df is None:
        _df = analytics.load_trips_df(DATA_PATH)
    return _df


def _extract_driver_name(query: str) -> str | None:
    df = _get_df()
    names = df["driver_name"].unique().tolist()
    q_lower = query.lower()
    for name in names:
        first_name = name.split()[0].lower()
        if first_name in q_lower or name.lower() in q_lower:
            return name
    return None


def _extract_violation_type(query: str) -> str | None:
    q = query.lower()
    for vtype in ["fatigue", "speeding", "phone", "rest"]:
        if vtype in q:
            return vtype
    return None


def route(query: str) -> dict:
    """Classify the query and return {'intent':, 'answer':, 'source':, 'evidence':}."""
    q = query.lower()
    df = _get_df()
    driver = _extract_driver_name(query)

    # --- "top N violators" ---------------------------------------------
    if "top" in q and ("violator" in q or "violation" in q):
        n_match = re.search(r"top\s+(\d+)", q)
        n = int(n_match.group(1)) if n_match else 3
        top = analytics.top_violators(df, n)
        answer = "Top {} violators:\n".format(n) + "\n".join(
            f"{i+1}. {row.driver_name} — {row.total_violations} total violations"
            for i, row in enumerate(top.itertuples())
        )
        return {"intent": "top_violators", "answer": answer, "source": "analytics", "evidence": top}

    # --- "recurring fatigue issues" --------------------------------------
    if "recurring" in q and "fatigue" in q and driver:
        r = analytics.recurring_fatigue(df, driver)
        answer = (
            f"{driver} had fatigue events in {r['trips_with_fatigue']} of "
            f"{r['total_trips']} trips ({r['total_fatigue_events']} events total). "
            f"{'This does look like a recurring issue' if r['is_recurring'] else 'This looks isolated, not recurring'}, "
            f"appearing in trips: {', '.join(r['trip_ids'])}."
        )
        return {"intent": "recurring_fatigue", "answer": answer, "source": "analytics", "evidence": r}

    # --- "how many X violations did <driver> have" -----------------------
    vtype = _extract_violation_type(query)
    if driver and vtype and ("how many" in q or "count" in q or "number of" in q):
        count = analytics.violation_count(df, driver, vtype)
        answer = f"{driver} had {count} {vtype} violation(s) across all logged trips."
        return {"intent": "violation_count", "answer": answer, "source": "analytics", "evidence": count}

    # --- "which trips had <violation type> violations" -------------------
    if vtype and ("which trips" in q or "what trips" in q or "trips had" in q):
        trips = analytics.trips_with_violation(df, vtype)
        answer = f"{len(trips)} trip(s) had {vtype} violations:\n" + "\n".join(
            f"- {row.trip_id} ({row.driver_name}, {row.departure_time.strftime('%b %d %H:%M')})"
            for row in trips.itertuples()
        )
        return {"intent": "trips_with_violation", "answer": answer, "source": "analytics", "evidence": trips}

    # --- "did <driver> follow his planned rest stops" ---------------------
    if driver and ("rest stop" in q or "planned rest" in q) and (
        "follow" in q or "comply" in q or "compliance" in q
    ):
        rc = analytics.rest_compliance(df, driver)
        followed = int(rc["followed_planned_rest"].sum())
        total = len(rc)
        answer = (
            f"{driver} followed planned rest stops in {followed}/{total} trips.\n"
            + "\n".join(
                f"- {row.trip_id} ({row.departure_time.strftime('%b %d')}): "
                f"{'Followed' if row.followed_planned_rest else 'NOT followed'}"
                for row in rc.itertuples()
            )
        )
        return {"intent": "rest_compliance", "answer": answer, "source": "analytics", "evidence": rc}

    # --- "<driver>'s last trip" -------------------------------------------
    if driver and ("last trip" in q or "most recent trip" in q or "latest trip" in q):
        trip = analytics.last_trip(df, driver)
        if trip is None:
            return {"intent": "last_trip", "answer": f"No trips found for {driver}.", "source": "analytics", "evidence": None}
        # Pull the matching full-text document from the vector store for
        # the narrative details (events, rest stop details, etc.) --
        # analytics.py only carries the numeric columns.
        hits = vector_store.semantic_search(
            trip["trip_id"], n_results=1, where={"trip_id": trip["trip_id"]}
        )
        text = hits[0]["text"] if hits else ""
        answer = f"{driver}'s last trip was {trip['trip_id']} ({trip['departure_time'].strftime('%b %d, %Y %H:%M')}):\n\n{text}"
        return {"intent": "last_trip", "answer": answer, "source": "hybrid", "evidence": trip}

    # --- fallback: open-ended narrative question -> semantic search -------
    where = {"driver_name": driver} if driver else None
    hits = vector_store.semantic_search(query, n_results=3, where=where)
    answer = "Here are the most relevant trips I found:\n\n" + "\n\n".join(
        f"[{h['id']}] (similarity dist={h['distance']:.3f})\n{h['text']}" for h in hits
    )
    return {"intent": "semantic_fallback", "answer": answer, "source": "vector_search", "evidence": hits}


if __name__ == "__main__":
    questions = [
        "What happened during Ahmed's last trip?",
        "How many fatigue violations did Ahmed have?",
        "Who are the top 3 violators?",
        "Which trips had phone violations?",
        "Did Ahmed follow his planned rest stops?",
        "Does Ahmed have recurring fatigue issues?",
    ]
    for q in questions:
        print("=" * 70)
        print("Q:", q)
        result = route(q)
        print(f"[intent={result['intent']}, source={result['source']}]")
        print(result["answer"])
        print()
