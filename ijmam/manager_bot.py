"""Fleet questions for managers. Numbers come from analytics, never from the model."""

from __future__ import annotations

import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

CORE = Path(__file__).resolve().parents[1] / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import analytics  # noqa: E402
import data_loader  # noqa: E402


def _try_full_stack():
    """
    Use the Chroma + Ollama pipeline when it is installed.

    query_router routes the question, and llm_answer phrases the routed result
    with a local Llama model. Both need heavy dependencies that are optional
    here, so when they are missing the BM25 path below answers instead. The
    routing logic and the analytics calls are the same either way.
    """
    try:
        import query_router  # noqa: F401
    except Exception:
        return None, None
    try:
        import llm_answer  # noqa: F401
    except Exception:
        return query_router, None
    return query_router, llm_answer


@dataclass
class BotAnswer:
    text: str
    intent: str
    source: str
    table: pd.DataFrame | None = None


class ManagerBot:
    def __init__(self, trips_json: Path, use_full_stack: bool = True):
        self.trips_json = Path(trips_json)
        self.router, self.llm = _try_full_stack() if use_full_stack else (None, None)
        self.df = analytics.load_trips_df(str(self.trips_json))

        # One document per (trip, driver) segment rather than per trip, since
        # a trip with two drivers has two different stories in it.
        docs, metas, ids = data_loader.build_documents(str(self.trips_json))
        self.documents = dict(zip(ids, docs))
        self.metadata = dict(zip(ids, metas))
        self._index = _LexicalIndex(self.documents)
        if self.llm is not None:
            self.semantic_backend = "chroma + llama3.1"
        elif self.router is not None:
            self.semantic_backend = "chroma"
        else:
            self.semantic_backend = "bm25"


    def _driver(self, query: str) -> str | None:
        q = query.lower()
        for name in self.df["driver_name"].unique():
            if name.lower() in q or name.split()[0].lower() in q:
                return name
        return None

    @staticmethod
    def _violation_type(query: str) -> str | None:
        q = query.lower()
        aliases = {
            "lane drift": "lane_drift",
            "lane departure": "lane_drift",
            "drift": "lane_drift",
            "tailgating": "tailgating",
            "tailgate": "tailgating",
            "following distance": "tailgating",
            "seatbelt": "seatbelt",
            "seat belt": "seatbelt",
            "belt": "seatbelt",
            "fatigue": "fatigue",
            "drowsy": "fatigue",
            "tired": "fatigue",
            "speeding": "speeding",
            "speed": "speeding",
            "phone": "phone",
            "mobile": "phone",
            "rest": "rest",
        }
        for key, value in aliases.items():
            if key in q:
                return value
        return None


    def answer(self, query: str) -> BotAnswer:
        q = query.lower().strip()
        if not q:
            return BotAnswer("Ask me about drivers, violations, or trips.", "empty", "-")

        if self.router is not None:
            try:
                routed = self.router.route(query)
                text = routed["answer"]
                if self.llm is not None:
                    text = self.llm.generate_answer(query)
                return BotAnswer(text, routed["intent"], routed["source"])
            except Exception:
                # Chroma index not built, Ollama not running, or the model is
                # not pulled. Fall through rather than showing an error.
                pass

        driver = self._driver(query)
        vtype = self._violation_type(query)


        if any(k in q for k in ("summary", "overview", "how is the fleet", "fleet status")):
            total = int(self.df["total_violations"].sum())
            trips = int(self.df["trip_id"].nunique())
            segments = len(self.df)
            worst = analytics.top_violators(self.df, 1)
            compliance = float(self.df["followed_planned_rest"].mean()) * 100
            text = (
                f"{trips} trips logged across {segments} driver segments, "
                f"{total} violations in total. "
                f"Planned-rest compliance is {compliance:.0f}%. "
                f"Highest violation count: {worst.iloc[0]['driver_name']} "
                f"({int(worst.iloc[0]['total_violations'])})."
            )
            return BotAnswer(text, "fleet_summary", "analytics")


        if any(k in q for k in ("shift", "swap", "relief", "pull", "rotate", "rest now")):
            fatigue_rank = (
                self.df.groupby("driver_name")
                .agg(fatigue=("fatigue", "sum"), trips=("trip_id", "count"))
                .sort_values("fatigue", ascending=False)
            )
            flagged = fatigue_rank[fatigue_rank["fatigue"] >= 2]
            if flagged.empty:
                return BotAnswer(
                    "No driver has repeated fatigue events. Nobody needs a shift change "
                    "on the current data.",
                    "shift_change",
                    "analytics",
                )
            lines = [
                f"{name} — {int(row.fatigue)} fatigue events across "
                f"{int(row.trips)} driving segments"
                for name, row in flagged.iterrows()
            ]
            return BotAnswer(
                "Drivers to rotate off the wheel first:\n" + "\n".join(lines),
                "shift_change",
                "analytics",
                flagged.reset_index(),
            )


        if "top" in q and ("violator" in q or "violation" in q or "driver" in q):
            n_match = re.search(r"top\s+(\d+)", q)
            n = int(n_match.group(1)) if n_match else 3
            top = analytics.top_violators(self.df, n)
            lines = [
                f"{i + 1}. {row.driver_name} — {int(row.total_violations)} total violations"
                for i, row in enumerate(top.itertuples())
            ]
            return BotAnswer(f"Top {n} violators:\n" + "\n".join(lines),
                             "top_violators", "analytics", top)


        if "recurring" in q and "fatigue" in q and driver:
            r = analytics.recurring_fatigue(self.df, driver)
            verdict = (
                "this looks like a recurring issue"
                if r["is_recurring"]
                else "this looks isolated rather than recurring"
            )
            text = (
                f"{driver} had fatigue events in {r['trips_with_fatigue']} of "
                f"{r['total_trips']} driving segments ({r['total_fatigue_events']} events total) — "
                f"{verdict}. Trips: {', '.join(r['trip_ids']) or 'none'}."
            )
            return BotAnswer(text, "recurring_fatigue", "analytics")


        if driver and vtype and any(k in q for k in ("how many", "count", "number of")):
            count = analytics.violation_count(self.df, driver, vtype)
            return BotAnswer(
                f"{driver} had {count} {vtype} violation(s) across all logged trips.",
                "violation_count",
                "analytics",
            )


        if vtype and any(k in q for k in ("which trip", "what trip", "trips had", "list trips")):
            trips = analytics.trips_with_violation(self.df, vtype)
            lines = [
                f"- {row.trip_id} ({row.driver_name}, "
                f"{row.departure_time.strftime('%b %d %H:%M')})"
                for row in trips.itertuples()
            ]
            return BotAnswer(
                f"{len(trips)} trip(s) had {vtype} violations:\n" + "\n".join(lines),
                "trips_with_violation",
                "analytics",
                trips,
            )


        if driver and ("rest" in q) and any(k in q for k in ("follow", "comply", "compliance")):
            rc = analytics.rest_compliance(self.df, driver)
            followed = int(rc["followed_planned_rest"].sum())
            lines = [
                f"- {row.trip_id} ({row.departure_time.strftime('%b %d')}): "
                f"{'followed' if row.followed_planned_rest else 'NOT followed'}"
                for row in rc.itertuples()
            ]
            return BotAnswer(
                f"{driver} followed planned rest stops in {followed}/{len(rc)} trips.\n"
                + "\n".join(lines),
                "rest_compliance",
                "analytics",
                rc,
            )


        if driver and any(k in q for k in ("last trip", "most recent", "latest trip")):
            trip = analytics.last_trip(self.df, driver)
            if trip is None:
                return BotAnswer(f"No trips found for {driver}.", "last_trip", "analytics")
            doc = self.documents.get(f"{trip['trip_id']}_{trip['driver_id']}", "")
            return BotAnswer(
                f"{driver}'s last trip was {trip['trip_id']} "
                f"({trip['departure_time'].strftime('%b %d, %Y %H:%M')}):\n\n{doc}",
                "last_trip",
                "hybrid",
            )


        hits = self._index.search(query, n=2, restrict_to=self._driver_segment_ids(driver))
        if not hits:
            return BotAnswer(
                "I could not match that to any trip. Try naming a driver, a trip id, "
                "or ask for the top violators.",
                "no_match",
                "-",
            )
        body = "\n\n".join(self.documents[doc_id] for doc_id, _ in hits)
        return BotAnswer("Closest matching driver segments:\n\n" + body,
                         "semantic_fallback", self.semantic_backend)

    def _driver_segment_ids(self, driver: str | None) -> set[str] | None:
        """Segment document ids belonging to one driver."""
        if not driver:
            return None
        rows = self.df[self.df["driver_name"] == driver]
        return {f"{r.trip_id}_{r.driver_id}" for r in rows.itertuples()}


    def attach_cv_violations(self, df: pd.DataFrame) -> int:
        """Fold a violations CSV into the trip records. Returns rows matched."""
        if df.empty or "trip_id" not in df.columns:
            return 0
        # Several detector outputs fold into one column - drowsiness,
        # yawning and weaving are all fatigue evidence.
        mapping = {
            "phone_use": "phone",
            "no_seatbelt": "seatbelt",
            "drowsiness": "fatigue",
            "yawning": "fatigue",
            "fatigue": "fatigue",
            "lane_departure": "lane_drift",
            "unsafe_distance": "tailgating",
            "speeding": "speeding",
        }
        matched = 0
        for trip_id, group in df.groupby("trip_id"):
            if trip_id not in set(self.df["trip_id"]):
                continue
            idx = self.df.index[self.df["trip_id"] == trip_id][0]  # first segment
            for vtype in group["violation_type"]:
                column = mapping.get(vtype)
                if column and column in self.df.columns:
                    self.df.at[idx, column] += 1
                    self.df.at[idx, "total_violations"] += 1
                    matched += 1
        return matched


