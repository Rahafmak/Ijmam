"""
llm_answer.py
--------------
The generation: takes the router's
grounded output (exact numbers from analytics.py, or retrieved trip
documents from vector_store.py) and asks llama3.1 to phrase it as a real
answer to the supervisor's question.
"""

import os

import ollama

import query_router

MODEL = "llama3.1"

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



def generate_answer(query: str) -> str:
    """Full pipeline using local Llama 3.1."""
    result = query_router.route(query)

    context = (
        f"Question intent: {result['intent']}\n"
        f"Source: {result['source']}\n\n"
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

    return response['message']['content']


if __name__ == "__main__":
    questions = [
        "What happened during Ahmed's last trip?",
        "How many fatigue violations did Ahmed have?",
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
