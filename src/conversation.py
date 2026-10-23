from __future__ import annotations

import re
from typing import Any


MODE_RECIPES = {
    "story_writer": "RECIPE-STORY",
    "story_lab": "RECIPE-LAB",
    "interactive": "RECIPE-INTERACTIVE",
    "analyst": "RECIPE-ANALYST",
    "character_room": "RECIPE-CHARACTER-ROOM",
}

_STORY_LAB_PROSE_COMMANDS = {"continue", "rewrite", "mono", "dia", "ambience", "intimacy", "describe"}
STORY_LAB_DISCUSSION_SYSTEM = (
    "You are Arline in Story Lab, a conversational workspace for developing stories with "
    "the author. Speak directly with the author as a collaborative "
    "story and character designer. Your default output is natural brainstorming dialogue, "
    "not fiction. Never turn a design question into scene narration or invented character "
    "dialogue unless the author explicitly asks you to write prose. Ideas discussed here are "
    "provisional and non-canonical. Use ordinary conversational paragraphs by default: no "
    "headings, bullet lists, numbered options, bracketed labels, context-system terminology, "
    "or menus of alternatives unless the author asks for structured output. Develop the most "
    "promising interpretation instead of making the author choose from A/B/C options. Remember "
    "and build on the actual dialogue included in the request. Distinguish exploratory ideas, "
    "decisions, and open questions without announcing internal machinery. If the author asks who "
    "they are or what you know about them, answer from the authorized personalization context. "
    "If the conversation contract assigns you an assistant alias, treat the author's direct use "
    "of that name as addressing you, not as introducing a story character. Display it as your "
    "conversation name without changing your behavior, the Arline Studio product, or story canon. "
    "Ask at most one natural question if a decision is genuinely needed."
)

STORY_LAB_PROSE_SYSTEM = (
    "This Story Lab turn explicitly asks for fiction. Write the requested prose now. "
    "Output only the fiction itself: do not discuss the premise, restate the request, "
    "offer writing advice, explain what you are about to write, or ask a follow-up question. "
    "Begin inside the requested scene, chapter, passage, dialogue, monologue, or description. "
    "Honor the requested length, language, point of view, and constraints."
)


def story_lab_prose_intent_warnings(prompt: str, response: str) -> list[dict[str, str]]:
    """Flag obvious meta-discussion when an explicit Story Lab prose request was made."""
    if not story_lab_requests_prose(prompt):
        return []
    opening = " ".join(response.strip().split())[:320]
    meta_patterns = (
        r"^(?:okay|sure|alright)[,!.]?\s+(?:so\s+)?(?:let(?:'s| us)|you want|i(?:'ll| will)|here(?:'s| is))\b",
        r"^(?:let(?:'s| us)|you want|the (?:idea|concept|request)|this (?:idea|concept|premise))\b",
        r"^(?:baik|oke|tentu)[,!.]?\s+(?:jadi\s+)?(?:mari|kita|aku akan|saya akan)\b",
    )
    for pattern in meta_patterns:
        match = re.search(pattern, opening, flags=re.IGNORECASE)
        if match:
            return [{
                "type": "story_lab_prose_not_started",
                "severity": "warning",
                "example": match.group(0),
            }]
    return []


