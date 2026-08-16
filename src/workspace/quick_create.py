from __future__ import annotations

from dataclasses import dataclass, asdict
import re
from typing import Any


_LOCATION_HINTS = {
    "apartemen", "apartment", "lantai", "floor", "unit", "kamar", "room",
    "rumah", "house", "gedung", "building", "jalan", "street", "city", "kota",
    "sanctuary", "castle", "istana", "forest", "hutan", "village", "desa",
    "campus", "kampus", "office", "kantor", "station", "stasiun",
}
_ITEM_HINTS = {
    "item", "pedang", "sword", "blade", "weapon", "senjata", "cincin", "ring",
    "amulet", "buku", "book", "armor", "armour", "potion", "artifact", "artefak",
}
_ORG_HINTS = {
    "organization", "organisation", "organisasi", "guild", "ordo", "order", "faction",
    "faksi", "company", "perusahaan", "kingdom", "kerajaan", "academy", "akademi",
}
_RULE_HINTS = {"rule", "aturan", "hukum", "magic system", "sistem sihir", "mekanisme dunia"}
_CHARACTER_HINTS = {"character", "karakter", "tokoh", "orang", "person", "npc"}
_DOCUMENT_HINTS = {"scene", "chapter", "bab", "outline", "draft", "note", "catatan", "lore note"}


@dataclass(slots=True)
class QuickCreatePreview:
    kind: str
    entity_type: str | None
    name: str
    description: str
    confidence: float
    attributes: dict[str, Any]
    shared_core: dict[str, Any]
    document_type: str | None = None
    warnings: list[str] | None = None
    detected: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["warnings"] = self.warnings or []
        data["detected"] = self.detected or []
        return data


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _has_any(text: str, hints: set[str]) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in hints)


def _strip_prefix(text: str, prefixes: tuple[str, ...]) -> str:
    lowered = text.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return text[len(prefix):].lstrip(" :-")
    return text


def _title_like(text: str) -> str:
    # Keep user casing for IDs/codenames; only capitalize the first letter when
    # the whole input is lowercase.
    if text and text == text.lower():
        return text[:1].upper() + text[1:]
    return text


