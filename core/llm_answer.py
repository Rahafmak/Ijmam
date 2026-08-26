"""
llm_answer.py
--------------
The generation: takes the router's
grounded output (exact numbers from analytics.py, or retrieved trip
documents from vector_store.py) and asks llama3.1 to phrase it as a real
answer to the supervisor's question.
"""

from __future__ import annotations  # `X | None` annotations on Python 3.9

import os

import ollama
from collections import deque
import re

import query_router

MODEL = "llama3.1"
MEMORY_SIZE = 2
_PRONOUN_RE = re.compile(r"\b(he|him|his|she|her)\b", re.IGNORECASE)

SYSTEM_PROMPT = """You are a fleet-safety assistant that answers a \
supervisor's questions about drivers, using ONLY the context provided \
below. The context was already computed by a separate, exact analytics \
system or retrieved from trip records -- it is ground truth.

Rules:
- Never invent, estimate, or "round" any number. Use only the numbers \
given to you in the context.
- If the context contains an exact answer (a count, a ranking, a \
compliance list), state it directly and confidently.
- If the context is a set of retrieved trip documents rather than a \
computed answer, synthesize a direct answer to the question from those \
documents -- don't just repeat the documents verbatim, answer the \
actual question they were asked.
- If the context doesn't contain enough information to answer, say so \
plainly instead of guessing.
- Keep the answer concise -- 2-5 sentences, unless the question asks for \
a list, in which case use a short list.
"""
# oldest exchange drops off automatically once you go past MEMORY_SIZE.
_history = deque(maxlen=MEMORY_SIZE)
_last_driver = None  # tracks the most recently discussed driver, for pronouns

def _history_text() -> str:
    if not _history:
        return "None yet."
    return "\n".join(f"Q: {q}\nA: {a}" for q, a in _history)

def _resolve_pronouns(query: str) -> str:
    global _last_driver
    found = query_router._extract_driver_name(query)
    if found:
        _last_driver = found
        return query
    if _last_driver and _PRONOUN_RE.search(query):
        return _PRONOUN_RE.sub(_last_driver, query)
    return query


def generate_answer(query: str) -> str:
    """Full pipeline using local Llama 3.1."""
    resolved_query = _resolve_pronouns(query)
    result = query_router.route(resolved_query)

    context = (
        f"Conversation so far (most recent {MEMORY_SIZE}):\n{_history_text()}\n\n"
        f"Question intent (already classified): {result['intent']}\n"
        f"Source of this context: {result['source']}\n\n"
        f"Context:\n{result['answer']}"
    )

    user_content = f"Supervisor's question: {query}\n\n{context}"

    response = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
    )

    _history.append((query, response['message']['content']))

    return response['message']['content']


if __name__ == "__main__":
    questions = [
        "What happened during Ahmed's last trip?",
        "How many fatigue violations did Ahmed have?",
        "How many fatigue violations did Khaled have?",
        "Does he have speeding violations also?",
        "Who are the top 3 violators?",
        "Which trips had phone violations?",
        "Did Ahmed follow his planned rest stops?",
        "Does Ahmed have recurring fatigue issues?",
        # a genuinely open-ended one, to show the semantic_fallback path:
        "Was there anything unusual about the Riyadh to Dammam trips?",
    ]
    for q in questions:
        print("=" * 70)
        print("Q:", q)
        print(generate_answer(q))
        print()
