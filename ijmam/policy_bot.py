"""Driver questions, answered only from the company policy manual."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .retrieval import BM25Index

REFUSAL_EN = (
    "That is not covered in the company policy manual. Please contact your "
    "supervisor or the control room before acting on it."
)
REFUSAL_AR = (
    "هذا غير مذكور في دليل سياسات الشركة. الرجاء الرجوع إلى المشرف أو غرفة "
    "التحكم قبل التصرف."
)
GROUNDING_AR = "بحسب دليل السياسات"
GROUNDING_EN = "From the policy manual"
TWO_SECTIONS_AR = "بحسب دليل السياسات، القسمان التاليان ينطبقان:"
TWO_SECTIONS_EN = "Two sections of the manual apply here:"

# Below this score the question is treated as off-manual and refused.
MIN_RELEVANCE = 1.2

# Two sections this close in score are both shown.
CLOSE_CALL_RATIO = 0.85

# Arabic terms mapped onto the English vocabulary the manual uses, so an
# Arabic question can be matched even when only the English manual is present.
AR_TO_EN = {
    "ساع": "hours duration",
    "سوق": "driving continuous",
    "قياد": "driving",
    "راح": "rest break",
    "استراح": "rest break",
    "توقف": "stop break",
    "ليل": "night shift",
    "سرع": "speed limit",
    "جوال": "mobile phone",
    "هاتف": "mobile phone",
    "تلفون": "mobile phone",
    "حزام": "seatbelt",
    "حادث": "accident emergency",
    "طوار": "emergency accident",
    "صيان": "maintenance servicing",
    "فحص": "inspection checklist",
    "إجاز": "leave absence",
    "اجاز": "leave absence",
    "مرض": "sick medical",
    "اضاف": "overtime",
    "إضاف": "overtime",
    "بدل": "allowance compensation",
    "تعب": "fatigue",
    "ارهاق": "fatigue",
    "إرهاق": "fatigue",
    "نعاس": "fatigue",
    "مخالف": "violation warning",
    "عقوب": "warning deduction",
    "كامير": "dashcam footage",
    "شاحن": "heavy vehicle",
}


@dataclass
class PolicyAnswer:
    text: str
    section: str | None
    quote: str | None
    backend: str


def _is_arabic(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06FF" for ch in text)


def _parse(path: Path) -> list[tuple[str, str]]:
    """Split a manual on its numbered headings."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore").replace("\r\n", "\n")
    text = re.sub(r"^=+\n?", "", text, flags=re.MULTILINE)

    sections: list[tuple[str, str]] = []
    for part in re.split(r"\n(?=\d+\.\s)", text):
        part = part.strip()
        heading = part.split("\n", 1)[0].strip() if part else ""
        if re.match(r"^\d+\.", heading):
            sections.append((heading, part))
    return sections


def _section_number(heading: str) -> str:
    match = re.match(r"^(\d+)\.", heading)
    return match.group(1) if match else ""


