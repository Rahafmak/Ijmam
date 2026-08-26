"""
Policy assistant, Gemini version.

Nawaf's chatbot from notebooks/chat_bot_policy_.ipynb, adapted to run inside
the application. The design is his: the full policy text is injected into the
system instructions, the model is told to answer only from it, to match the
user's language, to refuse in that language when the manual is silent, and to
return plain text without markdown. Temperature is zero.

Three changes for the application. The Colab secrets lookup is replaced with an
environment variable, the interactive input loop is replaced with a callable
chat session, and the model name falls back through a short list if the
configured one is unavailable on the account.
"""

from __future__ import annotations

import os
from pathlib import Path

MODELS = ("gemini-3.6-flash", "gemini-2.0-flash", "gemini-1.5-flash")

REFUSAL_AR = "عذراً، هذه المعلومة غير مذكورة في سياسة الشركة الرسمية."
REFUSAL_EN = "I'm sorry, but this information is not mentioned in the official company policy."

SYSTEM_TEMPLATE = """
You are an official Company Policy Assistant for Ejmam Transport Co.
Your primary duty is to answer user questions based STRICTLY and ONLY on the provided Company Policy text below.

RULES:
1. Do not use any outside knowledge or assumptions.
2. ALWAYS match the user's language:
   - If asked in Arabic, reply in Arabic.
   - If asked in English, reply in English.
3. If the information is NOT in the policy:
   - Arabic reply: "{refusal_ar}"
   - English reply: "{refusal_en}"
4. DO NOT use markdown bold formatting (asterisks like **) in any response. Plain text only.

COMPANY POLICY TEXT:
{policy_text}
"""


class GeminiPolicyChat:
    """A chat session over the policy document. Raises if Gemini is unavailable."""

    def __init__(self, policy_path: Path, api_key: str | None = None):
        api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")

        from google import genai
        from google.genai import types

        policy_text = Path(policy_path).read_text(encoding="utf-8")
        instructions = SYSTEM_TEMPLATE.format(
            policy_text=policy_text, refusal_ar=REFUSAL_AR, refusal_en=REFUSAL_EN
        )

        client = genai.Client(api_key=api_key)
        last_error = None
        for model in MODELS:
            try:
                self.chat = client.chats.create(
                    model=model,
                    config=types.GenerateContentConfig(
                        system_instruction=instructions, temperature=0
                    ),
                )
                self.model = model
                return
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"no usable Gemini model: {last_error}")

    def ask(self, question: str) -> str:
        response = self.chat.send_message(question)
        return response.text.replace("*", "").strip()

    @staticmethod
    def is_refusal(text: str) -> bool:
        return text.strip() in {REFUSAL_AR, REFUSAL_EN}
