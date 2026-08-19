from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import re
import unicodedata
from typing import Any

from .identity import normalize_identity_label, resolve_existing_family


TYPE_MAP = {
    "character": "character",
    "location": "location",
    "item": "item",
    "garment": "item",
    "organization": "organization",
    "lore": "lore",
    "world_rule": "world_rule",
}
FIRST_PERSON = {"aku", "saya", "i", "me", "my", "self", "myself", "-ku", "ku"}
THIRD_PERSON = {"dia", "ia", "he", "she", "him", "her", "it", "-nya", "nya", "itu"}
PLURAL_PERSON = {"mereka", "they", "them", "their"}
GENERIC = {
    "character", "person", "someone", "somebody", "unknown",
    "feminine_clothing", "underwear_set", "self_family",
}
SELF_NAME_RE = re.compile(
    r"(?:\bnamaku\b|\bnama\s+saya\b|\baku\s+bernama\b|\bsaya\s+bernama\b|"
    r"\bmy\s+name\s+is\b|\bi\s+am\s+called\b)\s+"
    r"(?P<name>[\wÀ-ÿ.'’\-]+(?:\s+[\wÀ-ÿ.'’\-]+){0,3})(?=\s*[,.;!?\n]|$)",
    re.I,
)


def _slug(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "unknown"


def default_anchor(entity_type: str, label: str) -> str:
    prefix = {
        "character": "char", "location": "loc", "item": "item",
        "garment": "item", "organization": "org", "lore": "lore",
        "world_rule": "rule",
    }.get(entity_type, "entity")
    return f"{prefix}:{_slug(label)}"


@dataclass(slots=True)
class ResolutionResult:
    surface: str
    entity_type: str
    raw_subject_key: str
    subject_key: str | None
    subject_label: str
    resolution_kind: str
    confidence: float
    target_resource_type: str | None = None
    target_resource_id: str | None = None
    ambiguous_candidates: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return bool(self.subject_key)

    def to_dict(self) -> dict[str, Any]:
        item = asdict(self)
        item["resolved"] = self.resolved
        item["ambiguous_candidates"] = list(self.ambiguous_candidates)
        return item


class NarrativeEntityResolver:
    """Conservative identity + bounded coreference gate for Discovery.

    Extractors are allowed to propose labels and temporary keys, but only this
    resolver decides the stable subject anchor persisted into propositions.
    It never fuzzy-merges identities. Ambiguous references are recorded as
    diagnostics and deliberately remain unresolved.
    """

    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.workspace = service.workspace
        self.foundation = service.foundation

    def _record(self, result: ResolutionResult, *, project_id: str | None,
                world_id: str | None, branch_id: str | None, session_id: str | None,
                turn_id: str | None, source_kind: str, span_start: int | None,
                span_end: int | None) -> ResolutionResult:
        self.store.record_mention(
            project_id=project_id, world_id=world_id, branch_id=branch_id,
            session_id=session_id, source_turn_id=turn_id, source_kind=source_kind,
            surface=result.surface, entity_type=result.entity_type,
            raw_subject_key=result.raw_subject_key,
            resolved_subject_key=result.subject_key,
            target_resource_type=result.target_resource_type,
            target_resource_id=result.target_resource_id,
            resolution_kind=result.resolution_kind,
            confidence=result.confidence,
            ambiguous_candidates=list(result.ambiguous_candidates),
            span_start=span_start, span_end=span_end,
        )
        return result

    def _existing_anchor(self, *, project_id: str | None, world_id: str | None,
                         raw_key: str, label: str, entity_type: str) -> ResolutionResult | None:
        linked = self.store.get_subject_link(
            project_id=project_id, world_id=world_id, subject_key=raw_key
        )
        if linked:
            return ResolutionResult(
                surface=label, entity_type=entity_type, raw_subject_key=raw_key,
                subject_key=raw_key, subject_label=label,
                resolution_kind="existing_anchor", confidence=1.0,
                target_resource_type=linked.get("resource_type"),
                target_resource_id=linked.get("resource_id"),
            )

        mapped = TYPE_MAP.get(entity_type, entity_type)
        family = resolve_existing_family(self.workspace, self.foundation, label, mapped)
        if family is None:
            return None
        canonical_key = self.store.find_subject_key_for_resource(
            project_id=project_id, world_id=world_id,
            resource_type="entity_family", resource_id=family["id"],
        ) or raw_key
        self.store.upsert_subject_link(
            project_id=project_id, world_id=world_id, subject_key=canonical_key,
            resource_type="entity_family", resource_id=family["id"],
        )
        return ResolutionResult(
            surface=label, entity_type=entity_type, raw_subject_key=raw_key,
            subject_key=canonical_key, subject_label=label,
            resolution_kind="library_exact", confidence=1.0,
            target_resource_type="entity_family", target_resource_id=family["id"],
        )

    def _recent(self, *, session_id: str | None, branch_id: str | None,
                turn_id: str | None, entity_type: str | None = None,
                same_turn: bool | None = None) -> list[dict[str, Any]]:
        if not session_id:
            return []
        rows = self.store.recent_mentions(
            session_id=session_id, branch_id=branch_id,
            entity_type=entity_type, limit=32,
        )
        if same_turn is True:
            rows = [row for row in rows if row.get("source_turn_id") == turn_id]
        elif same_turn is False:
            rows = [row for row in rows if row.get("source_turn_id") != turn_id]
        return rows

    @staticmethod
    def _candidate_keys(rows: list[dict[str, Any]], *, cap: int = 8) -> list[str]:
        out: list[str] = []
        for row in rows:
            key = str(row.get("resolved_subject_key") or "")
            surface = normalize_identity_label(row.get("surface") or "")
            if not key or surface in FIRST_PERSON | THIRD_PERSON | PLURAL_PERSON | GENERIC:
                continue
            if key not in out:
                out.append(key)
            if len(out) >= cap:
                break
        return out

    def _self_explicit(self, source_text: str) -> str | None:
        match = SELF_NAME_RE.search(source_text or "")
        return " ".join(match.group("name").strip().split()) if match else None

    def resolve(self, *, project_id: str | None, world_id: str | None,
                branch_id: str | None, session_id: str | None, turn_id: str | None,
                source_kind: str, source_text: str, entity_type: str,
                raw_subject_key: str | None, label: str,
                span_start: int | None = None, span_end: int | None = None,
                record: bool = True) -> ResolutionResult:
        surface = " ".join(str(label or "").strip().split())
        entity_type = str(entity_type or "entity").strip() or "entity"
        raw_key = str(raw_subject_key or default_anchor(entity_type, surface or "unknown"))
        norm = normalize_identity_label(surface)

        def done(result: ResolutionResult) -> ResolutionResult:
            if record:
                return self._record(
                    result, project_id=project_id, world_id=world_id,
                    branch_id=branch_id, session_id=session_id, turn_id=turn_id,
                    source_kind=source_kind, span_start=span_start, span_end=span_end,
                )
            return result

        # Explicit named identities always outrank anaphora.
        if norm and norm not in FIRST_PERSON | THIRD_PERSON | PLURAL_PERSON | GENERIC:
            existing = self._existing_anchor(
                project_id=project_id, world_id=world_id, raw_key=raw_key,
                label=surface, entity_type=entity_type,
            )
            if existing:
                return done(existing)
            # Reuse a same-turn stable anchor when separate extractors emitted
            # different temporary keys for the exact same mention.
            same = self._recent(
                session_id=session_id, branch_id=branch_id, turn_id=turn_id,
                entity_type=entity_type, same_turn=True,
            )
            matches = {
                str(row.get("resolved_subject_key"))
                for row in same
                if normalize_identity_label(row.get("surface") or "") == norm
                and row.get("resolved_subject_key")
            }
            if len(matches) == 1:
                key = next(iter(matches))
                return done(ResolutionResult(
                    surface=surface, entity_type=entity_type, raw_subject_key=raw_key,
                    subject_key=key, subject_label=surface,
                    resolution_kind="same_turn_exact", confidence=0.99,
                ))
            return done(ResolutionResult(
                surface=surface, entity_type=entity_type, raw_subject_key=raw_key,
                subject_key=raw_key, subject_label=surface,
                resolution_kind="new_anchor", confidence=0.92,
            ))

        # First-person self only becomes resolvable after an explicit narrator
        # identity has been stated in the session. We never assume the only
        # character in a story is the narrator.
        if norm in FIRST_PERSON or norm in {"self", "self_family"}:
            explicit_name = self._self_explicit(source_text)
            if explicit_name:
                named = self.resolve(
                    project_id=project_id, world_id=world_id, branch_id=branch_id,
                    session_id=session_id, turn_id=turn_id, source_kind=source_kind,
                    source_text=source_text, entity_type="character",
                    raw_subject_key=default_anchor("character", explicit_name),
                    label=explicit_name, span_start=span_start, span_end=span_end,
                    record=True,
                )
                return done(ResolutionResult(
                    surface=surface or "self", entity_type="character",
                    raw_subject_key=raw_key, subject_key=named.subject_key,
                    subject_label=named.subject_label, resolution_kind="self_explicit",
                    confidence=1.0, target_resource_type=named.target_resource_type,
                    target_resource_id=named.target_resource_id,
                ))
            recent = self._recent(
                session_id=session_id, branch_id=branch_id, turn_id=turn_id,
                entity_type="character", same_turn=None,
            )
            narrator = next(
                (row for row in recent if row.get("resolution_kind") == "self_explicit"
                 and row.get("resolved_subject_key")), None
            )
            if narrator:
                return done(ResolutionResult(
                    surface=surface or "self", entity_type="character",
                    raw_subject_key=raw_key,
                    subject_key=str(narrator["resolved_subject_key"]),
                    subject_label=str(narrator.get("resolved_label") or narrator.get("surface") or "self"),
                    resolution_kind="self_recent", confidence=0.98,
                    target_resource_type=narrator.get("target_resource_type"),
                    target_resource_id=narrator.get("target_resource_id"),
                ))
            return done(ResolutionResult(
                surface=surface or "self", entity_type="character",
                raw_subject_key=raw_key, subject_key=None, subject_label=surface or "self",
                resolution_kind="unresolved_self", confidence=0.0,
            ))

        if norm in PLURAL_PERSON:
            return done(ResolutionResult(
                surface=surface, entity_type=entity_type, raw_subject_key=raw_key,
                subject_key=None, subject_label=surface,
                resolution_kind="unresolved_plural", confidence=0.0,
            ))

        if norm in THIRD_PERSON or norm in GENERIC:
            wanted_type = "character" if norm in {"dia", "ia", "he", "she", "him", "her"} else None
            # Same-turn candidates first, then bounded prior-turn candidates.
            same = self._candidate_keys(self._recent(
                session_id=session_id, branch_id=branch_id, turn_id=turn_id,
                entity_type=wanted_type, same_turn=True,
            ))
            candidates = same or self._candidate_keys(self._recent(
                session_id=session_id, branch_id=branch_id, turn_id=turn_id,
                entity_type=wanted_type, same_turn=False,
            ))
            if len(candidates) == 1:
                key = candidates[0]
                rows = self.store.recent_mentions(
                    session_id=session_id, branch_id=branch_id,
                    entity_type=wanted_type, limit=32,
                )
                source = next((row for row in rows if row.get("resolved_subject_key") == key), {})
                return done(ResolutionResult(
                    surface=surface, entity_type=str(source.get("entity_type") or entity_type),
                    raw_subject_key=raw_key, subject_key=key,
                    subject_label=str(source.get("resolved_label") or source.get("surface") or key),
                    resolution_kind="coreference_same_turn" if same else "coreference_recent",
                    confidence=0.9 if same else 0.82,
                    target_resource_type=source.get("target_resource_type"),
                    target_resource_id=source.get("target_resource_id"),
                ))
            if len(candidates) > 1:
                return done(ResolutionResult(
                    surface=surface, entity_type=entity_type, raw_subject_key=raw_key,
                    subject_key=None, subject_label=surface,
                    resolution_kind="ambiguous_coreference", confidence=0.0,
                    ambiguous_candidates=tuple(candidates),
                ))
            return done(ResolutionResult(
                surface=surface, entity_type=entity_type, raw_subject_key=raw_key,
                subject_key=None, subject_label=surface,
                resolution_kind="unresolved_coreference", confidence=0.0,
            ))

        return done(ResolutionResult(
            surface=surface, entity_type=entity_type, raw_subject_key=raw_key,
            subject_key=raw_key, subject_label=surface or raw_key,
            resolution_kind="new_anchor", confidence=0.8,
        ))
