from __future__ import annotations

import html
import re
from typing import Any


_MONTHS = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12,
    "january": 1, "february": 2, "march": 3, "may": 5, "june": 6, "july": 7,
    "august": 8, "october": 10, "december": 12,
}

_NAME_CONTEXTS = {"default", "formal", "casual", "story_presence"}
_MEMORY_CATEGORIES = {
    "collaboration_preferences": {"enabled": True, "scope": "private", "retention_days": 90, "fields": {}},
    "about_you": {"enabled": True, "scope": "private", "retention_days": 180, "fields": {}},
    "story_presence": {"enabled": False, "scope": "selected_stories", "retention_days": 180, "fields": {}},
    "conversation_insights": {"enabled": True, "scope": "private", "retention_days": 90, "fields": {}},
}


def _bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def normalize_preferred_names(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Return an ordered, migration-safe preferred-name rule list."""
    raw_names = profile.get("preferred_names")
    names: list[dict[str, Any]] = []
    if isinstance(raw_names, list):
        for index, raw in enumerate(raw_names):
            if not isinstance(raw, dict):
                continue
            value = str(raw.get("value") or raw.get("name") or "").strip()
            if not value:
                continue
            context = str(raw.get("context") or "default")
            names.append({
                "id": str(raw.get("id") or f"name-{index + 1}"),
                "value": value,
                "context": context if context in _NAME_CONTEXTS else "default",
                "primary": bool(raw.get("primary")),
                "pronunciation": str(raw.get("pronunciation") or "").strip(),
                "language": str(raw.get("language") or "").strip(),
            })

    if not names:
        details = profile.get("personal_details") or {}
        preferred = details.get("preferred_name") if isinstance(details, dict) else None
        preferred_value = str((preferred or {}).get("value") or "").strip() if isinstance(preferred, dict) else ""
        fallback = preferred_value or str(profile.get("display_name") or "").strip()
        if fallback:
            names.append({"id": "name-1", "value": fallback, "context": "default", "primary": True, "pronunciation": "", "language": ""})

    primary_index = next((index for index, item in enumerate(names) if item["primary"]), 0)
    for index, item in enumerate(names):
        item["primary"] = index == primary_index
    return names


def normalize_memory_policy(policy: Any) -> dict[str, Any]:
    """Expand legacy booleans into the granular personal-memory policy."""
    raw = dict(policy) if isinstance(policy, dict) else {}
    raw_categories = raw.get("categories") if isinstance(raw.get("categories"), dict) else {}
    categories: dict[str, dict[str, Any]] = {}
    for key, defaults in _MEMORY_CATEGORIES.items():
        current = raw_categories.get(key) if isinstance(raw_categories.get(key), dict) else {}
        legacy_default = defaults["enabled"]
        if key == "collaboration_preferences" and "creative_preferences" in raw:
            legacy_default = bool(raw["creative_preferences"])
        if key == "story_presence" and "reusable_personas" in raw:
            legacy_default = bool(raw["reusable_personas"])
        try:
            retention_days = max(0, int(current.get("retention_days", defaults["retention_days"])))
        except (TypeError, ValueError):
            retention_days = int(defaults["retention_days"])
        categories[key] = {
            "enabled": _bool(current.get("enabled"), bool(legacy_default)),
            "scope": str(current.get("scope") or defaults["scope"]),
            "retention_days": retention_days,
            "fields": dict(current.get("fields") or {}) if isinstance(current.get("fields"), dict) else {},
        }
    behavior = raw.get("behavior") if isinstance(raw.get("behavior"), dict) else {}
    try:
        forget_inactive_days = max(0, int(behavior.get("forget_inactive_days", 90)))
    except (TypeError, ValueError):
        forget_inactive_days = 90
    return {
        "schema_version": 2,
        "enabled": _bool(raw.get("enabled"), True),
        "learn_from_chats": _bool(raw.get("learn_from_chats"), True),
        "categories": categories,
        "behavior": {
            "ask_before_sensitive": _bool(behavior.get("ask_before_sensitive"), True),
            "forget_inactive_days": forget_inactive_days,
            "prevent_personal_canon": _bool(behavior.get("prevent_personal_canon"), True),
        },
        # Keep legacy readers coherent while the v2 policy rolls through the app.
        "creative_preferences": categories["collaboration_preferences"]["enabled"],
        "reusable_personas": categories["story_presence"]["enabled"],
    }


def normalize_user_profile(profile: Any, profile_id: str = "default") -> dict[str, Any]:
    raw = dict(profile) if isinstance(profile, dict) else {}
    normalized = {
        **raw,
        "id": str(raw.get("id") or profile_id),
        "display_name": str(raw.get("display_name") or "").strip(),
        "about": str(raw.get("about") or ""),
        "personal_details": dict(raw.get("personal_details") or {}),
        "creative_profile": dict(raw.get("creative_profile") or {}),
        "collaboration": dict(raw.get("collaboration") or {}),
        "presence_defaults": dict(raw.get("presence_defaults") or {}),
        "story_lab": dict(raw.get("story_lab") or {}),
        "boundaries": dict(raw.get("boundaries") or {"prefer": [], "avoid": [], "ask_before": []}),
        "memory_policy": normalize_memory_policy(raw.get("memory_policy")),
    }
    names = normalize_preferred_names(normalized)
    normalized["preferred_names"] = names
    primary = next((item for item in names if item["primary"]), None)
    if primary:
        normalized["display_name"] = primary["value"]
        normalized["personal_details"]["preferred_name"] = {
            **(normalized["personal_details"].get("preferred_name") or {}),
            "value": primary["value"],
            "visibility": "collaboration",
        }
    return normalized


def resolve_preferred_name(profile: dict[str, Any], context: str = "default") -> str:
    names = normalize_preferred_names(profile)
    contextual = next((item for item in names if item["context"] == context and not item["primary"]), None)
    primary = next((item for item in names if item["primary"]), None)
    return str((contextual or primary or {}).get("value") or profile.get("display_name") or "User")


def build_personalization_context(
    profile: dict[str, Any],
    conversation_mode: str,
    prompt: str = "",
) -> dict[str, Any]:
    """Compile only personal data allowed by the user's memory policy."""
    normalized = normalize_user_profile(profile)
    policy = normalized["memory_policy"]
    if not policy["enabled"]:
        return {"memory_enabled": False, "learn_from_chat": False}
    categories = policy["categories"]
    context_name = {
        "story_lab": "casual", "analyst": "formal", "interactive": "story_presence", "character_room": "casual",
    }.get(conversation_mode, "default")
    result: dict[str, Any] = {
        "memory_enabled": True,
        "learn_from_chat": policy["learn_from_chats"],
        "preferred_name": resolve_preferred_name(normalized, context_name),
        "name_context": context_name,
        "prevent_personal_canon": policy["behavior"]["prevent_personal_canon"],
    }
    if categories["collaboration_preferences"]["enabled"]:
        result["creative_profile"] = normalized["creative_profile"]
        result["collaboration"] = normalized["collaboration"]
        result["boundaries"] = normalized["boundaries"]
    if categories["about_you"]["enabled"]:
        result["about"] = normalized["about"]
        allowed = {"collaboration"}
        direct_self_query = bool(re.search(
            r"\b(?:who am i|what do you know about me|tell me about myself|siapa aku|kamu tahu apa tentang aku|tentang diriku)\b",
            prompt,
            flags=re.IGNORECASE,
        ))
        if categories["story_presence"]["enabled"] and (
            conversation_mode in {"interactive", "character_room"} or direct_self_query
        ):
            allowed.add("story_presence")
        result["personal_details"] = {
            key: detail.get("value")
            for key, detail in normalized["personal_details"].items()
            if isinstance(detail, dict) and detail.get("value") and detail.get("visibility") in allowed
        }
    if categories["story_presence"]["enabled"] and conversation_mode in {"interactive", "character_room"}:
        result["presence_defaults"] = normalized["presence_defaults"]
    return result


def _clean(text: str) -> str:
    value = html.unescape(text).replace("\u00a0", " ")
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"__([^_]+)__", r"\1", value)
    value = re.sub(r"[ \t]+", " ", value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"(?<=[.!?])\s+|\n+", text) if item.strip()]


