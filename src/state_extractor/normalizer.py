from __future__ import annotations

import re


class TextNormalizer:
    """Create a parse-friendly view while preserving raw text and spans."""

    VERSION = "0.3.3"

    REPLACEMENTS = {
        "nggak": "tidak",
        "gak": "tidak",
        "ga": "tidak",
        "yg": "yang",
        "yzng": "yang",
        "jiga": "juga",
        "cewekl": "cewek",
        "itumah": "itu mah",
        "beliin": "belikan",
        "diajakin": "diajak",
        "diajakinn": "diajak",
        "kayak": "seperti",
        "bener bener": "benar-benar",
        "beneran": "benar-benar",
        "lama lama": "lama-lama",
        "malam malam": "malam-malam",
        "soalnya": "karena",
        "jadinya": "sehingga",
    }

    @classmethod
    def default(cls):
        return cls()

    def normalize(self, segments: dict) -> dict:
        out = []
        for segment in segments.get("segments", []):
            raw = segment["text"]
            normalized = self._normalize_text(raw)
            item = dict(segment)
            item["raw_text"] = raw
            item["normalized_text"] = normalized
            item["normalization_changed"] = normalized != raw
            out.append(item)
        return {
            "version": self.VERSION,
            "segments": out,
            "diagnostics": [],
        }

    def _normalize_text(self, text: str) -> str:
        out = text
        # Normalize whitespace without destroying punctuation structure.
        out = re.sub(r"[\t\r]+", " ", out)
        out = re.sub(r" {2,}", " ", out)

        for src, dst in sorted(self.REPLACEMENTS.items(), key=lambda kv: len(kv[0]), reverse=True):
            out = re.sub(rf"\b{re.escape(src)}\b", dst, out, flags=re.I)

        # Common clitic spacing in casual Indonesian.
        out = re.sub(r"\bmembuat\s+ku\b", "membuatku", out, flags=re.I)
        out = re.sub(r"\bmenyuruh\s+ku\b", "menyuruhku", out, flags=re.I)
        return out.strip()