class _LexicalIndex:
    """BM25 over the trip documents."""

    def __init__(self, documents: dict[str, str]):
        self.docs = {k: _tokenise(v) for k, v in documents.items()}
        self.df_counts: Counter = Counter()
        for tokens in self.docs.values():
            self.df_counts.update(set(tokens))
        self.N = max(len(self.docs), 1)
        self.avg_len = sum(len(t) for t in self.docs.values()) / self.N

    def search(self, query: str, n: int = 3, restrict_to: set[str] | None = None):
        q_tokens = _tokenise(query)
        scores: list[tuple[str, float]] = []
        for doc_id, tokens in self.docs.items():
            if restrict_to and doc_id not in restrict_to:
                continue
            scores.append((doc_id, self._bm25(q_tokens, tokens)))
        scores.sort(key=lambda x: x[1], reverse=True)
        return [(d, s) for d, s in scores[:n] if s > 0]

    def _bm25(self, q_tokens, doc_tokens, k1=1.5, b=0.75) -> float:
        counts = Counter(doc_tokens)
        dl = len(doc_tokens)
        score = 0.0
        for term in q_tokens:
            f = counts.get(term, 0)
            if not f:
                continue
            df = self.df_counts.get(term, 0)
            idf = math.log(1 + (self.N - df + 0.5) / (df + 0.5))
            score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / self.avg_len))
        return score


_STOP = {
    "the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "is", "was",
    "did", "do", "does", "what", "which", "who", "how", "many", "his", "her",
    "with", "that", "this", "it", "at", "by", "from", "me", "tell", "about",
}


def _tokenise(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 1]
