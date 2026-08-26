"""A small BM25 index, shared by both chatbots."""

from __future__ import annotations

import math
import re
from collections import Counter

STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "is", "are",
    "was", "were", "be", "do", "does", "did", "what", "which", "who", "whom",
    "how", "many", "much", "his", "her", "their", "with", "that", "this", "it",
    "at", "by", "from", "me", "my", "i", "you", "your", "we", "us", "tell",
    "about", "can", "should", "would", "please", "there", "any", "all",
}

# Order matters, and "d" rather than "ed" maps fatigued->fatigue. Two passes
# so "inspections" reaches "inspect".
_SUFFIXES = ("ing", "ers", "ies", "ion", "er", "es", "s", "d", "e")


def normalise(word: str) -> str:
    """Enough of a stemmer to tie driving, drive and driver together."""
    w = word.lower()
    for _ in range(2):
        for suffix in _SUFFIXES:
            if len(w) > len(suffix) + 3 and w.endswith(suffix):
                w = w[: -len(suffix)]
                break
        else:
            break
    return w


def tokenise(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [normalise(w) for w in words if w not in STOPWORDS and len(w) > 2]


class BM25Index:
    def __init__(self, documents: dict[str, str]):
        self.raw = documents
        self.docs = {k: tokenise(v) for k, v in documents.items()}
        self.doc_freq: Counter = Counter()
        for tokens in self.docs.values():
            self.doc_freq.update(set(tokens))
        self.n_docs = max(len(self.docs), 1)
        self.avg_len = max(
            sum(len(t) for t in self.docs.values()) / self.n_docs, 1.0
        )

    def search(
        self,
        query: str,
        n: int = 3,
        restrict_to: set[str] | None = None,
        min_score: float = 0.0,
    ) -> list[tuple[str, float]]:
        q_tokens = tokenise(query)
        if not q_tokens:
            return []
        scored = []
        for doc_id, tokens in self.docs.items():
            if restrict_to is not None and doc_id not in restrict_to:
                continue
            score = self._score(q_tokens, tokens)
            if score > min_score:
                scored.append((doc_id, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:n]

    def _score(self, q_tokens, doc_tokens, k1: float = 1.5, b: float = 0.75) -> float:
        counts = Counter(doc_tokens)
        dl = len(doc_tokens)
        total = 0.0
        for term in q_tokens:
            f = counts.get(term, 0)
            if not f:
                continue
            df = self.doc_freq.get(term, 0)
            idf = math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))
            total += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / self.avg_len))
        return total