class PolicyBot:
    """
    Answers strictly from the manual, in the language of the question.

    Both a source manual and its Arabic translation are loaded. Retrieval runs
    against the English text, which is where the searchable vocabulary lives,
    and the answer is then returned from whichever language matches the
    question. Translating a compliance document at query time would risk
    changing what it says, so the Arabic text is a prepared translation rather
    than a generated one.
    """

    def __init__(self, policy_path: Path, policy_path_ar: Path | None = None):
        self.policy_path = Path(policy_path)
        self.gemini = self._start_gemini()
        self.policy_path_ar = (
            Path(policy_path_ar)
            if policy_path_ar
            else self.policy_path.with_name(self.policy_path.stem + "_ar.txt")
        )

        self.sections = _parse(self.policy_path)
        self.sections_ar = _parse(self.policy_path_ar)
        self.by_number_ar = {_section_number(h): (h, b) for h, b in self.sections_ar}

        self.index = self._build_index()
        self.has_arabic = bool(self.sections_ar)
        self.backend = "gemini" if self.gemini else "retrieval-only"

    def _start_gemini(self):
        """
        Nawaf's Gemini chat when a key is available.

        His approach injects the whole manual into the system instructions and
        lets the model answer in the user's language. It reads better in Arabic
        than returning a prepared translation, so it is the preferred path. The
        retrieval layer below stays as the offline fallback, which means the
        assistant still works with no key and no network.
        """
        try:
            from core.policy_chat import GeminiPolicyChat
        except Exception:
            try:
                from policy_chat import GeminiPolicyChat
            except Exception:
                return None
        try:
            return GeminiPolicyChat(self.policy_path)
        except Exception:
            return None

    def _build_index(self):
        # The heading is repeated so section titles outweigh incidental
        # mentions in the body.
        return BM25Index(
            {h: f"{h} {h} {h}\n{b}" for h, b in self.sections}
        )

    def _translate(self, question: str) -> str:
        hits = [en for ar, en in AR_TO_EN.items() if ar in question]
        return " ".join(hits)

    def _retrieve(self, question: str) -> list[tuple[str, str]]:
        """
        Return the matching section, or both when two score within 15%.

        "How long can I drive without a break" has a different answer by day
        and by night, and a driver needs to see the one that applies to them.
        """
        query = question
        if _is_arabic(question):
            translated = self._translate(question)
            if not translated:
                return []
            query = translated

        results = self.index.search(query, n=2, min_score=MIN_RELEVANCE)
        if not results:
            return []

        by_heading = dict(self.sections)
        top_score = results[0][1]
        keep = [r for r in results if r[1] >= top_score * CLOSE_CALL_RATIO]
        return [(h, by_heading[h]) for h, _ in keep]

    def _cite(self, question: str) -> str | None:
        """Which section a Gemini answer most likely came from, for display."""
        hits = self._retrieve(question)
        if not hits:
            return None
        arabic = _is_arabic(question)
        return " + ".join(self._localise(h, b, arabic)[0] for h, b in hits)

    def _localise(self, heading: str, body: str, arabic: bool) -> tuple[str, str]:
        """Swap a retrieved English section for its Arabic counterpart."""
        if not arabic:
            return heading, body
        match = self.by_number_ar.get(_section_number(heading))
        return match if match else (heading, body)

    @staticmethod
    def _bullets(body: str) -> str:
        lines = [
            line.strip("- ").strip()
            for line in body.split("\n")[1:]
            if line.strip().startswith("-")
        ]
        return "\n".join(f"• {line}" for line in lines) or body

    def answer(self, question: str) -> PolicyAnswer:
        arabic = _is_arabic(question)

        if self.gemini is not None:
            try:
                text = self.gemini.ask(question)
                if text:
                    section = None if self.gemini.is_refusal(text) else self._cite(question)
                    return PolicyAnswer(text, section, None, f"gemini · {self.gemini.model}")
            except Exception:
                # Network dropped or quota exhausted. Fall through to retrieval
                # rather than showing the driver an error.
                pass

        hits = self._retrieve(question)
        if not hits:
            return PolicyAnswer(
                REFUSAL_AR if arabic else REFUSAL_EN, None, None, self.backend
            )

        blocks, context_parts, headings = [], [], []
        for heading, body in hits:
            local_heading, local_body = self._localise(heading, body, arabic)
            blocks.append(f"{local_heading}\n{self._bullets(local_body)}")
            context_parts.append(local_body)
            headings.append(local_heading)

        quote = "\n\n".join(blocks)
        section = " + ".join(headings)
        context = "\n\n".join(context_parts)

        if len(hits) == 1:
            lead = f"{GROUNDING_AR}:" if arabic else f"{GROUNDING_EN}:"
        else:
            lead = TWO_SECTIONS_AR if arabic else TWO_SECTIONS_EN

        return PolicyAnswer(f"{lead}\n\n{quote}", section, quote, "retrieval-only")

    def suggested_questions(self, arabic: bool = False) -> list[str]:
        if arabic:
            return [
                "كم ساعة أقدر أسوق متواصل؟",
                "ايش سياسة القيادة الليلية؟",
                "أستخدم الجوال وأنا أسوق؟",
                "وش أسوي إذا حسيت بتعب؟",
            ]
        return [
            "How long can I drive without a break?",
            "What is the night driving policy?",
            "Can I use my phone while driving?",
            "What do I do if I feel fatigued?",
        ]
