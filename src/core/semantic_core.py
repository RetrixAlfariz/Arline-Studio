from __future__ import annotations

import re
from typing import Any

from .authority import AuthorityResolver
from .contradictions import ContradictionResolver
from .schema import (
    FactRecord,
    NegativeFact,
    Provenance,
    SemanticCore,
    TemporalEntry,
    TransitionContract,
)


class SemanticCoreBuilder:
    VERSION = "0.1"

    def __init__(self):
        self.authority = AuthorityResolver()
        self.contradictions = ContradictionResolver()

    @classmethod
    def default(cls):
        return cls()

    def build(self, pipeline_result) -> SemanticCore:
        state = pipeline_result.extracted_state
        events = pipeline_result.events
        debug = pipeline_result.debug
        source_index = self._source_index(debug)

        facts: list[FactRecord] = []
        trace_index: dict[str, dict[str, Any]] = {}
        fact_counter = 1

        for entity in state.get("entities", []) or []:
            entity_id = entity.get("id")
            for path, raw_fact in self._flatten(entity.get("attributes", {})):
                if path.startswith("ontology."):
                    continue
                fact_id = f"fact_{fact_counter:04d}"
                fact_counter += 1
                epistemic = raw_fact.get("epistemic", "explicit")
                authority = self._authority_for(epistemic, path)
                source_segment = raw_fact.get("source_segment")
                source_text = source_index.get(source_segment)
                category = self._category(path)
                temporal = self._temporal_for_path(path)
                priority = self._priority(category, temporal)
                prov = Provenance(
                    source_kind="narrator_assertion" if epistemic == "explicit" else "analytical_or_contextual_inference",
                    source_segment=source_segment,
                    source_text=source_text,
                    authority=authority,
                )
                record = FactRecord(
                    id=fact_id,
                    entity_id=entity_id,
                    path=path,
                    value=raw_fact.get("value"),
                    category=category,
                    authority=authority,
                    epistemic=epistemic,
                    confidence=float(raw_fact.get("confidence", .9)),
                    temporal_scope=temporal,
                    persistence="persistent",
                    priority=priority,
                    provenance=[prov],
                )
                facts.append(record)
                trace_index[fact_id] = {
                    "writer_fact": None,
                    "canonical_entity": entity_id,
                    "canonical_path": path,
                    "value": raw_fact.get("value"),
                    "epistemic": epistemic,
                    "confidence": raw_fact.get("confidence"),
                    "authority": authority,
                    "source_segment": source_segment,
                    "source_text": source_text,
                }

        # Resolve competing values by authority while preserving all trace
        # records for debugging. Temporal scopes remain distinct slots, so a
        # historical baseline and a current value can coexist without conflict.
        resolved = self.authority.resolve_by_slot(facts)
        selected_ids = {fact.id for fact in resolved.values()}
        for trace_id, trace in trace_index.items():
            trace["canonical_selected"] = trace_id in selected_ids
        facts = [fact for fact in facts if fact.id in selected_ids]

        # Claims that aren't materialized as entity attributes still belong in
        # semantic core (social, relational, state, negative, etc.).
        negative_facts: list[NegativeFact] = []
        for claim in state.get("claims", []) or []:
            value = claim.get("value")
            pred = str(claim.get("predicate") or "")
            temporal = claim.get("scope", {}).get("temporal", "current_or_unspecified")
            if value is False:
                negative_facts.append(NegativeFact(
                    subject=claim.get("subject") or "?",
                    predicate=pred,
                    object=claim.get("object"),
                    temporal_scope=temporal,
                    reason="explicit_negative_claim",
                    provenance=[Provenance(
                        source_kind=claim.get("source", {}).get("kind", "narrator_assertion"),
                        source_segment=claim.get("source_segment"),
                        source_text=claim.get("source_text"),
                        authority="user_explicit" if claim.get("epistemic") == "explicit" else "analytical_inference",
                    )],
                ))

        transitions = self._transitions(state, events, source_index, facts)
        # Explicit invalidations become negative current facts.
        for tr in transitions:
            for inv in tr.invalidates:
                negative_facts.append(NegativeFact(
                    subject=tr.actor or "?",
                    predicate=str(inv.get("path") or "invalidated"),
                    object=inv.get("from"),
                    temporal_scope="current_after_transition",
                    reason=f"invalidated_by_{tr.event_type}",
                    provenance=tr.provenance,
                ))

        temporal_ledger = [TemporalEntry(0, "baseline", None, None, None, "S0", "baseline")]
        for i, patch in enumerate(events.get("state_patches", []) or [], 1):
            temporal_ledger.append(TemporalEntry(
                index=i,
                label=f"T{i}",
                event_id=patch.get("event_id"),
                event_type=patch.get("event_type"),
                state_before=patch.get("state_before"),
                state_after=patch.get("state_after"),
            ))

        contradictions = self.contradictions.classify_claim_conflicts(
            state.get("claim_conflicts", []) or []
        )
        contradictions.extend(
            self.contradictions.classify_transition_replacements(
                events.get("state_patches", []) or []
            )
        )

        unresolved = list((state.get("coverage") or {}).get("unresolved_semantic_queue", []) or [])
        return SemanticCore(
            version=self.VERSION,
            facts=facts,
            relations=list(state.get("relations", []) or []),
            negative_facts=negative_facts,
            transitions=transitions,
            temporal_ledger=temporal_ledger,
            knowledge=list(state.get("knowledge", []) or []),
            beliefs=list(state.get("beliefs", []) or []),
            norms=list(state.get("norms", []) or []),
            experience=list(state.get("experience", []) or []),
            relationship_timeline=list(state.get("relationship_timeline", []) or []),
            contradictions=contradictions,
            unresolved=unresolved,
            trace_index=trace_index,
            diagnostics=[],
        )

    def _transitions(self, state, events, source_index, facts) -> list[TransitionContract]:
        fact_paths = {(f.entity_id, f.path) for f in facts}
        patches = {p.get("event_id"): p for p in events.get("state_patches", []) or []}
        out = []
        for event in events.get("events", []) or []:
            patch = patches.get(event.get("id"), {})
            changes, invalidates = [], []
            for op in patch.get("patch", []) or []:
                raw_path = op.get("path")
                path = self._canonical_runtime_path(raw_path)
                if op.get("op") == "delete":
                    invalidates.append({"path": path, "from": op.get("from")})
                elif op.get("op") in {"set", "replace"}:
                    changes.append({
                        "path": path,
                        "from": op.get("from"),
                        "to": op.get("value", op.get("to")),
                    })
                elif op.get("op") == "add_relation":
                    changes.append({
                        "relation": {
                            "subject": op.get("subject"),
                            "predicate": op.get("predicate"),
                            "object": op.get("object"),
                        }
                    })

            preserves: list[str] = []
            preconditions: list[str] = []
            side_effects: list[str] = []
            etype = event.get("type")
            target = event.get("target")
            cause = event.get("cause")

            if cause and str(cause).startswith("item:"):
                preconditions.append(f"{cause} exists")

            if etype == "anatomical_transformation":
                # Scope is deliberately narrow for the writer. Existing
                # morphology is already canonical and must not be rewritten
                # unless an explicit event changes it.
                changes.append({
                    "path": "physical.reproductive_anatomy",
                    "to": "fictionally transformed as explicitly described by the source",
                    "semantic_scope": "source-bounded",
                })
                preserves.extend(self._existing_paths(facts, event.get("actor"), (
                    "physical.height_cm",
                    "physical.morphology.",
                    "physical.chest.",
                    "physical.face.",
                )))
                side_effects.append("subsequent body interactions use the transformed reproductive-anatomy state")
            elif etype == "hair_transformation":
                preserves.extend(self._existing_paths(facts, event.get("actor"), (
                    "physical.height_cm", "physical.morphology.", "physical.chest.", "physical.face."
                )))
                preconditions.append("wig is applied before the hair state transition")
            elif etype == "dress_change":
                preconditions.append("target garment exists")
            elif etype == "apply_wig":
                preconditions.append("wig exists")

            prov = [Provenance(
                source_kind="realized_event",
                source_segment=event.get("source_segment"),
                source_text=source_index.get(event.get("source_segment")) or event.get("source_text"),
                authority="verified_story_state",
            )]
            out.append(TransitionContract(
                event_id=event.get("id"),
                event_type=etype,
                actor=event.get("actor"),
                target=target,
                cause=cause,
                order=event.get("order"),
                preconditions=preconditions,
                changes=self._dedup_struct(changes),
                invalidates=self._dedup_struct(invalidates),
                preserves=sorted(set(preserves)),
                side_effects=side_effects,
                provenance=prov,
            ))
        return out

    @staticmethod
    def _dedup_struct(items):
        seen, out = set(), []
        for item in items:
            key = repr(item)
            if key not in seen:
                seen.add(key); out.append(item)
        return out

    @staticmethod
    def _existing_paths(facts, entity_id, prefixes):
        out = []
        for f in facts:
            if f.entity_id != entity_id:
                continue
            if any(f.path == p or (p.endswith(".") and f.path.startswith(p)) for p in prefixes):
                out.append(f.path)
        return out

    @staticmethod
    def _canonical_runtime_path(path: str | None) -> str | None:
        if not path:
            return path
        text = path
        if text.startswith("runtime."):
            text = text[len("runtime."):]
        # strip entity id from runtime path, leaving domain path
        m = re.match(r"(?:char|garment|item|loc|family|relationship):[^.]+\.(.+)", text)
        return m.group(1) if m else text

    @staticmethod
    def _source_index(debug) -> dict[str, str]:
        out = {}
        normalized = (debug or {}).get("normalized_segments", {}).get("segments", []) or []
        for seg in normalized:
            out[seg.get("id")] = seg.get("raw_text") or seg.get("text") or ""
        return out

    @staticmethod
    def _flatten(obj: Any, prefix=""):
        if not isinstance(obj, dict):
            return
        if "value" in obj and any(k in obj for k in ("epistemic", "confidence", "source_segment")):
            yield prefix, obj
            return
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                yield from SemanticCoreBuilder._flatten(value, path)

    @staticmethod
    def _authority_for(epistemic: str, path: str) -> str:
        if epistemic == "explicit":
            return "user_explicit"
        if epistemic == "estimated":
            return "estimate"
        if epistemic == "inferred":
            return "analytical_inference"
        if epistemic == "assumed":
            return "assumed"
        return "analytical_inference"

    @staticmethod
    def _category(path: str) -> str:
        if path.startswith("identity."): return "identity"
        if path.startswith("physical."): return "physical"
        if path.startswith("hair."): return "appearance"
        if path.startswith("scene_state."): return "scene_state"
        if path.startswith("ontology."): return "ontology"
        if path in {"color", "material", "length", "front_length", "back_length", "flowiness", "size_class", "construction"}: return "garment"
        if path.startswith("transformations."): return "transformation"
        if path.startswith("skills."): return "skill"
        if path in {"city", "floor", "area_m2"}: return "location"
        return "general"

    @staticmethod
    def _temporal_for_path(path: str) -> str:
        if ".baseline." in path or path.startswith("hair.baseline"):
            return "historical_baseline"
        if ".current." in path or path.startswith("hair.current"):
            return "current"
        if path.startswith("scene_state."):
            return "current"
        return "current_or_unspecified"

    @staticmethod
    def _priority(category: str, temporal: str) -> int:
        if temporal == "current": return 0
        if category in {"identity", "location", "transformation"}: return 1
        if category in {"physical", "garment", "appearance"}: return 2
        return 3
