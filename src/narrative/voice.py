from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any


@dataclass(slots=True)
class LanguageProfile:
    language: str = "id-ID"
    register: str = "natural_informal_neutral"
    narrator_pronoun: str = "aku"
    preserve_user_voice: str = "high"
    code_switching: str = "natural_only"
    discourse_markers: list[str] = field(default_factory=list)
    avoid_translationese: bool = True
    formal_literary_diction: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DescriptionLens:
    visual: float = 0.30
    tactile: float = 0.20
    spatial: float = 0.18
    emotional: float = 0.12
    social: float = 0.10
    auditory: float = 0.10

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SceneEnergy:
    level: str = "low"
    pacing: str = "slow"
    change_rate: str = "low_medium"
    introspection: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VoiceProfileExtractor:
    INDONESIAN_MARKERS = {
        "aku", "saya", "yang", "dan", "dengan", "karena", "jadi", "kalau",
        "gak", "nggak", "tidak", "sih", "oh", "ya", "banget", "aja", "cuma",
        "mau", "pakai", "cerita", "fokus", "dulu", "sekarang",
    }
    INFORMAL = {"aku", "gue", "gua", "gak", "nggak", "sih", "banget", "aja", "cok", "jir", "loh", "deh"}

    @classmethod
    def extract(cls, text: str) -> LanguageProfile:
        tokens = re.findall(r"[\w'-]+", text.lower())
        token_set = set(tokens)
        id_score = sum(1 for x in tokens if x in cls.INDONESIAN_MARKERS)
        en_score = sum(1 for x in tokens if x in {"the", "and", "with", "story", "write", "character", "scene"})
        language = "id-ID" if id_score >= en_score else "en-US"

        if language == "id-ID":
            informal_count = sum(1 for x in tokens if x in cls.INFORMAL)
            register = "natural_informal_neutral" if informal_count else "natural_neutral"
            if "saya" in token_set and "aku" not in token_set:
                pronoun = "saya"
            elif "gue" in token_set or "gua" in token_set:
                pronoun = "gue"
            else:
                pronoun = "aku"
            markers = [m for m in ("sih", "jadinya", "oh ya", "banget", "aja", "deh", "loh") if m in text.lower()]
        else:
            register = "natural_contemporary"
            pronoun = "I" if re.search(r"\bI\b", text) else "adaptive"
            markers = []

        code_switch = "natural_only"
        if language == "id-ID" and en_score > 4:
            code_switch = "preserve_established_terms_only"

        return LanguageProfile(
            language=language,
            register=register,
            narrator_pronoun=pronoun,
            preserve_user_voice="high",
            code_switching=code_switch,
            discourse_markers=markers,
            avoid_translationese=True,
            formal_literary_diction="low" if register.startswith("natural_informal") else "medium_low",
        )

    @classmethod
    def description_lens(cls, text: str) -> DescriptionLens:
        low = text.lower()
        lens = DescriptionLens()
        if any(x in low for x in ("detail", "lihat", "warna", "bentuk", "tampilan", "cermin")):
            lens.visual += 0.12
        if any(x in low for x in ("halus", "sensitif", "gerah", "dingin", "sentuh", "kain")):
            lens.tactile += 0.12
        if any(x in low for x in ("ruang", "apartemen", "lantai", "jarak", "tinggi", "panjang")):
            lens.spatial += 0.08
        if any(x in low for x in ("fano", "keluarga", "pacar", "teman", "dijodohkan")):
            lens.social += 0.12
        total = sum(lens.to_dict().values())
        if total:
            for key, value in lens.to_dict().items():
                setattr(lens, key, round(value / total, 3))
        return lens
