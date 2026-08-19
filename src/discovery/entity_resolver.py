from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
from typing import Any

from .coreference import GENERIC_REFERENCES, CrossTurnCoreferenceResolver
from .identity import linked_subject_keys, normalize_identity_label, resolve_existing_family
from .store import dumps, utc_now


INSTANCE_SENSITIVE_TYPES = {"item", "garment"}
GENERIC_LABELS = GENERIC_REFERENCES | {
    "feminine_clothing", "underwear_set", "self_family",
}


@dataclass(slots=True)
class EntityResolution:
    raw_key: str
    raw_label: str
    entity_type: str
    subject_key: str
    subject_label: str
    state: str
    reason: str
    resource_id: str | None = None
    candidates: list[dict[str, str]] | None = None
    mention_role: str = "explicit"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["candidates"] = payload.get("candidates") or []
        return payload


@dataclass(slots=True)
class ResolvedEntityFrame:
    entities: dict[str, dict[str, Any]]
    key_map: dict[str, str]
    resolutions: dict[str, EntityResolution]


class NarrativeEntityResolver:
    """Resolve extractor-local entity ids into stable narrative anchors.

    Exact Library identity, existing Discovery links and exact prior labels are
    allowed. Physical items remain instance-sensitive. Fuzzy merging is never
    performed. Generic narrator/pronoun entities are delegated to the bounded
    cross-turn coreference resolver.
    """

    def __init__(self, service, coreference: CrossTurnCoreferenceResolver):
        self.service = service
        self.coreference = coreference

    @staticmethod
    def _mapped_type(entity_type: str) -> str:
        return "item" if entity_type == "garment" else entity_type

    def _linked_key_for_family(self, source: dict[str, Any], family_id: str) -> str:
        keys = linked_subject_keys(
            self.service.store,
            project_id=source.get("project_id"), world_id=source.get("world_id"), family_id=family_id,
        )
        if len(keys) == 1:
            return keys[0]
        return f"entity:{family_id}"

    def _prior_exact_subject(self, *, source: dict[str, Any], label: str, entity_type: str) -> list[dict[str, str]]:
        needle = normalize_identity_label(label)
        if not needle:
            return []
        with self.service.store.connection() as con:
            rows = con.execute(
                "SELECT DISTINCT subject_key,subject_label FROM discovery_propositions "
                "WHERE project_id IS ? AND world_id IS ? AND subject_type=? AND authority_state!='dismissed' "
                "ORDER BY updated_at DESC LIMIT 100",
                (source.get("project_id"), source.get("world_id"), entity_type),
            ).fetchall()
        matches: dict[str, dict[str, str]] = {}
        for row in rows:
            if normalize_identity_label(row["subject_label"] or "") != needle:
                continue
            key = str(row["subject_key"] or "")
            if key:
                matches[key] = {"subject_key": key, "subject_label": str(row["subject_label"] or label)}
        return list(matches.values())

    def _explicit(self, *, raw_key: str, label: str, entity_type: str, source: dict[str, Any]) -> EntityResolution:
        mapped = self._mapped_type(entity_type)
        if entity_type in INSTANCE_SENSITIVE_TYPES:
            link = self.service.store.get_subject_link(
                project_id=source.get("project_id"), world_id=source.get("world_id"), subject_key=raw_key
            )
            return EntityResolution(
                raw_key=raw_key, raw_label=label, entity_type=entity_type,
                subject_key=raw_key, subject_label=label, state="resolved",
                reason="instance_sensitive_anchor", resource_id=link.get("resource_id") if link else None,
            )

        family = resolve_existing_family(self.service.workspace, self.service.foundation, label, mapped)
        if family:
            key = self._linked_key_for_family(source, str(family["id"]))
            self.service.store.upsert_subject_link(
                project_id=source.get("project_id"), world_id=source.get("world_id"),
                subject_key=key, resource_type="entity_family", resource_id=family["id"],
            )
            return EntityResolution(
                raw_key=raw_key, raw_label=label, entity_type=entity_type,
                subject_key=key, subject_label=str(family.get("name") or label),
                state="resolved", reason="exact_library_identity", resource_id=str(family["id"]),
            )

        prior = self._prior_exact_subject(source=source, label=label, entity_type=entity_type)
        if len(prior) == 1:
            return EntityResolution(
                raw_key=raw_key, raw_label=label, entity_type=entity_type,
                subject_key=prior[0]["subject_key"], subject_label=prior[0]["subject_label"],
                state="resolved", reason="exact_prior_subject", candidates=prior,
            )
        if len(prior) > 1:
            return EntityResolution(
                raw_key=raw_key, raw_label=label, entity_type=entity_type,
                subject_key=raw_key, subject_label=label, state="ambiguous",
                reason="duplicate_exact_prior_subject", candidates=prior,
            )
        return EntityResolution(
            raw_key=raw_key, raw_label=label, entity_type=entity_type,
            subject_key=raw_key, subject_label=label, state="resolved", reason="new_stable_anchor",
        )

    def _prepare_mentions(self, source: dict[str, Any]) -> None:
        with self.service.store._lock, self.service.store.connection() as con:
            con.execute(
                "UPDATE discovery_mentions SET active=0,updated_at=? "
                "WHERE source_turn_id=? AND source_kind=? AND active=1 AND source_revision!=?",
                (utc_now(), source.get("turn_id"), source.get("source_kind"), source.get("revision")),
            )

    def _record_mention(self, resolution: EntityResolution, entity: dict[str, Any], source: dict[str, Any]) -> None:
        segment_id = entity.get("introduced_by")
        segment = source.get("segments", {}).get(str(segment_id)) if segment_id else None
        span_text = ""
        if segment:
            span_text = str(segment.get("raw_text") or segment.get("text") or segment.get("normalized_text") or "")
        seed = dumps([
            source.get("turn_id"), source.get("source_kind"), source.get("revision"),
            resolution.raw_key, resolution.raw_label, resolution.entity_type,
        ])
        mention_key = sha256(seed.encode("utf-8")).hexdigest()
        mention_id = "MENTION-" + mention_key[:16].upper()
        now = utc_now()
        with self.service.store._lock, self.service.store.connection() as con:
            con.execute(
                "INSERT INTO discovery_mentions(id,mention_key,project_id,world_id,branch_id,source_session_id,"
                "source_turn_id,source_kind,source_revision,raw_entity_key,surface,normalized_surface,entity_type,"
                "mention_role,resolution_state,resolved_subject_key,resolved_label,resolved_resource_type,"
                "resolved_resource_id,candidates_json,source_segment,span_text,story_order,world_time_json,active,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?) "
                "ON CONFLICT(mention_key) DO UPDATE SET resolution_state=excluded.resolution_state,"
                "resolved_subject_key=excluded.resolved_subject_key,resolved_label=excluded.resolved_label,"
                "resolved_resource_id=excluded.resolved_resource_id,candidates_json=excluded.candidates_json,"
                "mention_role=excluded.mention_role,span_text=excluded.span_text,active=1,updated_at=excluded.updated_at",
                (
                    mention_id, mention_key, source.get("project_id"), source.get("world_id"), source.get("branch_id"),
                    source.get("session_id"), source.get("turn_id"), source.get("source_kind"), source.get("revision"),
                    resolution.raw_key, resolution.raw_label, normalize_identity_label(resolution.raw_label),
                    resolution.entity_type, resolution.mention_role, resolution.state,
                    resolution.subject_key if resolution.state == "resolved" else None,
                    resolution.subject_label if resolution.state == "resolved" else None,
                    "entity_family" if resolution.resource_id else None, resolution.resource_id,
                    dumps(resolution.candidates or []), segment_id, span_text, source.get("story_order"),
                    dumps(source.get("world_time")) if source.get("world_time") is not None else None,
                    now, now,
                ),
            )

    def resolve_entities(
        self,
        entities: dict[str, dict[str, Any]],
        *,
        text: str,
        source: dict[str, Any],
    ) -> ResolvedEntityFrame:
        self._prepare_mentions(source)
        resolutions: dict[str, EntityResolution] = {}
        resolved_entities: dict[str, dict[str, Any]] = {}
        key_map: dict[str, str] = {}

        self_labels = self.coreference.self_labels(text)
        named: list[dict[str, str]] = []
        self_named: list[dict[str, str]] = []

        # Pass 1: explicit named identities. This establishes anchors before any
        # anaphor can refer to them in the same source.
        for raw_key, entity in entities.items():
            entity_type = str(entity.get("type") or "entity").strip() or "entity"
            label = str(entity.get("label") or "").strip()
            if not label or normalize_identity_label(label) in GENERIC_LABELS:
                continue
            resolution = self._explicit(
                raw_key=raw_key, label=label, entity_type=entity_type, source=source
            )
            if normalize_identity_label(label) in self_labels and entity_type == "character":
                resolution.mention_role = "self"
            resolutions[raw_key] = resolution
            named.append({"subject_key": resolution.subject_key, "subject_label": resolution.subject_label})
            if resolution.mention_role == "self":
                self_named.append({"subject_key": resolution.subject_key, "subject_label": resolution.subject_label})

        # Pass 2: generic/self/pronoun entities resolve only when the candidate
        # set is unique. Otherwise the extractor-local id remains isolated and no
        # proposition is silently merged into another entity.
        for raw_key, entity in entities.items():
            if raw_key in resolutions:
                continue
            entity_type = str(entity.get("type") or "entity").strip() or "entity"
            label = str(entity.get("label") or raw_key).strip() or raw_key
            coref = self.coreference.resolve(
                surface=label, entity_type=entity_type, source=source,
                current_named=named, self_named=self_named,
            )
            if coref.state == "resolved" and coref.subject_key:
                resolution = EntityResolution(
                    raw_key=raw_key, raw_label=label, entity_type=entity_type,
                    subject_key=coref.subject_key, subject_label=coref.subject_label or label,
                    state="resolved", reason=coref.reason, candidates=coref.candidates,
                    mention_role="anaphor",
                )
                if normalize_identity_label(label) in {"self", "aku", "saya", "gue", "gua", "i", "me", "myself", "my"}:
                    resolution.mention_role = "self"
            else:
                resolution = EntityResolution(
                    raw_key=raw_key, raw_label=label, entity_type=entity_type,
                    subject_key=raw_key, subject_label=label, state=coref.state,
                    reason=coref.reason, candidates=coref.candidates, mention_role="anaphor",
                )
            resolutions[raw_key] = resolution

        for raw_key, entity in entities.items():
            resolution = resolutions[raw_key]
            clone = dict(entity)
            clone["raw_id"] = raw_key
            clone["id"] = resolution.subject_key
            clone["label"] = resolution.subject_label
            clone["resolution_state"] = resolution.state
            clone["resolution_reason"] = resolution.reason
            clone["resolution_candidates"] = resolution.candidates or []
            resolved_entities[raw_key] = clone
            key_map[raw_key] = resolution.subject_key
            self._record_mention(resolution, entity, source)

        return ResolvedEntityFrame(
            entities=resolved_entities, key_map=key_map, resolutions=resolutions
        )
