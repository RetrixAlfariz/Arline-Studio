from __future__ import annotations

from collections import Counter
import re
from typing import Any


_WORD_RE = re.compile(r"[\wÀ-ÿ]+", re.UNICODE)
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+|\n+")

_STOPWORDS = {
    "yang", "dan", "di", "ke", "dari", "itu", "ini", "aku", "saya", "dia", "ia",
    "kami", "kita", "mereka", "untuk", "dengan", "pada", "dalam", "sebagai", "karena",
    "saat", "ketika", "sebuah", "suatu", "adalah", "jadi", "juga", "tidak", "tak", "lebih",
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "is", "was",
}

_INTENSIFIERS = {
    "sangat", "benar-benar", "sepenuhnya", "sempurna", "memukau", "luar biasa",
    "really", "very", "completely", "perfectly", "stunning", "incredibly",
}

_FIRST_PERSON = {"aku", "saya", "ku", "-ku", "kami", "kita", "i", "me", "my", "mine", "we", "our"}
_SECOND_PERSON = {"kamu", "kau", "anda", "kalian", "mu", "-mu", "you", "your", "yours"}
_TIME_AFTERNOON = {"sore", "afternoon"}
_TIME_NIGHT = {"malam", "night", "nighttime"}
_TIME_TRANSITIONS = {
    "kemudian", "beberapa jam", "menjelang malam", "malam tiba", "setelah itu",
    "later", "hours later", "by night", "night fell", "afterward",
}


class ProseQualityAnalyzer:
    """Cheap, non-destructive prose diagnostics for the v1.1 output-quality layer.

    The analyzer intentionally flags suspicious surface/narrative behavior instead
    of rewriting story facts. Deep interpretation belongs to later reasoning layers.
    """

    version = "1.1-surface-1"

    def analyze(self, text: str) -> dict[str, Any]:
        source = str(text or "")
        lower = source.casefold()
        tokens = [m.group(0).casefold() for m in _WORD_RE.finditer(source)]
        sentences = [s.strip() for s in _SENTENCE_RE.split(source) if s.strip()]
        issues: list[dict[str, Any]] = []

        def add(kind: str, severity: str, message: str, **detail: Any) -> None:
            issues.append({"kind": kind, "severity": severity, "message": message, **detail})

        duplicate_words = re.findall(r"\b([\wÀ-ÿ]+)\s+\1\b", lower, re.UNICODE)
        if duplicate_words:
            add("duplicate_word", "warning", "Adjacent duplicate words were detected.", examples=duplicate_words[:5])

        if re.search(r"[ \t]{2,}", source) or re.search(r"[!?.,]{3,}", source):
            add("surface_punctuation", "info", "Spacing or punctuation contains suspicious repetition.")

        first_count = sum(1 for token in tokens if token in _FIRST_PERSON)
        second_count = sum(1 for token in tokens if token in _SECOND_PERSON)
        if first_count >= 4 and second_count >= 2:
            add(
                "possible_pov_shift",
                "warning",
                "The prose is predominantly first-person but also contains repeated second-person narration. Check for accidental POV drift.",
                first_person_markers=first_count,
                second_person_markers=second_count,
            )

        has_afternoon = any(re.search(rf"\b{re.escape(word)}\b", lower) for word in _TIME_AFTERNOON)
        has_night = any(re.search(rf"\b{re.escape(word)}\b", lower) for word in _TIME_NIGHT)
        has_transition = any(phrase in lower for phrase in _TIME_TRANSITIONS)
        if has_afternoon and has_night and not has_transition:
            add(
                "possible_time_jump",
                "info",
                "The scene references both afternoon and night without an obvious transition marker.",
            )

        intensifier_hits = sum(lower.count(term) for term in _INTENSIFIERS)
        if intensifier_hits >= max(4, len(sentences) // 3):
            add(
                "generic_intensifier_overuse",
                "info",
                "The prose leans heavily on generic intensifiers/evaluative adjectives; concrete description may read more naturally.",
                count=intensifier_hits,
            )

        content_tokens = [t for t in tokens if len(t) > 2 and t not in _STOPWORDS and not t.isdigit()]
        counts = Counter(content_tokens)
        repeated = [
            {"term": term, "count": count, "ratio": round(count / max(1, len(content_tokens)), 4)}
            for term, count in counts.most_common(8)
            if count >= 5 and count / max(1, len(content_tokens)) >= 0.035
        ]
        if repeated:
            add(
                "lexical_repetition",
                "warning",
                "Several content words repeat often enough to make the prose feel formulaic.",
                terms=repeated,
            )

        openings: list[str] = []
        for sentence in sentences:
            words = [m.group(0).casefold() for m in _WORD_RE.finditer(sentence)]
            if words:
                openings.append(" ".join(words[: min(2, len(words))]))
        opening_counts = Counter(openings)
        if openings:
            opening, count = opening_counts.most_common(1)[0]
            if count >= 4 and count / len(openings) >= 0.35:
                add(
                    "repeated_sentence_opening",
                    "info",
                    "Many sentences begin the same way, reducing rhythm variation.",
                    opening=opening,
                    count=count,
                )

        score = 100
        weights = {"warning": 12, "info": 5, "error": 20}
        for issue in issues:
            score -= weights.get(issue["severity"], 5)
        score = max(0, min(100, score))
        return {
            "version": self.version,
            "score": score,
            "issue_count": len(issues),
            "issues": issues,
            "metrics": {
                "word_count": len(tokens),
                "sentence_count": len(sentences),
                "first_person_markers": first_count,
                "second_person_markers": second_count,
                "intensifier_hits": intensifier_hits,
            },
            "policy": "flag_surface_and_narrative_suspicion_without_rewriting_story_facts",
        }