def _field(
    key: str,
    label: str,
    value: str,
    *,
    visibility: str,
    confidence: float,
    source: str,
    sensitive: bool = False,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": value.strip(),
        "visibility": visibility,
        "confidence": confidence,
        "source": source.strip(),
        "sensitive": sensitive,
        "included": True,
    }


def _join(items: list[str]) -> str:
    return " ".join(dict.fromkeys(item.strip() for item in items if item.strip()))


def extract_profile_draft(text: str) -> dict[str, Any]:
    """Extract a conservative, editable profile draft from Indonesian or English prose.

    This intentionally does not save anything and keeps the original wording for
    descriptive fields. Low-risk identity patterns are structured; ambiguous facts
    remain editable prose instead of being invented.
    """
    cleaned = _clean(text)
    sentences = _sentences(cleaned)
    fields: list[dict[str, Any]] = []
    consumed: set[int] = set()

    full_name = ""
    preferred_name = ""
    name_source = ""
    name_patterns = [
        r"(?:namaku|nama saya|nama lengkap(?:ku| saya)?|my name is)\s+([^,.]+?)(?:,|\.|$)",
    ]
    preferred_patterns = [
        r"(?:dipanggil|panggil(?:lah)?(?: aku| saya)?|called|go by)\s+([^,.]+?)(?:,|\.|$)",
    ]
    for index, sentence in enumerate(sentences):
        for pattern in name_patterns:
            match = re.search(pattern, sentence, flags=re.IGNORECASE)
            if match:
                full_name = match.group(1).strip(" '\"")
                name_source = sentence
                consumed.add(index)
                break
        for pattern in preferred_patterns:
            match = re.search(pattern, sentence, flags=re.IGNORECASE)
            if match:
                preferred_name = match.group(1).strip(" '\"")
                name_source = sentence
                consumed.add(index)
                break
        if full_name or preferred_name:
            break
    if full_name:
        fields.append(_field("full_name", "Full name", full_name, visibility="private", confidence=.98, source=name_source))
    if preferred_name:
        fields.append(_field("preferred_name", "Preferred name", preferred_name, visibility="collaboration", confidence=.98, source=name_source))

    for index, sentence in enumerate(sentences):
        match = re.search(r"(?:lahir(?: pada)?|born(?: on)?)\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", sentence, flags=re.IGNORECASE)
        if match and match.group(2).lower() in _MONTHS:
            value = f"{int(match.group(3)):04d}-{_MONTHS[match.group(2).lower()]:02d}-{int(match.group(1)):02d}"
            fields.append(_field("birth_date", "Birth date", value, visibility="private", confidence=.99, source=sentence, sensitive=True))
            consumed.add(index)
            break

    for index, sentence in enumerate(sentences):
        match = re.search(r"(?:tinggi(?: badan)?(?:ku| saya)?(?: sekitar)?|height(?: is| around)?)\s*(?:sekitar|about|approximately)?\s*(\d{2,3})\s*(?:cm|sentimeter)", sentence, flags=re.IGNORECASE)
        if match:
            fields.append(_field("height_cm", "Height (cm)", match.group(1), visibility="story_presence", confidence=.99, source=sentence))
            consumed.add(index)
            break

    appearance: list[str] = []
    presentation: list[str] = []
    skills: list[str] = []
    sensitive: list[str] = []
    general: list[str] = []
    for index, sentence in enumerate(sentences):
        if index in consumed:
            continue
        lowered = sentence.lower()
        if re.search(r"\b(dada|payudara|breasts?|cup)\b", lowered):
            sensitive.append(sentence)
        elif re.search(r"voice acting|kontrol suara|warna suara|intonasi|cara bicara|vocal|suara perempuan|female voice", lowered):
            skills.append(sentence)
        elif re.search(r"kemben|pakaian|kampus|menyamarkan|berpakaian|tampil sebagai|terlihat seperti|presentasi diri|sehari-hari|keseharian", lowered):
            presentation.append(sentence)
        elif re.search(r"secara fisik|bentuk tubuh|tubuhku|tubuh saya|pinggul|kaki|tangan|wajah|rambut|proporsi|ramping|maskulin|feminin|appearance|physique|hair|face", lowered):
            appearance.append(sentence)
        else:
            general.append(sentence)

    if appearance:
        fields.append(_field("appearance", "Appearance", _join(appearance), visibility="story_presence", confidence=.88, source=_join(appearance)))
    if presentation:
        fields.append(_field("presentation", "Everyday presentation", _join(presentation), visibility="story_presence", confidence=.86, source=_join(presentation)))
    if skills:
        fields.append(_field("skills", "Skills and abilities", _join(skills), visibility="collaboration", confidence=.9, source=_join(skills)))
    if sensitive:
        fields.append(_field("sensitive_details", "Private physical details", _join(sensitive), visibility="private", confidence=.92, source=_join(sensitive), sensitive=True))
    if general:
        fields.append(_field("notes", "Additional notes", _join(general), visibility="private", confidence=.65, source=_join(general)))

    return {
        "display_name": preferred_name or full_name.split(" ", 1)[0] if full_name else preferred_name,
        "fields": fields,
        "source_length": len(cleaned),
    }