def parse_quick_create(text: str, *, forced_kind: str | None = None) -> QuickCreatePreview:
    raw = _clean(text)
    if not raw:
        raise ValueError("Describe what you want to create")
    lowered = raw.lower()
    detected: list[str] = []
    warnings: list[str] = []

    explicit_kind = forced_kind
    prefix_map = {
        "project": ("project ", "project:", "proyek ", "proyek:"),
        "world": ("world ", "world:", "dunia ", "dunia:"),
        "folder": ("folder ", "folder:"),
        "document": ("document ", "document:", "dokumen ", "dokumen:"),
        "entity": ("entity ", "entity:", "sheet ", "sheet:"),
    }
    if not explicit_kind:
        for kind, prefixes in prefix_map.items():
            if any(lowered.startswith(prefix) for prefix in prefixes):
                explicit_kind = kind
                raw = _strip_prefix(raw, prefixes)
                lowered = raw.lower()
                detected.append(f"explicit {kind}")
                break

    if explicit_kind in {"project", "world", "folder"}:
        return QuickCreatePreview(
            kind=explicit_kind,
            entity_type=None,
            name=_title_like(raw),
            description="",
            confidence=0.99,
            attributes={},
            shared_core={},
            warnings=warnings,
            detected=detected,
        )

    if explicit_kind == "document" or _has_any(lowered, _DOCUMENT_HINTS):
        # Generic prose creation maps to a Scene. “Drafting” is a workflow
        # status in v1.1, not a document type.
        doc_type = "scene"
        if "chapter" in lowered or re.search(r"\bbab\b", lowered):
            doc_type = "chapter"
        elif "scene" in lowered:
            doc_type = "scene"
        elif "outline" in lowered:
            doc_type = "outline"
        elif "note" in lowered or "catatan" in lowered:
            doc_type = "note"
        # Keep semantic labels such as “Chapter 7” or “Scene Arrival” in the
        # display title. Only generic `document:`/`dokumen:` prefixes are
        # removed earlier by the explicit-kind parser.
        name = raw
        return QuickCreatePreview(
            kind="document", entity_type=None, name=_title_like(name),
            description="", confidence=0.9 if explicit_kind else 0.78,
            attributes={}, shared_core={}, document_type=doc_type,
            warnings=warnings, detected=detected + [doc_type],
        )

    entity_type = "lore"
    confidence = 0.55
    if _has_any(lowered, _LOCATION_HINTS):
        entity_type, confidence = "location", 0.9
        detected.append("location cues")
    elif _has_any(lowered, _ITEM_HINTS):
        entity_type, confidence = "item", 0.86
        detected.append("item cues")
    elif _has_any(lowered, _ORG_HINTS):
        entity_type, confidence = "organization", 0.84
        detected.append("organization cues")
    elif _has_any(lowered, _RULE_HINTS):
        entity_type, confidence = "world_rule", 0.86
        detected.append("world-rule cues")
    elif _has_any(lowered, _CHARACTER_HINTS):
        entity_type, confidence = "character", 0.82
        detected.append("character cues")
    elif explicit_kind == "entity":
        entity_type, confidence = "lore", 0.65
        warnings.append("Type is ambiguous; Arline will create a Lore sheet unless you change it in Advanced.")
    else:
        # Names without structural cues are usually characters in a narrative
        # workspace, but keep confidence low so the preview invites correction.
        words = raw.split()
        if 1 <= len(words) <= 4 and not any(char.isdigit() for char in raw):
            entity_type, confidence = "character", 0.58
            warnings.append("This looks like a name, so Arline guessed Character.")
        else:
            warnings.append("Arline could not confidently infer the sheet type; guessed Lore.")

    attributes: dict[str, Any] = {}
    shared_core: dict[str, Any] = {}
    name = raw

    if entity_type == "location":
        floor = re.search(r"\b(?:lantai|floor)\s*[-:#]?\s*([A-Za-z0-9]+)\b", raw, re.I)
        unit = re.search(r"\bunit\s*[-:#]?\s*([A-Za-z0-9._/-]+)\b", raw, re.I)
        city = re.search(r"\b(?:di|in)\s+([A-Z][\w.-]+(?:\s+[A-Z][\w.-]+){0,2})\b", raw)
        building_part = re.split(r"\b(?:lantai|floor|unit)\b", raw, maxsplit=1, flags=re.I)[0].strip(" ,.-")
        if floor:
            attributes["floor"] = int(floor.group(1)) if floor.group(1).isdigit() else floor.group(1)
            detected.append(f"floor {floor.group(1)}")
        if unit:
            attributes["unit"] = unit.group(1)
            detected.append(f"unit {unit.group(1)}")
        if building_part and building_part.lower() != raw.lower():
            attributes["building"] = building_part
        if city:
            attributes["city"] = city.group(1)
        if unit and building_part:
            name = f"{building_part} — Unit {unit.group(1)}"
        elif floor and building_part:
            name = f"{building_part} — Floor {floor.group(1)}"
        shared_core["kind"] = "location"
        hierarchy = []
        if building_part:
            hierarchy.append(building_part)
        if floor:
            hierarchy.append(f"Floor {floor.group(1)}")
        if unit:
            hierarchy.append(f"Unit {unit.group(1)}")
        if hierarchy:
            attributes["hierarchy"] = hierarchy

    elif entity_type == "item":
        shared_core["kind"] = "item"
    elif entity_type == "organization":
        shared_core["kind"] = "organization"
    elif entity_type == "world_rule":
        shared_core["domain"] = None
        attributes["rule"] = raw
    elif entity_type == "character":
        shared_core["identity"] = {"name": raw}

    return QuickCreatePreview(
        kind="entity",
        entity_type=entity_type,
        name=_title_like(name),
        description=raw,
        confidence=confidence,
        attributes=attributes,
        shared_core=shared_core,
        warnings=warnings,
        detected=detected,
    )
