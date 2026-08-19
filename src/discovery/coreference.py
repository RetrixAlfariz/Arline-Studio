from __future__ import annotations

from dataclasses import dataclass, asdict
import re
from typing import Any

from src.memory.models import MemoryQueryContext

from .identity import normalize_identity_label


SELF_REFERENCES = {
    "self", "aku", "saya", "gue", "gua", "i", "me", "myself", "my",
}
THIRD_PERSON_REFERENCES = {
    "dia", "ia", "he", "she", "him", "her", "they", "them", "character", "person",
}
GENERIC_REFERENCES = SELF_REFERENCES | THIRD_PERSON_REFERENCES | {
    "someone", "somebody", "unknown", "it", "itu", "tadi",
}


@dataclass(slots=True)
class CoreferenceResolution:
    state: str
    subject_key: str | None = None
    subject_label: str | None = None
    candidates: list[dict[str, str]] | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["candidates"] = payload.get("candidates") or []
        return payload


class CrossTurnCoreferenceResolver:
    """Precision-first bounded coreference for narrative entity mentions.

    This is deliberately not a fuzzy NLP resolver. It only resolves references
    when a unique narrative anchor is supported by current or visible recent
    context. Ambiguous candidate sets remain unresolved and are persisted for
    diagnostics instead of being guessed into continuity.
    """

    SELF_INTRO_PATTERNS = (
        re.compile(r"\b(?:namaku|nama\s+saya|aku\s+bernama|saya\s+bernama)\s+([\w'’-]+)", re.I),
        re.compile(r"\b(?:my\s+name\s+is|i\s+am|i['’]m)\s+([\w'’-]+)", re.I),
    )

    def __init__(self, service):
        self.service = service

    def self_labels(self, text: str) -> set[str]:
        output: set[str] = set()
        for pattern in self.SELF_INTRO_PATTERNS:
            for match in pattern.finditer(text or ""):
                output.add(normalize_identity_label(match.group(1)))
        return output

    def _context(self, source: dict[str, Any]) -> MemoryQueryContext:
        return MemoryQueryContext(
            project_id=source.get("project_id"),
            world_id=source.get("world_id"),
            branch_id=source.get("branch_id"),
            session_id=source.get("session_id"),
            current_turn_id=source.get("turn_id"),
            world_time=source.get("world_time"),
            story_order=source.get("story_order"),
            context_lens="scene",
            retrieval_mode="continuity",
        )

    def _recent_self(self, source: dict[str, Any]) -> list[dict[str, str]]:
        with self.service.store.connection() as con:
            rows = con.execute(
                "SELECT resolved_subject_key,resolved_label FROM discovery_mentions "
                "WHERE active=1 AND mention_role='self' AND resolution_state='resolved' "
                "AND source_session_id IS ? AND project_id IS ? AND world_id IS ? "
                "AND resolved_subject_key IS NOT NULL ORDER BY created_at DESC LIMIT 8",
                (source.get("session_id"), source.get("project_id"), source.get("world_id")),
            ).fetchall()
        seen: dict[str, dict[str, str]] = {}
        for row in rows:
            key = str(row["resolved_subject_key"] or "")
            if key and key not in seen:
                seen[key] = {"subject_key": key, "subject_label": str(row["resolved_label"] or key)}
        return list(seen.values())

    def _recent_characters(self, source: dict[str, Any], *, limit: int = 48) -> list[dict[str, str]]:
        context = self._context(source)
        with self.service.store.connection() as con:
            rows = con.execute(
                "SELECT DISTINCT p.* FROM discovery_propositions p "
                "JOIN discovery_instances i ON i.proposition_id=p.id "
                "WHERE p.subject_type='character' AND p.authority_state!='dismissed' "
                "AND i.active=1 AND p.project_id IS ? AND p.world_id IS ? "
                "ORDER BY i.created_at DESC LIMIT ?",
                (source.get("project_id"), source.get("world_id"), max(1, int(limit))),
            ).fetchall()
        output: list[dict[str, str]] = []
        seen: set[str] = set()
        for row in rows:
            prop = self.service.store._prop_row(row)
            key = str(prop.get("subject_key") or "")
            if not key or key in seen:
                continue
            evaluated = self.service.evaluate_proposition(prop, context)
            if evaluated.get("knowledge_state") != "canon" and int(evaluated.get("support_count") or 0) <= 0:
                continue
            seen.add(key)
            output.append({"subject_key": key, "subject_label": str(prop.get("subject_label") or key)})
        return output[:8]

    def resolve(
        self,
        *,
        surface: str,
        entity_type: str,
        source: dict[str, Any],
        current_named: list[dict[str, str]],
        self_named: list[dict[str, str]],
    ) -> CoreferenceResolution:
        needle = normalize_identity_label(surface)
        if entity_type != "character":
            return CoreferenceResolution(state="unresolved", reason="generic_non_character_reference")

        if needle in SELF_REFERENCES:
            candidates = self_named or self._recent_self(source)
            unique = {item["subject_key"]: item for item in candidates if item.get("subject_key")}
            if len(unique) == 1:
                chosen = next(iter(unique.values()))
                return CoreferenceResolution(
                    state="resolved", subject_key=chosen["subject_key"],
                    subject_label=chosen["subject_label"], candidates=list(unique.values()),
                    reason="unique_self_anchor",
                )
            return CoreferenceResolution(
                state="ambiguous" if len(unique) > 1 else "unresolved",
                candidates=list(unique.values()), reason="self_anchor_not_unique",
            )

        if needle in THIRD_PERSON_REFERENCES or needle in GENERIC_REFERENCES:
            candidates = current_named or self._recent_characters(source)
            unique = {item["subject_key"]: item for item in candidates if item.get("subject_key")}
            if len(unique) == 1:
                chosen = next(iter(unique.values()))
                return CoreferenceResolution(
                    state="resolved", subject_key=chosen["subject_key"],
                    subject_label=chosen["subject_label"], candidates=list(unique.values()),
                    reason="unique_recent_character",
                )
            return CoreferenceResolution(
                state="ambiguous" if len(unique) > 1 else "unresolved",
                candidates=list(unique.values()), reason="recent_character_not_unique",
            )

        return CoreferenceResolution(state="unresolved", reason="unsupported_reference")
