from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Iterable

from src.memory.models import Authority, MemoryCandidate, MemoryQueryContext, RetrievalLane, TrustLevel
from src.memory.scope import ScopeGate
from src.narrative.rails import CharacterRailParser
from src.pipeline import ArlineAnalyticalPipeline
from src.workspace.store import WORLD_BIBLE_PROJECT_ID

from .store import DiscoveryStore, checksum


GENERIC_ENTITY_LABELS = {
    "self", "character", "person", "someone", "somebody", "unknown",
    "feminine_clothing", "underwear_set", "self_family",
}
LIBRARY_ENTITY_TYPE = {
    "character": "character",
    "location": "location",
    "item": "item",
    "garment": "item",
    "organization": "organization",
    "lore": "lore",
    "world_rule": "world_rule",
}


@dataclass(slots=True)
class CaptureReport:
    turn_id: str
    source_kind: str
    propositions: int
    instances: int
    skipped: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "source_kind": self.source_kind,
            "propositions": self.propositions,
            "instances": self.instances,
            "skipped": self.skipped,
        }


class DiscoveryService:
    """Extract source-backed Library discoveries without granting canon authority."""

    REVIEW_SOURCE_KINDS = {"user_prompt", "user_edited_prose", "manuscript_user"}

    def __init__(self, *, store: DiscoveryStore, workspace, history, foundation=None):
        self.store = store
        self.workspace = workspace
        self.history = history
        self.foundation = foundation
        self.pipeline = ArlineAnalyticalPipeline.default()
        self.gate = ScopeGate(workspace, history)

    @staticmethod
    def _segment_map(result) -> dict[str, dict[str, Any]]:
        payload = result.debug.get("normalized_segments") or result.debug.get("structure") or {}
        return {str(item.get("id")): item for item in payload.get("segments", []) if item.get("id")}

    @staticmethod
    def _span(segment: dict[str, Any] | None) -> tuple[int | None, int | None, str]:
        if not segment:
            return None, None, ""
        text = segment.get("raw_text") or segment.get("text") or segment.get("normalized_text") or ""
        return segment.get("start"), segment.get("end"), str(text)

    @staticmethod
    def _unwrap_fact(value: Any) -> tuple[Any, str | None, float, str, bool] | None:
        if not isinstance(value, dict) or "value" not in value or "source_segment" not in value:
            return None
        return (
            value.get("value"),
            value.get("source_segment"),
            float(value.get("confidence") or 0.0),
            str(value.get("epistemic") or "explicit"),
            bool(value.get("inferred")),
        )

    @classmethod
    def _flatten_attributes(cls, payload: Any, prefix: str = "") -> Iterable[tuple[str, Any, str, float, str, bool]]:
        fact = cls._unwrap_fact(payload)
        if fact is not None:
            value, segment, confidence, epistemic, inferred = fact
            if prefix and segment:
                yield prefix, value, str(segment), confidence, epistemic, inferred
            return
        if isinstance(payload, dict):
            for key, value in payload.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                yield from cls._flatten_attributes(value, path)

    def _existing_family(self, label: str, entity_type: str) -> dict[str, Any] | None:
        mapped = LIBRARY_ENTITY_TYPE.get(entity_type, entity_type)
        needle = label.strip().casefold()
        try:
            families = self.workspace.list_entity_families(None, entity_type=mapped)
        except Exception:
            families = []
        return next((item for item in families if str(item.get("name") or "").strip().casefold() == needle), None)

    def _subject_link(self, *, project_id: str | None, world_id: str | None,
                      subject_key: str, subject_label: str, subject_type: str) -> dict[str, str] | None:
        linked = self.store.get_subject_link(project_id=project_id, world_id=world_id, subject_key=subject_key)
        if linked:
            return linked
        family = self._existing_family(subject_label, subject_type)
        if family:
            self.store.upsert_subject_link(
                project_id=project_id, world_id=world_id, subject_key=subject_key,
                resource_type="entity_family", resource_id=family["id"],
            )
            return {"resource_type": "entity_family", "resource_id": family["id"]}
        return None

    @staticmethod
    def _turn_time_scope(turn: dict[str, Any]) -> tuple[Any, float | None]:
        scope = turn.get("workspace_scope") or {}
        active = scope.get("active_scene") or scope.get("scene") or {}
        world_time = (
            scope.get("world_time") or active.get("narrative_time")
            or scope.get("narrative_time")
        )
        story_order = scope.get("story_order")
        if story_order is None:
            story_order = active.get("sort_order")
        try:
            story_order = float(story_order) if story_order is not None else None
        except (TypeError, ValueError):
            story_order = None
        return world_time, story_order

    def _capture_prop(self, *, report_keys: set[str], source: dict[str, Any],
                      subject_type: str, subject_key: str, subject_label: str,
                      predicate: str, value: Any, operation: str,
                      source_segment: str | None, confidence: float,
                      explicitness: str, inferred: bool = False,
                      object_type: str | None = None, object_key: str | None = None,
                      object_label: str | None = None,
                      temporal_state: str = "current_or_unspecified") -> bool:
        segment = source["segments"].get(str(source_segment)) if source_segment else None
        span_start, span_end, span_text = self._span(segment)
        link = self._subject_link(
            project_id=source["project_id"], world_id=source["world_id"],
            subject_key=subject_key, subject_label=subject_label, subject_type=subject_type,
        )
        prop = self.store.upsert_proposition(
            project_id=source["project_id"], world_id=source["world_id"],
            subject_type=subject_type, subject_key=subject_key, subject_label=subject_label,
            predicate=predicate, value=value, object_type=object_type,
            object_key=object_key, object_label=object_label, operation=operation,
            temporal_state=temporal_state,
            target_resource_type=link.get("resource_type") if link else None,
            target_resource_id=link.get("resource_id") if link else None,
        )
        qualifies = bool(
            source["base_qualifies"]
            and explicitness == "explicit"
            and not inferred
            and confidence >= 0.6
        )
        self.store.add_instance(
            prop["id"], source_kind=source["source_kind"],
            source_session_id=source["session_id"], source_turn_id=source["turn_id"],
            origin_session_id=source["origin_session_id"], origin_turn_id=source["origin_turn_id"],
            source_revision=source["revision"], project_id=source["project_id"],
            world_id=source["world_id"], branch_id=source["branch_id"],
            world_time=source["world_time"], story_order=source["story_order"],
            source_segment=source_segment, span_start=span_start, span_end=span_end,
            span_text=span_text, extraction_confidence=confidence,
            explicitness="inferred" if inferred else explicitness,
            qualifies_review=qualifies,
        )
        report_keys.add(prop["id"])
        return True

    def capture_text(self, text: str, *, source_kind: str, turn: dict[str, Any],
                     session: dict[str, Any], qualifies_review: bool | None = None) -> CaptureReport:
        if session.get("scratch_mode"):
            return CaptureReport(turn["id"], source_kind, 0, 0, 1)
        compiled = CharacterRailParser.parse(text)
        evidence = compiled.evidence_prompt if compiled.active else text
        evidence = str(evidence or "").strip()
        if not evidence:
            return CaptureReport(turn["id"], source_kind, 0, 0, 1)

        lineage = turn.get("lineage") or {}
        # Fork copying is storage lineage, not an independent narrative source.
        if lineage.get("forked_from_turn_id") and source_kind != "user_edited_prose":
            return CaptureReport(turn["id"], source_kind, 0, 0, 1)

        revision = checksum(evidence)
        self.store.prepare_source_revision(
            source_turn_id=turn["id"], source_kind=source_kind, source_revision=revision
        )
        result = self.pipeline.run(evidence)
        segments = self._segment_map(result)
        world_time, story_order = self._turn_time_scope(turn)
        base_qualifies = source_kind in self.REVIEW_SOURCE_KINDS if qualifies_review is None else bool(qualifies_review)
        origin_turn_id = str(lineage.get("forked_from_turn_id") or turn["id"])
        origin_session_id = str(lineage.get("forked_from_session_id") or session["id"])
        source = {
            "source_kind": source_kind, "session_id": session["id"], "turn_id": turn["id"],
            "origin_session_id": origin_session_id, "origin_turn_id": origin_turn_id,
            "revision": revision, "project_id": session.get("project_id"),
            "world_id": session.get("world_id"), "branch_id": session.get("branch_id"),
            "world_time": world_time, "story_order": story_order,
            "segments": segments, "base_qualifies": base_qualifies,
        }

        entities = {str(item["id"]): item for item in result.extracted_state.get("entities", []) if item.get("id")}
        prop_ids: set[str] = set()
        skipped = 0

        for entity_id, entity in entities.items():
            entity_type = str(entity.get("type") or "").strip()
            label = str(entity.get("label") or "").strip()
            mapped = LIBRARY_ENTITY_TYPE.get(entity_type)
            meaningful = bool(mapped and label and label.casefold() not in GENERIC_ENTITY_LABELS)
            if meaningful:
                self._capture_prop(
                    report_keys=prop_ids, source=source, subject_type=entity_type,
                    subject_key=entity_id, subject_label=label, predicate="entity.exists",
                    value={"entity_type": mapped, "label": label}, operation="create",
                    source_segment=entity.get("introduced_by"), confidence=0.95,
                    explicitness="explicit", inferred=False,
                )
            else:
                skipped += 1

            for path, value, segment_id, confidence, epistemic, inferred in self._flatten_attributes(entity.get("attributes") or {}):
                if not label or label.casefold() in GENERIC_ENTITY_LABELS:
                    skipped += 1
                    continue
                self._capture_prop(
                    report_keys=prop_ids, source=source, subject_type=entity_type or "entity",
                    subject_key=entity_id, subject_label=label, predicate=path,
                    value=value, operation="update", source_segment=segment_id,
                    confidence=confidence, explicitness=epistemic, inferred=inferred,
                )

        for relation in result.extracted_state.get("relations", []):
            subject_key = str(relation.get("subject") or "")
            if not subject_key:
                continue
            subject = entities.get(subject_key) or {}
            subject_label = str(subject.get("label") or subject_key)
            if subject_label.casefold() in GENERIC_ENTITY_LABELS:
                skipped += 1
                continue
            object_key = str(relation.get("object") or "") or None
            obj = entities.get(object_key or "") or {}
            self._capture_prop(
                report_keys=prop_ids, source=source,
                subject_type=str(subject.get("type") or "entity"), subject_key=subject_key,
                subject_label=subject_label, predicate=str(relation.get("predicate") or "related_to"),
                value=relation.get("value", True), operation="relation",
                source_segment=relation.get("source_segment"),
                confidence=float(relation.get("confidence") or 0.7),
                explicitness=str(relation.get("epistemic") or "explicit"),
                object_type=str(obj.get("type") or "entity") if object_key else None,
                object_key=object_key, object_label=str(obj.get("label") or object_key or "") or None,
                temporal_state=str(relation.get("temporal_scope") or "current_or_unspecified"),
            )

        event_by_id = {str(item.get("id")): item for item in result.events.get("events", []) if item.get("id")}
        for state_patch in result.events.get("state_patches", []):
            event = event_by_id.get(str(state_patch.get("event_id") or "")) or {}
            for patch in state_patch.get("patch", []):
                if patch.get("op") not in {"set", "replace", "delete"}:
                    continue
                raw_path = str(patch.get("path") or "")
                match = re.match(r"runtime\.([^.]*)\.(.+)", raw_path)
                if not match:
                    continue
                subject_key, state_path = match.group(1), match.group(2)
                subject = entities.get(subject_key) or {}
                subject_label = str(subject.get("label") or subject_key)
                if subject_label.casefold() in GENERIC_ENTITY_LABELS:
                    skipped += 1
                    continue
                value = patch.get("value") if patch.get("op") != "delete" else {"deleted": True, "previous": patch.get("from")}
                self._capture_prop(
                    report_keys=prop_ids, source=source,
                    subject_type=str(subject.get("type") or "character"), subject_key=subject_key,
                    subject_label=subject_label, predicate=f"state.{state_path}", value=value,
                    operation="transition", source_segment=event.get("source_segment"),
                    confidence=float(event.get("eventhood_score") or 0.8), explicitness="explicit",
                    temporal_state="historical_or_current",
                )

        instances = sum(
            1 for prop_id in prop_ids
            for item in self.store.list_instances(prop_id)
            if item["source_turn_id"] == turn["id"] and item["source_kind"] == source_kind
            and item["source_revision"] == revision and item["active"]
        )
        return CaptureReport(turn["id"], source_kind, len(prop_ids), instances, skipped)

    def capture_turn(self, turn_id: str, *, source_kind: str = "user_prompt") -> CaptureReport:
        turn = self.history.get_turn(turn_id)
        session = self.history.get_session_meta(turn["session_id"])
        if source_kind == "user_prompt":
            text = turn.get("user_prompt") or ""
            qualifies = True
        elif source_kind == "accepted_generation":
            text = turn.get("story") or ""
            qualifies = False
        elif source_kind == "user_edited_prose":
            text = turn.get("edited_story") or ""
            qualifies = True
        else:
            raise ValueError(f"Unsupported discovery source kind: {source_kind}")
        return self.capture_text(text, source_kind=source_kind, turn=turn, session=session, qualifies_review=qualifies)

    def _instance_allowed(self, instance: dict[str, Any], context: MemoryQueryContext) -> bool:
        if not instance.get("active"):
            return False
        if context.session_id is None:
            # Library browsing without an active chat is conservative: scope by
            # project/world/branch here, while reviewed support is later counted
            # within a single session rather than across unrelated chat forks.
            if context.project_id and instance.get("project_id") not in {None, context.project_id}:
                return False
            if context.world_id and instance.get("world_id") not in {None, context.world_id}:
                return False
            if context.branch_id and instance.get("branch_id") not in {None, context.branch_id}:
                return False
            return True
        candidate = MemoryCandidate(
            id=instance["id"], lane=RetrievalLane.STRUCTURED_STATE,
            text=instance.get("span_text") or "discovery evidence",
            source_type="turn", source_id=instance.get("source_turn_id") or instance["id"],
            project_id=instance.get("project_id"), world_id=instance.get("world_id"),
            branch_id=instance.get("branch_id"), session_id=instance.get("source_session_id"),
            world_time=instance.get("world_time"), story_order=instance.get("story_order"),
            authority=Authority.USER_EXPLICIT_NOTE.value, trust_level=TrustLevel.USER_PROVIDED.value,
            metadata={"source_recorded_at": instance.get("created_at")},
        )
        return self.gate.evaluate(candidate, context).allowed

    def evaluate_proposition(self, proposition: dict[str, Any], context: MemoryQueryContext,
                             *, include_instances: bool = False) -> dict[str, Any]:
        all_instances = self.store.list_instances(proposition["id"])
        visible = [item for item in all_instances if self._instance_allowed(item, context)]
        visible_active = [item for item in visible if item["active"]]
        inactive = [item for item in all_instances if not item["active"]]

        if proposition["authority_state"] == "canon":
            knowledge_state = "canon"
        elif proposition["authority_state"] == "dismissed":
            knowledge_state = "dismissed"
        else:
            if context.session_id is None:
                by_session: dict[str, set[tuple[str, str]]] = {}
                for item in visible_active:
                    if not item["qualifies_review"]:
                        continue
                    key = str(item.get("source_session_id") or "")
                    by_session.setdefault(key, set()).add((item["source_kind"], str(item.get("origin_turn_id") or item.get("source_turn_id") or item["id"])))
                qualified_count = max((len(values) for values in by_session.values()), default=0)
            else:
                qualified = {
                    (item["source_kind"], str(item.get("origin_turn_id") or item.get("source_turn_id") or item["id"]))
                    for item in visible_active if item["qualifies_review"]
                }
                qualified_count = len(qualified)
            knowledge_state = "reviewed" if qualified_count >= 2 else "detected"

        if visible_active:
            provenance_state = "partial" if inactive else "active"
        else:
            provenance_state = "orphaned"

        qualified_visible = {
            (item["source_kind"], str(item.get("origin_turn_id") or item.get("source_turn_id") or item["id"]))
            for item in visible_active if item["qualifies_review"]
        }
        item = {
            **proposition,
            "knowledge_state": knowledge_state,
            "provenance_state": provenance_state,
            "support_count": len(visible_active),
            "qualified_support_count": len(qualified_visible),
            "total_support_count": len(all_instances),
            "out_of_scope_support_count": max(0, sum(1 for x in all_instances if x["active"]) - len(visible_active)),
            "inactive_support_count": len(inactive),
        }
        if include_instances:
            item["instances"] = all_instances
            item["visible_instance_ids"] = [x["id"] for x in visible_active]
        return item

    def list(self, context: MemoryQueryContext, *, include_dismissed: bool = False,
             include_orphaned: bool = False, limit: int = 500) -> list[dict[str, Any]]:
        rows = self.store.list_propositions(
            project_id=context.project_id, world_id=context.world_id,
            include_dismissed=include_dismissed, limit=limit,
        )
        evaluated = [self.evaluate_proposition(row, context) for row in rows]
        if not include_orphaned:
            evaluated = [item for item in evaluated if item["provenance_state"] != "orphaned" or item["knowledge_state"] == "canon"]
        rank = {"canon": 3, "reviewed": 2, "detected": 1, "dismissed": 0}
        return sorted(evaluated, key=lambda item: (rank.get(item["knowledge_state"], 0), item["qualified_support_count"], item["support_count"], item["updated_at"]), reverse=True)

    def get(self, proposition_id: str, context: MemoryQueryContext) -> dict[str, Any]:
        return self.evaluate_proposition(self.store.get_proposition(proposition_id), context, include_instances=True)

    def memory_candidates(self, plan) -> list[MemoryCandidate]:
        context = plan.scope
        rows = self.list(context, include_dismissed=False, include_orphaned=False, limit=250)
        query = (plan.normalized_query or "").casefold()
        labels = {str(item.get("label") or "").casefold() for item in plan.resolved_entities}
        output: list[MemoryCandidate] = []
        for item in rows:
            if item["knowledge_state"] in {"canon", "dismissed"} or item.get("materialized_resource_id"):
                continue
            label = str(item.get("subject_label") or "")
            directly_named = bool(label and label.casefold() in query)
            if labels and label.casefold() not in labels and not directly_named:
                continue
            if not directly_named and not labels and item["knowledge_state"] == "detected" and plan.route.value == "STORY_CONTINUE":
                continue
            value = json.dumps(item.get("value"), ensure_ascii=False, default=str)
            prefix = "REVIEWED NON-CANON" if item["knowledge_state"] == "reviewed" else "DETECTED NON-CANON"
            text = f"[{prefix}] {label}.{item['predicate']} = {value}"
            output.append(MemoryCandidate(
                id=f"DISCOVERY:{item['id']}", lane=RetrievalLane.STRUCTURED_STATE,
                text=text, source_type="discovery_proposition", source_id=item["id"],
                project_id=context.project_id, world_id=context.world_id, branch_id=context.branch_id,
                session_id=context.session_id,
                authority=f"discovery_{item['knowledge_state']}", trust_level=TrustLevel.USER_PROVIDED.value,
                importance=0.72 if item["knowledge_state"] == "reviewed" else 0.45,
                extraction_confidence=1.0,
                metadata={
                    "discovery": True, "knowledge_state": item["knowledge_state"],
                    "provenance_state": item["provenance_state"],
                    "support_count": item["support_count"],
                    "qualified_support_count": item["qualified_support_count"],
                    "structured": False,
                },
            ))
        return output[:24]

    def set_session_active(self, session_id: str, *, active: bool, reason: str) -> int:
        return self.store.set_source_active(session_id=session_id, active=active, reason=reason)

    def _ensure_subject_family(self, proposition: dict[str, Any], branch_id: str | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
        link = self.store.get_subject_link(
            project_id=proposition.get("project_id"), world_id=proposition.get("world_id"),
            subject_key=proposition["subject_key"],
        )
        family = None
        if link and link.get("resource_type") == "entity_family":
            try:
                family = self.workspace.get_entity_family(link["resource_id"])
            except KeyError:
                family = None
        if family is None:
            mapped = LIBRARY_ENTITY_TYPE.get(proposition.get("subject_type") or "", "lore")
            family = self._existing_family(proposition["subject_label"], mapped)
        if family is None:
            family = self.workspace.create_entity_family(
                None, proposition["subject_label"], entity_type=LIBRARY_ENTITY_TYPE.get(proposition.get("subject_type") or "", "lore"),
                description="Discovered indirectly from narrative evidence.",
                create_variant_in_world=proposition.get("world_id"), branch_id=branch_id,
            )
        self.store.upsert_subject_link(
            project_id=proposition.get("project_id"), world_id=proposition.get("world_id"),
            subject_key=proposition["subject_key"], resource_type="entity_family", resource_id=family["id"],
        )
        variant = None
        if proposition.get("world_id"):
            variant = self.workspace.resolve_variant(family["id"], proposition["world_id"], branch_id)
            if variant is None:
                variant = self.workspace.create_variant(
                    family["id"], proposition["world_id"], branch_id=branch_id, canon_status="draft"
                )
        return family, variant

    def _best_visible_instance(self, proposition: dict[str, Any], context: MemoryQueryContext) -> dict[str, Any] | None:
        instances = [x for x in self.store.list_instances(proposition["id"]) if self._instance_allowed(x, context)]
        if not instances:
            return None
        return max(instances, key=lambda x: (x["qualifies_review"], x["extraction_confidence"], x["created_at"]))

    def promote_canon(self, proposition_id: str, context: MemoryQueryContext, *, note: str = "") -> dict[str, Any]:
        proposition = self.store.get_proposition(proposition_id)
        # Authority changes only because this method is exposed behind an explicit
        # user action. No extraction/ranking path calls it automatically.
        proposition = self.store.set_authority(proposition_id, "canon", note=note)
        family, variant = self._ensure_subject_family(proposition, context.branch_id)
        resource_type: str | None = None
        resource_id: str | None = None
        predicate = proposition["predicate"]
        value = proposition.get("value")

        if proposition["operation"] == "create" and predicate == "entity.exists":
            resource_type, resource_id = "entity_family", family["id"]
        elif proposition["operation"] == "relation" and proposition.get("object_key"):
            object_props = self.store.find_subject_propositions(
                project_id=proposition.get("project_id"), world_id=proposition.get("world_id"),
                subject_key=proposition["object_key"],
            )
            object_seed = next((x for x in object_props if x["predicate"] == "entity.exists"), None)
            if object_seed:
                object_family, object_variant = self._ensure_subject_family(object_seed, context.branch_id)
            else:
                object_family = self._existing_family(proposition.get("object_label") or proposition["object_key"], proposition.get("object_type") or "lore")
                object_variant = self.workspace.resolve_variant(object_family["id"], proposition["world_id"], context.branch_id) if object_family and proposition.get("world_id") else None
            if variant and object_variant and proposition.get("world_id"):
                relationship = self.workspace.create_relationship(
                    proposition["world_id"], variant["id"], object_variant["id"], predicate,
                    branch_id=context.branch_id, canon_status="canon",
                    attributes={"value": value, "source": "discovery"},
                )
                resource_type, resource_id = "relationship", relationship["id"]
        elif proposition["operation"] == "transition" and variant:
            best = self._best_visible_instance(proposition, context)
            state_key = predicate.removeprefix("state.")
            if best and (best.get("story_order") is not None or best.get("world_time") is not None):
                event = self.workspace.add_timeline_event(
                    world_id=proposition["world_id"], branch_id=context.branch_id,
                    owner_type="entity_variant", owner_id=variant["id"],
                    time_label=str(best.get("world_time") or ""), order_key=float(best.get("story_order") or 0.0),
                    event_type="discovered_state_transition",
                    summary=f"User promoted discovered state: {proposition['subject_label']}.{state_key}",
                    state_patch={state_key: value}, source_type="discovery_proposition",
                    source_id=proposition_id, status="canon",
                )
                resource_type, resource_id = "timeline", event["id"]
            else:
                fact = self.workspace.add_fact(
                    WORLD_BIBLE_PROJECT_ID, "entity_variant", variant["id"], f"current_state.{state_key}", value,
                    world_id=proposition.get("world_id"), branch_id=context.branch_id,
                    status="canon", authority="user_promoted", source_type="discovery_proposition", source_id=proposition_id,
                )
                resource_type, resource_id = "fact", fact["id"]
        elif variant or family:
            owner_type = "entity_variant" if variant else "entity_family"
            owner_id = variant["id"] if variant else family["id"]
            fact = self.workspace.add_fact(
                WORLD_BIBLE_PROJECT_ID, owner_type, owner_id, predicate, value,
                world_id=proposition.get("world_id"), branch_id=context.branch_id,
                status="canon", authority="user_promoted", source_type="discovery_proposition", source_id=proposition_id,
            )
            resource_type, resource_id = "fact", fact["id"]
            if isinstance(value, str) and predicate in {"identity.nickname", "identity.presentation_name"} and self.foundation is not None:
                try:
                    self.foundation.add_alias("entity_family", family["id"], value)
                except Exception:
                    pass

        result = self.store.set_materialized(
            proposition_id, resource_type=resource_type, resource_id=resource_id,
            target_resource_type="entity_family", target_resource_id=family["id"],
        )
        if self.foundation is not None:
            try:
                self.foundation.log_activity(
                    proposition.get("project_id"), "discovery_promoted", "discovery_proposition", proposition_id,
                    label=proposition["subject_label"], detail={"predicate": predicate, "materialized": [resource_type, resource_id]},
                )
            except Exception:
                pass
        return self.evaluate_proposition(result, context, include_instances=True)

    def dismiss(self, proposition_id: str, context: MemoryQueryContext, *, note: str = "") -> dict[str, Any]:
        prop = self.store.set_authority(proposition_id, "dismissed", note=note)
        return self.evaluate_proposition(prop, context, include_instances=True)

    def reset_decision(self, proposition_id: str, context: MemoryQueryContext, *, note: str = "") -> dict[str, Any]:
        prop = self.store.set_authority(proposition_id, "observed", note=note)
        return self.evaluate_proposition(prop, context, include_instances=True)