def story_lab_requests_prose(prompt: str) -> bool:
    """Return true only when Story Lab receives an explicit prose-writing request."""
    text = prompt.strip()
    command = re.match(r"^/([a-z_][a-z0-9_-]*)", text, flags=re.IGNORECASE)
    if command:
        return command.group(1).lower() in _STORY_LAB_PROSE_COMMANDS
    patterns = (
        r"^(?:please\s+)?(?:write|draft|rewrite)\s+(?:me\s+)?(?:the\s+|a\s+|this\s+)?(?:(?:short|brief|long|full|quick|small|complete|polished)\s+){0,2}(?:scene|chapter|passage|prose|dialogue|monologue|description)\b",
        r"^(?:please\s+)?continue\s+(?:the\s+|this\s+)?(?:scene|chapter|story|passage)\b",
        r"^(?:can|could|would)\s+you\s+(?:please\s+)?(?:write|draft|rewrite|continue)\b",
        r"^(?:tolong\s+)?(?:tulis|tuliskan|buatkan|drafkan|draftkan|tulis ulang)\s+(?:sebuah\s+)?(?:adegan|bab|dialog|prosa|monolog|deskripsi)\b",
        r"^(?:tolong\s+)?lanjutkan\s+(?:adegan|bab|cerita|bagian)\b",
        r"^(?:bisa|bisakah|dapatkah)\s+(?:kamu\s+)?(?:menulis|buatkan|melanjutkan|tulis ulang)\b",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def recipe_for_mode(mode: str, explicit_recipe_id: str | None = None) -> str:
    return explicit_recipe_id or MODE_RECIPES.get(mode, "RECIPE-STORY")


def resolve_presence(profile: dict[str, Any]) -> dict[str, Any]:
    presence = dict(profile.get("presence") or {})
    perspective = dict(profile.get("perspective") or {})
    mode = presence.get("mode") or "observer"
    return {
        "mode": mode,
        "display_name": presence.get("display_name") or ("Observer" if mode == "observer" else "User"),
        "entity_variant_id": presence.get("entity_variant_id"),
        "identity_style": presence.get("identity_style") or "blended",
        "control_policy": "user_directed",
        "first_person_refers_to": "active_user_presence" if mode != "observer" else "narrator",
        "second_person_refers_to": "active_user_presence" if mode != "observer" else "reader",
        "pov_variant_id": perspective.get("pov_entity_id"),
        "pov_style": perspective.get("style") or "scene_defined",
    }


def extract_blueprint(text: str, current: dict[str, Any] | None = None) -> dict[str, Any]:
    """Conservatively classify explicit intent; ambiguous statements stay suggested."""
    result = {key: list((current or {}).get(key) or []) for key in (
        "wanted", "flexible", "suggested", "avoid", "open_questions",
        "narrative_desires", "relationship_intentions",
    )}
    clauses = [part.strip(" \t\r\n-.,") for part in re.split(r"[;\n]+", text) if part.strip()]
    for clause in clauses:
        lowered = clause.lower()
        target = "suggested"
        value = clause
        patterns = (
            ("avoid", r"^(?:i\s+)?(?:do not|don't|never|avoid|without|no)\s+(.+)$"),
            ("wanted", r"^(?:i\s+)?(?:want|need|would like|i'd like|prefer)\s+(?:to\s+)?(.+)$"),
            ("flexible", r"^(?:i(?:'m| am)?\s+)?(?:am\s+)?(?:open to|flexible about|maybe|could)\s+(.+)$"),
        )
        for bucket, pattern in patterns:
            match = re.match(pattern, lowered, re.I)
            if match:
                target, value = bucket, match.group(1).strip()
                break
        if value and value not in result[target]:
            result[target].append(value)
    return result


def validate_user_agency(story: str, profile: dict[str, Any]) -> list[dict[str, Any]]:
    presence = resolve_presence(profile)
    if presence["mode"] == "observer":
        return []
    patterns = {
        "invented_user_dialogue": r'\b(?:you|you then)\s+(?:say|reply|promise|agree|confess)\b|[“\"](?:[^”\"]{2,80})[”\"],?\s+you\s+(?:say|reply)',
        "invented_user_decision": r"\byou\s+(?:decide|choose|accept|refuse|promise|agree|commit)\b",
        "invented_private_belief": r"\byou\s+(?:realize|believe|know|want|feel certain)\b",
    }
    warnings = []
    for kind, pattern in patterns.items():
        hit = re.search(pattern, story, re.I)
        if hit:
            warnings.append({"type": kind, "example": hit.group(0), "severity": "warning"})
    return warnings
