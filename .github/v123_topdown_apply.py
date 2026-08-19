from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise RuntimeError(f"patch anchor not found in {path}: {old[:160]!r}")
    write(path, text.replace(old, new, 1))


# ---------------------------------------------------------------------------
# v1.2.3 top-level planner: one deterministic plan above Workspace/Memory/WCF.
# ---------------------------------------------------------------------------
write("src/context/intelligence.py", r'''from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import re
from typing import Any


CONTEXT_INTELLIGENCE_VERSION = "1.2.3a1"


class NarrativeIntent(StrEnum):
    CONTINUE = "continue"
    DIALOGUE = "dialogue"
    ACTION = "action"
    DESCRIPTION = "description"
    TRANSITION = "transition"
    CAUSAL = "causal"
    RECALL = "recall"
    SUMMARY = "summary"
    CONTINUITY_REVIEW = "continuity_review"
    BRANCH_COMPARE = "branch_compare"


@dataclass(slots=True)
class NarrativeContextPlan:
    version: str
    route: str
    intent: str
    lens: str
    focus_resources: list[dict[str, Any]] = field(default_factory=list)
    scene_anchors: dict[str, Any] = field(default_factory=dict)
    dimensions: dict[str, float] = field(default_factory=dict)
    required_lanes: list[str] = field(default_factory=list)
    optional_lanes: list[str] = field(default_factory=list)
    preserve_lanes: list[str] = field(default_factory=list)
    lane_weights: dict[str, float] = field(default_factory=dict)
    lane_token_budget: dict[str, int] = field(default_factory=dict)
    policies: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NarrativeContextPlanner:
    """Deterministic narrative-context planner.

    This layer does not create truth. It tells existing Workspace/Memory/
    Continuity systems which dimensions matter for the current request and how
    much budget they may consume. ScopeGate and Canon authority remain below it.
    """

    VERSION = CONTEXT_INTELLIGENCE_VERSION

    DIALOGUE = re.compile(r"\b(dialogue|conversation|talk|talking|speak|speaks|said|says|whisper|berkata|bicara|ngobrol|percakapan|dialog)\b", re.I)
    ACTION = re.compile(r"\b(fight|attack|chase|run|escape|battle|action|combat|menyerang|bertarung|mengejar|kabur|aksi)\b", re.I)
    DESCRIPTION = re.compile(r"\b(describe|description|appearance|look|looks|outfit|clothes|room|setting|atmosphere|detail|gambarkan|deskripsi|penampilan|pakaian|ruangan|suasana)\b", re.I)
    TRANSITION = re.compile(r"\b(transform|transformed|become|became|change|changed|transition|after|now|berubah|menjadi|setelah|sekarang|transformasi)\b", re.I)

    DIMENSION_LANES = {
        "continuity": ("continuity",),
        "state": ("structured_state",),
        "pov": ("epistemic",),
        "relationships": ("relationships",),
        "events": ("events",),
        "spatial": ("spatial",),
        "threads": ("threads",),
        "source": ("fts_manuscript", "fts_chat", "dense"),
    }

    @staticmethod
    def _route_value(route: Any) -> str:
        return str(getattr(route, "value", route or "TEXT_RECALL"))

    def _intent(self, prompt: str, route: str) -> NarrativeIntent:
        if route == "WHY_CAUSAL":
            return NarrativeIntent.CAUSAL
        if route == "CONTINUITY_CHECK":
            return NarrativeIntent.CONTINUITY_REVIEW
        if route == "BRANCH_COMPARE":
            return NarrativeIntent.BRANCH_COMPARE
        if route == "GLOBAL_SUMMARY":
            return NarrativeIntent.SUMMARY
        if route in {"TEMPORAL_STATE", "EVENT_LOOKUP", "TEXT_RECALL"}:
            if self.TRANSITION.search(prompt):
                return NarrativeIntent.TRANSITION
            if self.DIALOGUE.search(prompt):
                return NarrativeIntent.DIALOGUE
            if self.ACTION.search(prompt):
                return NarrativeIntent.ACTION
            if self.DESCRIPTION.search(prompt):
                return NarrativeIntent.DESCRIPTION
            return NarrativeIntent.RECALL
        if self.DIALOGUE.search(prompt):
            return NarrativeIntent.DIALOGUE
        if self.ACTION.search(prompt):
            return NarrativeIntent.ACTION
        if self.DESCRIPTION.search(prompt):
            return NarrativeIntent.DESCRIPTION
        if self.TRANSITION.search(prompt):
            return NarrativeIntent.TRANSITION
        return NarrativeIntent.CONTINUE

    @staticmethod
    def _workspace_scope(workspace_context: Any | None) -> dict[str, Any]:
        return dict(getattr(workspace_context, "scope", {}) or {})

    def _focus_resources(self, scope: Any, workspace_context: Any | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        ws_scope = self._workspace_scope(workspace_context)
        active = dict(ws_scope.get("active_scene") or {})
        labels: dict[tuple[str, str], str] = {}
        for row in list(getattr(workspace_context, "auto_selected", []) or []) + list(getattr(workspace_context, "explicit_references", []) or []):
            typ, rid = str(row.get("type") or ""), str(row.get("id") or "")
            if typ and rid:
                labels[(typ, rid)] = str(row.get("label") or rid)

        output: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        def add(typ: str, rid: Any, reason: str, label: str | None = None) -> None:
            rid = str(rid or "").strip()
            if not typ or not rid or (typ, rid) in seen:
                return
            seen.add((typ, rid))
            output.append({
                "type": typ,
                "id": rid,
                "label": label or labels.get((typ, rid), rid),
                "reason": reason,
                "method": "context_plan",
                "confidence": 1.0,
            })

        for ref in list(getattr(scope, "explicit_references", []) or []):
            add(str(ref.get("type") or ""), ref.get("id"), "explicit reference", str(ref.get("label") or "") or None)
        if active.get("pov_variant_id"):
            add("entity_variant", active["pov_variant_id"], "active scene POV")
        if active.get("location_variant_id"):
            add("entity_variant", active["location_variant_id"], "active scene location")
        for variant_id in (active.get("participants") or [])[:16]:
            add("entity_variant", variant_id, "present in active scene")

        anchors = {
            "document_id": active.get("document_id"),
            "pov_variant_id": getattr(scope, "pov_variant_id", None) or active.get("pov_variant_id"),
            "location_variant_id": active.get("location_variant_id"),
            "participants": list(active.get("participants") or [])[:16],
            "world_time": getattr(scope, "world_time", None) or active.get("narrative_time"),
            "story_order": getattr(scope, "story_order", None),
        }
        return output[:24], anchors

    @staticmethod
    def _base_dimensions(intent: NarrativeIntent) -> dict[str, float]:
        table = {
            NarrativeIntent.CONTINUE: dict(continuity=1.00, state=.92, relationships=.82, events=.72, spatial=.62, threads=.78, pov=.65, source=.32),
            NarrativeIntent.DIALOGUE: dict(continuity=.96, state=.78, relationships=1.00, events=.48, spatial=.36, threads=.62, pov=1.00, source=.22),
            NarrativeIntent.ACTION: dict(continuity=.96, state=.92, relationships=.58, events=1.00, spatial=.78, threads=.55, pov=.72, source=.28),
            NarrativeIntent.DESCRIPTION: dict(continuity=.82, state=1.00, relationships=.48, events=.38, spatial=1.00, threads=.30, pov=.52, source=.34),
            NarrativeIntent.TRANSITION: dict(continuity=1.00, state=.96, relationships=.62, events=1.00, spatial=.52, threads=.58, pov=.72, source=.30),
            NarrativeIntent.CAUSAL: dict(continuity=.96, state=.68, relationships=.70, events=1.00, spatial=.42, threads=.48, pov=.55, source=.58),
            NarrativeIntent.RECALL: dict(continuity=.76, state=.66, relationships=.55, events=.78, spatial=.45, threads=.35, pov=.42, source=1.00),
            NarrativeIntent.SUMMARY: dict(continuity=.72, state=.55, relationships=.55, events=.68, spatial=.34, threads=.62, pov=.30, source=.82),
            NarrativeIntent.CONTINUITY_REVIEW: dict(continuity=1.00, state=.96, relationships=.72, events=.82, spatial=.48, threads=.30, pov=.62, source=.40),
            NarrativeIntent.BRANCH_COMPARE: dict(continuity=1.00, state=.92, relationships=.68, events=.82, spatial=.42, threads=.38, pov=.35, source=.28),
        }
        return dict(table[intent])

    def plan(self, prompt: str, scope: Any, *, workspace_context: Any | None = None, route: Any = "STORY_CONTINUE") -> NarrativeContextPlan:
        route_value = self._route_value(route)
        intent = self._intent(prompt, route_value)
        focus, anchors = self._focus_resources(scope, workspace_context)
        lens = str(getattr(getattr(scope, "context_lens", "scene"), "value", getattr(scope, "context_lens", "scene")) or "scene")
        dimensions = self._base_dimensions(intent)
        if anchors.get("pov_variant_id"):
            dimensions["pov"] = max(dimensions["pov"], 1.0 if lens == "pov" else .84)
        elif lens == "pov":
            dimensions["pov"] = .35
        if not anchors.get("location_variant_id"):
            dimensions["spatial"] *= .72
        if not anchors.get("participants") and len([x for x in focus if x["type"] == "entity_variant"]) < 2:
            dimensions["relationships"] *= .74

        lane_weights: dict[str, float] = {}
        lane_factor = {"fts_manuscript": .80, "fts_chat": .55, "dense": .70}
        for dimension, weight in dimensions.items():
            for lane in self.DIMENSION_LANES[dimension]:
                lane_weights[lane] = max(lane_weights.get(lane, 0.0), round(weight * lane_factor.get(lane, 1.0), 3))

        optional_lanes = [lane for lane, _ in sorted(lane_weights.items(), key=lambda item: (-item[1], item[0])) if _ >= .18]
        required_lanes: list[str] = ["continuity"] if route_value == "CONTINUITY_CHECK" else []
        preserve_order = ["continuity", "epistemic", "structured_state", "relationships", "events", "spatial", "threads"]
        preserve_lanes = [lane for lane in preserve_order if lane_weights.get(lane, 0.0) >= .55][:6]

        token_budget = max(0, int(getattr(scope, "token_budget", 0) or 0))
        lane_token_budget: dict[str, int] = {}
        if token_budget and optional_lanes:
            total_weight = sum(max(.05, lane_weights.get(lane, .05)) for lane in optional_lanes)
            distributable = max(0, token_budget - 96)
            for lane in optional_lanes:
                share = max(.05, lane_weights.get(lane, .05)) / total_weight
                lane_token_budget[lane] = max(96, int(distributable * share))

        diagnostics: list[str] = []
        if lens == "pov" and not anchors.get("pov_variant_id"):
            diagnostics.append("POV lens requested without an active POV variant; epistemic retrieval stays conservative.")
        if not focus:
            diagnostics.append("No explicit or active-scene entity anchors; retrieval may rely on scoped text evidence.")

        return NarrativeContextPlan(
            version=self.VERSION,
            route=route_value,
            intent=intent.value,
            lens=lens,
            focus_resources=focus,
            scene_anchors=anchors,
            dimensions={k: round(v, 3) for k, v in dimensions.items()},
            required_lanes=required_lanes,
            optional_lanes=optional_lanes,
            preserve_lanes=preserve_lanes,
            lane_weights=lane_weights,
            lane_token_budget=lane_token_budget,
            policies={
                "canon_precedence": True,
                "derived_continuity_is_non_authoritative": True,
                "ambiguity_policy": "abstain_and_surface",
                "pov_boundary": "enforce_scope_gate" if lens in {"scene", "pov"} else "author_lens",
                "future_knowledge": "allowed" if bool(getattr(scope, "allow_future_author_knowledge", False)) else "blocked",
                "fuzzy_identity_merge": False,
            },
            diagnostics=diagnostics,
        )
''')


# ---------------------------------------------------------------------------
# Memory public model: relationships lane + explicit context-plan trace.
# ---------------------------------------------------------------------------
replace_once(
    "src/memory/models.py",
    '    SPATIAL = "spatial"\n    THREADS = "threads"\n',
    '    SPATIAL = "spatial"\n    RELATIONSHIPS = "relationships"\n    THREADS = "threads"\n',
)
replace_once(
    "src/memory/models.py",
    '    normalized_query: str = ""\n\n    def to_dict(self) -> dict[str, Any]:\n',
    '    normalized_query: str = ""\n    context_plan: dict[str, Any] = field(default_factory=dict)\n\n    def to_dict(self) -> dict[str, Any]:\n',
)
replace_once(
    "src/memory/models.py",
    '            "normalized_query": self.normalized_query,\n',
    '            "normalized_query": self.normalized_query,\n            "context_plan": self.context_plan,\n',
)


# ---------------------------------------------------------------------------
# Query compiler/engine: plan-aware lane selection, relationships, continuity.
# ---------------------------------------------------------------------------
replace_once(
    "src/memory/query.py",
    '    def compile(self, query: str, scope: MemoryQueryContext) -> QueryPlan:\n        route = self.route(query)\n        entities = self.resolve_entities(query, scope.explicit_references)\n',
    '''    def compile(self, query: str, scope: MemoryQueryContext, context_plan: dict[str, Any] | None = None) -> QueryPlan:\n        route = self.route(query)\n        context_plan = dict(context_plan or {})\n        entities = self.resolve_entities(query, scope.explicit_references)\n        seen_entities = {(item.get("type"), item.get("id")) for item in entities}\n        for focus in context_plan.get("focus_resources") or []:\n            key = (str(focus.get("type") or ""), str(focus.get("id") or ""))\n            if not key[0] or not key[1] or key in seen_entities:\n                continue\n            seen_entities.add(key)\n            entities.append({\n                "type": key[0], "id": key[1], "label": focus.get("label") or key[1],\n                "method": "context_plan", "confidence": float(focus.get("confidence") or 1.0),\n            })\n''',
)
replace_once(
    "src/memory/query.py",
    '            QueryRoute.CURRENT_STATE: ([RetrievalLane.STRUCTURED_STATE], [RetrievalLane.EVENTS]),\n',
    '            QueryRoute.CURRENT_STATE: ([RetrievalLane.STRUCTURED_STATE], [RetrievalLane.RELATIONSHIPS, RetrievalLane.EVENTS]),\n',
)
replace_once(
    "src/memory/query.py",
    '            QueryRoute.EPISTEMIC_STATE: ([RetrievalLane.EPISTEMIC], [RetrievalLane.EVENTS, RetrievalLane.FTS_MANUSCRIPT]),\n',
    '            QueryRoute.EPISTEMIC_STATE: ([RetrievalLane.EPISTEMIC], [RetrievalLane.RELATIONSHIPS, RetrievalLane.EVENTS, RetrievalLane.FTS_MANUSCRIPT]),\n',
)
replace_once(
    "src/memory/query.py",
    '            QueryRoute.STORY_CONTINUE: ([], [RetrievalLane.STRUCTURED_STATE, RetrievalLane.EVENTS, RetrievalLane.THREADS, RetrievalLane.FTS_MANUSCRIPT, RetrievalLane.FTS_CHAT, RetrievalLane.DENSE]),\n',
    '            QueryRoute.STORY_CONTINUE: ([], [RetrievalLane.CONTINUITY, RetrievalLane.STRUCTURED_STATE, RetrievalLane.EPISTEMIC, RetrievalLane.RELATIONSHIPS, RetrievalLane.EVENTS, RetrievalLane.SPATIAL, RetrievalLane.THREADS, RetrievalLane.FTS_MANUSCRIPT, RetrievalLane.FTS_CHAT, RetrievalLane.DENSE]),\n',
)
replace_once(
    "src/memory/query.py",
    '''        required, optional = policies[route]\n        fts_lanes = {RetrievalLane.FTS_MANUSCRIPT, RetrievalLane.FTS_CHAT, RetrievalLane.FTS_SUMMARY, RetrievalLane.FTS_IMPORT}\n''',
    '''        required, optional = [*policies[route][0]], [*policies[route][1]]\n        for raw in context_plan.get("required_lanes") or []:\n            try:\n                lane = RetrievalLane(str(raw))\n            except ValueError:\n                continue\n            if lane not in required:\n                required.append(lane)\n            optional = [item for item in optional if item != lane]\n        for raw in context_plan.get("optional_lanes") or []:\n            try:\n                lane = RetrievalLane(str(raw))\n            except ValueError:\n                continue\n            if lane not in required and lane not in optional:\n                optional.append(lane)\n        fts_lanes = {RetrievalLane.FTS_MANUSCRIPT, RetrievalLane.FTS_CHAT, RetrievalLane.FTS_SUMMARY, RetrievalLane.FTS_IMPORT}\n''',
)
replace_once(
    "src/memory/query.py",
    '''        budget = max(8, self.config.max_candidates // max(1, len(required) + len(optional)))\n        return QueryPlan(\n            route=route,\n            scope=scope,\n            resolved_entities=entities,\n            required_lanes=required,\n            optional_lanes=optional,\n            forbidden_lanes=[],\n            per_lane_candidate_budget={lane.value: budget for lane in required + optional},\n            final_candidate_budget=self.config.final_k,\n            trace=self.config.trace_enabled,\n            normalized_query=" ".join(query.split()),\n        )\n''',
    '''        lanes = list(dict.fromkeys(required + optional))\n        weights = {str(k): max(0.05, float(v)) for k, v in (context_plan.get("lane_weights") or {}).items()}\n        total_weight = sum(weights.get(lane.value, 1.0) for lane in lanes) or 1.0\n        candidate_budgets = {\n            lane.value: max(2, int(round(self.config.max_candidates * weights.get(lane.value, 1.0) / total_weight)))\n            for lane in lanes\n        }\n        return QueryPlan(\n            route=route,\n            scope=scope,\n            resolved_entities=entities,\n            required_lanes=required,\n            optional_lanes=optional,\n            forbidden_lanes=[],\n            per_lane_candidate_budget=candidate_budgets,\n            final_candidate_budget=self.config.final_k,\n            trace=self.config.trace_enabled,\n            normalized_query=" ".join(query.split()),\n            context_plan=context_plan,\n        )\n''',
)

# Install a non-authoritative Discovery pointer; attach_discovery fills it later.
replace_once(
    "src/memory/query.py",
    '        self.reranker = reranker or DisabledRerankerProvider()\n',
    '        self.reranker = reranker or DisabledRerankerProvider()\n        self.discovery = None\n',
)

# Add relationship and continuity retrieval immediately before FTS retrieval.
replace_once(
    "src/memory/query.py",
    '''    def _fts(self, query: str, lane: RetrievalLane, budget: int) -> list[MemoryCandidate]:\n''',
    r'''    def _relationships(self, plan: QueryPlan) -> list[MemoryCandidate]:
        if not plan.scope.world_id:
            return []
        output: list[MemoryCandidate] = []
        seen: set[str] = set()
        for variant in self._variant_targets(plan):
            try:
                rows = self.workspace.list_relationships(
                    world_id=plan.scope.world_id,
                    branch_id=plan.scope.branch_id,
                    variant_id=variant["id"],
                )
            except Exception:
                rows = []
            for row in rows:
                if row["id"] in seen:
                    continue
                seen.add(row["id"])
                canon = str(row.get("canon_status") or "") == "canon"
                output.append(MemoryCandidate(
                    id=row["id"], lane=RetrievalLane.RELATIONSHIPS,
                    text=f"{row.get('subject_name') or row.get('subject_variant_id')} —{row.get('relation_type') or 'related_to'}→ {row.get('object_name') or row.get('object_variant_id')}",
                    source_type="relationship", source_id=row["id"],
                    world_id=plan.scope.world_id, branch_id=plan.scope.branch_id,
                    authority=Authority.USER_ACCEPTED_WORLD_CANON.value if canon else Authority.USER_EXPLICIT_NOTE.value,
                    trust_level=TrustLevel.TRUSTED_LOCAL.value, importance=.92,
                    metadata={"structured": True, "relationship": row},
                ))
        return output[:plan.per_lane_candidate_budget.get(RetrievalLane.RELATIONSHIPS.value, 20)]

    def _continuity_subjects(self, plan: QueryPlan) -> list[tuple[str, str]]:
        discovery = getattr(self, "discovery", None)
        if discovery is None:
            return []
        subjects: list[tuple[str, str]] = []
        seen: set[str] = set()
        for item in plan.resolved_entities:
            resource_type, resource_id = item.get("type"), item.get("id")
            label = str(item.get("label") or resource_id or "entity")
            try:
                if resource_type == "entity_variant":
                    variant = self.workspace.get_variant(resource_id)
                    resource_type, resource_id = "entity_family", variant["family_id"]
                    label = str(variant.get("display_name") or label)
                if resource_type != "entity_family":
                    continue
                key = discovery.store.find_subject_key_for_resource(
                    project_id=plan.scope.project_id, world_id=plan.scope.world_id,
                    resource_type="entity_family", resource_id=resource_id,
                )
            except Exception:
                key = None
            if key and key not in seen:
                seen.add(key)
                subjects.append((key, label))
        return subjects

    def _continuity(self, plan: QueryPlan) -> list[MemoryCandidate]:
        discovery = getattr(self, "discovery", None)
        resolver = getattr(discovery, "continuity", None) if discovery is not None else None
        if resolver is None or not plan.scope.world_id:
            return []
        output: list[MemoryCandidate] = []
        for subject_key, label in self._continuity_subjects(plan):
            try:
                current = resolver.current_view(plan.scope, subject_key=subject_key)
            except Exception:
                current = {"heads": [], "ambiguous": []}
            for head in current.get("heads") or []:
                knowledge = str(head.get("knowledge_state") or "detected")
                output.append(MemoryCandidate(
                    id=f"CONT:{head['id']}", lane=RetrievalLane.CONTINUITY,
                    text=f"CURRENT {label}.{head.get('predicate')} = {head.get('value')!r} [{knowledge}; derived continuity]",
                    source_type="continuity_head", source_id=head["id"],
                    project_id=plan.scope.project_id, world_id=plan.scope.world_id,
                    branch_id=plan.scope.branch_id, authority=f"discovery_{knowledge}",
                    trust_level=TrustLevel.USER_PROVIDED.value, importance=.98,
                    metadata={"structured": True, "continuity_kind": "current", "proposition": head},
                ))
            for ambiguous in current.get("ambiguous") or []:
                output.append(MemoryCandidate(
                    id=f"CONT-AMB:{subject_key}:{ambiguous.get('predicate')}", lane=RetrievalLane.CONTINUITY,
                    text=f"AMBIGUOUS {label}.{ambiguous.get('predicate')}; visible heads={ambiguous.get('proposition_ids')}. Do not choose a value without explicit resolution.",
                    source_type="continuity_ambiguity", source_id=subject_key,
                    project_id=plan.scope.project_id, world_id=plan.scope.world_id,
                    branch_id=plan.scope.branch_id, authority="derived_continuity",
                    trust_level=TrustLevel.USER_PROVIDED.value, importance=1.0,
                    metadata={"structured": True, "ambiguity": True, "continuity_kind": "ambiguous", "detail": ambiguous},
                ))
            try:
                forms = resolver.list_forms(plan.scope, subject_key=subject_key)
            except Exception:
                forms = []
            for form in forms[-2:]:
                output.append(MemoryCandidate(
                    id=form["id"], lane=RetrievalLane.CONTINUITY,
                    text=f"FORM {label}: {form.get('state')!r} ({form.get('reason')})",
                    source_type="continuity_form", source_id=form["id"],
                    project_id=plan.scope.project_id, world_id=plan.scope.world_id,
                    branch_id=plan.scope.branch_id, story_order=form.get("story_order"),
                    authority="derived_continuity", trust_level=TrustLevel.USER_PROVIDED.value,
                    importance=.82, metadata={"structured": True, "continuity_kind": "form", "form": form},
                ))
            try:
                events = resolver.list_events(plan.scope, subject_key=subject_key)
            except Exception:
                events = []
            for event in events[-4:]:
                output.append(MemoryCandidate(
                    id=event["id"], lane=RetrievalLane.CONTINUITY,
                    text=f"EVENT {event.get('summary') or event.get('event_type')} · causal_links={len(event.get('causal_links') or [])}",
                    source_type="continuity_event", source_id=event["id"],
                    project_id=plan.scope.project_id, world_id=plan.scope.world_id,
                    branch_id=plan.scope.branch_id, story_order=event.get("story_order"),
                    authority="derived_continuity", trust_level=TrustLevel.USER_PROVIDED.value,
                    importance=.88, metadata={"structured": True, "continuity_kind": "event", "event": event},
                ))
            try:
                conflicts = resolver.list_conflicts(plan.scope, subject_key=subject_key)
            except Exception:
                conflicts = []
            for conflict in conflicts[:4]:
                output.append(MemoryCandidate(
                    id=conflict["id"], lane=RetrievalLane.CONTINUITY,
                    text=f"UNRESOLVED CONFLICT {label}.{conflict.get('predicate')}: {conflict.get('left', {}).get('value')!r} ↔ {conflict.get('right', {}).get('value')!r}. Abstain until resolved.",
                    source_type="continuity_conflict", source_id=conflict["id"],
                    project_id=plan.scope.project_id, world_id=plan.scope.world_id,
                    branch_id=plan.scope.branch_id, authority="derived_continuity",
                    trust_level=TrustLevel.USER_PROVIDED.value, importance=1.0,
                    metadata={"structured": True, "ambiguity": True, "continuity_kind": "conflict", "conflict": conflict},
                ))
        output.sort(key=lambda item: (not bool(item.metadata.get("ambiguity")), -item.importance, -(item.story_order or -1e12)))
        return output[:plan.per_lane_candidate_budget.get(RetrievalLane.CONTINUITY.value, 24)]

    def _fts(self, query: str, lane: RetrievalLane, budget: int) -> list[MemoryCandidate]:
''',
)
replace_once(
    "src/memory/query.py",
    '        if lane == RetrievalLane.SPATIAL: return self._spatial(plan)\n        if lane == RetrievalLane.EPISTEMIC: return self._epistemic(plan)\n',
    '        if lane == RetrievalLane.SPATIAL: return self._spatial(plan)\n        if lane == RetrievalLane.RELATIONSHIPS: return self._relationships(plan)\n        if lane == RetrievalLane.EPISTEMIC: return self._epistemic(plan)\n',
)
replace_once(
    "src/memory/query.py",
    '        if lane == RetrievalLane.CONTINUITY: return []\n',
    '        if lane == RetrievalLane.CONTINUITY: return self._continuity(plan)\n',
)
replace_once(
    "src/memory/query.py",
    '    def _rrf(self, lane_results: dict[RetrievalLane, list[MemoryCandidate]]) -> list[MemoryCandidate]:\n',
    '    def _rrf(self, lane_results: dict[RetrievalLane, list[MemoryCandidate]], plan: QueryPlan) -> list[MemoryCandidate]:\n',
)
replace_once(
    "src/memory/query.py",
    '                current.ranks[lane.value] = rank\n                current.score += 1.0 / (self.config.rrf_k + rank)\n',
    '                current.ranks[lane.value] = rank\n                lane_weight = float((plan.context_plan.get("lane_weights") or {}).get(lane.value, 1.0))\n                current.score += max(0.05, lane_weight) / (self.config.rrf_k + rank)\n',
)

# Replace token fitting with lane-aware semantic fitting.
start = read("src/memory/query.py").index('    @staticmethod\n    def _fit_token_budget(')
end = read("src/memory/query.py").index('    @staticmethod\n    def _pack(', start)
text = read("src/memory/query.py")
new_fit = r'''    @staticmethod
    def _fit_token_budget(candidates: list[MemoryCandidate], token_budget: int | None,
                          context_plan: dict[str, Any] | None = None) -> list[MemoryCandidate]:
        if token_budget is None:
            return candidates
        remaining = max(0, int(token_budget) - 72)
        if remaining <= 0:
            return []
        plan = context_plan or {}
        lane_caps = {str(k): max(0, int(v)) for k, v in (plan.get("lane_token_budget") or {}).items()}
        preserve = [str(x) for x in (plan.get("preserve_lanes") or [])]
        usage: Counter[str] = Counter()
        selected: list[MemoryCandidate] = []
        selected_ids: set[str] = set()

        def cost(item: MemoryCandidate) -> int:
            return max(16, len(item.text) // 4 + 20)

        def add(item: MemoryCandidate, *, respect_cap: bool) -> bool:
            nonlocal remaining
            if item.id in selected_ids:
                return False
            item_cost = cost(item)
            cap = lane_caps.get(item.lane.value)
            if respect_cap and cap is not None and usage[item.lane.value] + item_cost > cap:
                return False
            if item_cost > remaining:
                return False
            selected.append(item); selected_ids.add(item.id)
            usage[item.lane.value] += item_cost; remaining -= item_cost
            return True

        # First guarantee one high-ranked item from each important narrative
        # dimension when it exists. This is what keeps POV/continuity alive when
        # source evidence is verbose.
        for lane_name in preserve:
            item = next((row for row in candidates if row.lane.value == lane_name and row.id not in selected_ids), None)
            if item is not None:
                add(item, respect_cap=False)

        deferred: list[MemoryCandidate] = []
        for item in candidates:
            if item.id in selected_ids:
                continue
            if not add(item, respect_cap=True):
                deferred.append(item)
        # Reuse unused lane budget after the planned allocation has had first
        # choice; global budget remains the hard ceiling.
        for item in deferred:
            add(item, respect_cap=False)
        return selected

'''
write("src/memory/query.py", text[:start] + new_fit + text[end:])

# Pack a scene-intelligence contract rather than an undifferentiated memory blob.
replace_once(
    "src/memory/query.py",
    '''            if item.lane in {RetrievalLane.STRUCTURED_STATE, RetrievalLane.TEMPORAL_STATE}: key = "ACCEPTED STATE"\n            elif item.lane == RetrievalLane.EPISTEMIC: key = "POV KNOWLEDGE & BELIEFS"\n            elif item.lane == RetrievalLane.EVENTS: key = "RELEVANT EVENTS"\n            elif item.lane == RetrievalLane.SPATIAL: key = "SPATIAL CONTEXT"\n            elif item.lane == RetrievalLane.THREADS: key = "OPEN THREADS"\n''',
    '''            if item.metadata.get("ambiguity"): key = "UNRESOLVED CONTINUITY"\n            elif item.lane == RetrievalLane.CONTINUITY: key = "ACTIVE CONTINUITY"\n            elif item.lane in {RetrievalLane.STRUCTURED_STATE, RetrievalLane.TEMPORAL_STATE}: key = "ACCEPTED STATE"\n            elif item.lane == RetrievalLane.EPISTEMIC: key = "POV KNOWLEDGE & BELIEFS"\n            elif item.lane == RetrievalLane.RELATIONSHIPS: key = "RELATIONSHIPS"\n            elif item.lane == RetrievalLane.EVENTS: key = "RELEVANT EVENTS"\n            elif item.lane == RetrievalLane.SPATIAL: key = "SPATIAL CONTEXT"\n            elif item.lane == RetrievalLane.THREADS: key = "OPEN THREADS"\n''',
)
replace_once(
    "src/memory/query.py",
    '''        lines = ["@ARLINE-MEMORY 1.0", f"route: {plan.route.value}", f"lens: {plan.scope.context_lens.value}"]\n        for title in ("ACCEPTED STATE", "POV KNOWLEDGE & BELIEFS", "RELEVANT EVENTS", "SPATIAL CONTEXT", "OPEN THREADS", "DERIVED SUMMARIES", "SOURCE EVIDENCE"):\n''',
    '''        intelligence = plan.context_plan or {}\n        if intelligence:\n            lines = [\n                "@ARLINE-NARRATIVE-CONTEXT 1.2.3",\n                f"route: {plan.route.value}",\n                f"intent: {intelligence.get('intent') or 'unspecified'}",\n                f"lens: {plan.scope.context_lens.value}",\n            ]\n            focus = [str(item.get("label") or item.get("id")) for item in intelligence.get("focus_resources") or []]\n            if focus:\n                lines.append("focus: " + ", ".join(focus[:16]))\n            lines += [\n                "", "[CONTEXT POLICY]",\n                "- Canon remains authoritative; derived continuity never grants Canon.",\n                "- Unresolved continuity conflicts must remain ambiguous rather than being guessed.",\n                "- POV/scene scope must not leak blocked future or inaccessible knowledge.",\n            ]\n        else:\n            lines = ["@ARLINE-MEMORY 1.0", f"route: {plan.route.value}", f"lens: {plan.scope.context_lens.value}"]\n        for title in ("UNRESOLVED CONTINUITY", "ACTIVE CONTINUITY", "ACCEPTED STATE", "POV KNOWLEDGE & BELIEFS", "RELATIONSHIPS", "RELEVANT EVENTS", "SPATIAL CONTEXT", "OPEN THREADS", "DERIVED SUMMARIES", "SOURCE EVIDENCE"):\n''',
)
replace_once(
    "src/memory/query.py",
    '    def execute(self, query: str, scope: MemoryQueryContext) -> RetrievalResult:\n        started = time.perf_counter(); plan = self.compiler.compile(query, scope)\n',
    '    def execute(self, query: str, scope: MemoryQueryContext, context_plan: dict[str, Any] | None = None) -> RetrievalResult:\n        started = time.perf_counter(); plan = self.compiler.compile(query, scope, context_plan=context_plan)\n',
)
replace_once(
    "src/memory/query.py",
    '        raw = self._rrf(gated_lane_results)\n',
    '        raw = self._rrf(gated_lane_results, plan)\n',
)
replace_once(
    "src/memory/query.py",
    '        selected = self._fit_token_budget(selected, scope.token_budget)\n',
    '        selected = self._fit_token_budget(selected, scope.token_budget, plan.context_plan)\n',
)


# ---------------------------------------------------------------------------
# MemoryService owns the planner and exposes the exact plan in Workspace scope.
# ---------------------------------------------------------------------------
replace_once(
    "src/memory/service.py",
    'from .store import MemoryStore\n',
    'from .store import MemoryStore\nfrom src.context.intelligence import NarrativeContextPlanner\n',
)
replace_once(
    "src/memory/service.py",
    '        self.query_engine = MemoryQueryEngine(store=store, workspace=workspace, history=history, foundation=foundation,\n                                              config=config, embedding=embedding, reranker=self.reranker)\n',
    '        self.query_engine = MemoryQueryEngine(store=store, workspace=workspace, history=history, foundation=foundation,\n                                              config=config, embedding=embedding, reranker=self.reranker)\n        self.context_planner = NarrativeContextPlanner()\n',
)
replace_once(
    "src/memory/service.py",
    '                "reranker_requested": self.config.reranker.enabled, "reranker_available": self.reranker.available()}\n',
    '                "reranker_requested": self.config.reranker.enabled, "reranker_available": self.reranker.available(),\n                "context_intelligence_version": self.context_planner.VERSION}\n',
)
replace_once(
    "src/memory/service.py",
    '''    def retrieve(self, query: str, context: MemoryQueryContext) -> RetrievalResult:\n        if not self.config.enabled or not query.strip():\n            from .models import QueryPlan, QueryRoute\n            plan = QueryPlan(QueryRoute.TEXT_RECALL, context, normalized_query=query.strip())\n            return RetrievalResult("disabled", plan, [], [], "", {}, True, "Memory retrieval is disabled.")\n        return self.query_engine.execute(query, self._enrich_context(context))\n''',
    '''    def retrieve(self, query: str, context: MemoryQueryContext, *, workspace_context=None) -> RetrievalResult:\n        if not self.config.enabled or not query.strip():\n            from .models import QueryPlan, QueryRoute\n            plan = QueryPlan(QueryRoute.TEXT_RECALL, context, normalized_query=query.strip())\n            return RetrievalResult("disabled", plan, [], [], "", {}, True, "Memory retrieval is disabled.")\n        enriched = self._enrich_context(context)\n        route = self.query_engine.compiler.route(query)\n        intelligence = self.context_planner.plan(\n            query, enriched, workspace_context=workspace_context, route=route\n        )\n        return self.query_engine.execute(query, enriched, context_plan=intelligence.to_dict())\n''',
)
replace_once(
    "src/memory/service.py",
    '''        memory_meta = {\n            "run_id": result.run_id, "route": result.plan.route.value, "selected": len(result.selected),\n            "excluded": len(result.excluded), "abstain": result.abstain, "reason": result.abstention_reason,\n            "token_budget": result.plan.scope.token_budget,\n        }\n''',
    '''        intelligence = result.plan.context_plan or {}\n        memory_meta = {\n            "run_id": result.run_id, "route": result.plan.route.value, "selected": len(result.selected),\n            "excluded": len(result.excluded), "abstain": result.abstain, "reason": result.abstention_reason,\n            "token_budget": result.plan.scope.token_budget,\n            "context_intelligence_version": intelligence.get("version"),\n            "intent": intelligence.get("intent"),\n        }\n        if intelligence:\n            workspace_context.scope["context_intelligence"] = intelligence\n''',
)
replace_once(
    "src/memory/service.py",
    '''            **memory_meta, "lens": result.plan.scope.context_lens.value, "lane_counts": result.lane_counts,\n            "packed_tokens": packed_tokens, "diagnostics": result.diagnostics,\n''',
    '''            **memory_meta, "lens": result.plan.scope.context_lens.value, "lane_counts": result.lane_counts,\n            "packed_tokens": packed_tokens, "diagnostics": result.diagnostics,\n            "dimensions": intelligence.get("dimensions") or {},\n            "preserve_lanes": intelligence.get("preserve_lanes") or [],\n            "focus_resources": intelligence.get("focus_resources") or [],\n''',
)


# Pass the Workspace anchors into the planner during all generate/analyze paths.
replace_once(
    "src/interface/web/app.py",
    '            result = memory_service.retrieve(prompt, memory_scope)\n',
    '            result = memory_service.retrieve(prompt, memory_scope, workspace_context=ws_context)\n',
)


# ---------------------------------------------------------------------------
# Application version contract.
# ---------------------------------------------------------------------------
replace_once("src/version.py", '__version__ = "1.2.2a1"', '__version__ = "1.2.3a1"')
replace_once("pyproject.toml", 'version = "1.2.2a1"', 'version = "1.2.3a1"')
replace_once(
    "uv.lock",
    'name = "arline-studio"\nversion = "1.2.2a1"',
    'name = "arline-studio"\nversion = "1.2.3a1"',
)


# ---------------------------------------------------------------------------
# v1.2.3 regression layer.
# ---------------------------------------------------------------------------
write("tests/test_v123_context_intelligence.py", r'''from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.context.intelligence import NarrativeContextPlanner
from src.history.store import HistoryStore
from src.memory import MemoryCandidate, MemoryConfig, MemoryQueryContext, MemoryService, MemoryStore, RetrievalLane
from src.memory.web import create_memory_router
from src.workspace import FoundationStore, WorkspaceContext
from src.workspace.store import WorkspaceStore


class Fixture:
    def __init__(self, root: str):
        path = Path(root) / "arline.db"
        self.workspace = WorkspaceStore(path, backup_before_migration=False)
        self.history = HistoryStore(path, backup_before_migration=False)
        self.foundation = FoundationStore(path)
        self.project = self.workspace.create_project("v123 context")
        self.world_id = self.project["default_world_id"]
        self.branch = next(x for x in self.workspace.get_world(self.world_id)["branches"] if x["kind"] == "main")
        cfg = MemoryConfig(); cfg.dense_enabled = False; cfg.final_k = 16
        store = MemoryStore(path, backup_before_migration=False)
        self.memory = MemoryService(
            store=store, workspace=self.workspace, history=self.history,
            foundation=self.foundation, config=cfg,
            lmstudio_base_url="http://127.0.0.1:1234",
        )
        create_memory_router(service=self.memory, store=store, foundation=self.foundation)
        self.discovery = self.memory.discovery
        self.session = self.history.create_session(
            prompt="v123", project_id=self.project["id"], world_id=self.world_id,
            branch_id=self.branch["id"],
        )

    def context(self, **kwargs):
        return MemoryQueryContext(
            project_id=self.project["id"], world_id=self.world_id,
            branch_id=self.branch["id"], session_id=self.session["id"],
            token_budget=kwargs.pop("token_budget", 1800), **kwargs,
        )

    def ws(self, *, pov=None, location=None, participants=None, refs=None):
        active = {
            "pov_variant_id": pov, "location_variant_id": location,
            "participants": list(participants or []), "narrative_time": "now",
        }
        autos = []
        for rid, reason in [(pov, "active scene POV"), (location, "active scene location")]:
            if rid:
                autos.append({"type": "entity_variant", "id": rid, "label": rid, "reason": reason})
        autos.extend({"type": "entity_variant", "id": rid, "label": rid, "reason": "present in active scene"} for rid in participants or [])
        return WorkspaceContext(
            version="0.2", text="@ARLINE-WORKSPACE 0.1\n", scope={"active_scene": active},
            explicit_references=list(refs or []), auto_selected=autos, estimated_tokens=32,
        )

    def family_variant(self, name: str):
        family = self.workspace.create_entity_family(
            None, name, entity_type="character", create_variant_in_world=self.world_id,
            branch_id=self.branch["id"],
        )
        variant = self.workspace.resolve_variant(family["id"], self.world_id, self.branch["id"])
        return family, variant

    def add_claim(self, *, subject_key: str, label: str, predicate: str, value, suffix: str):
        turn = self.history.add_turn(
            self.session["id"], run_id=f"RUN-V123-{suffix}", user_prompt=f"{label} {predicate} {value}",
            story="Generated.", model="fixture", mode="smart_hybrid", reasoning="off", projection_mode="off",
        )
        prop = self.discovery.store.upsert_proposition(
            project_id=self.project["id"], world_id=self.world_id, subject_type="character",
            subject_key=subject_key, subject_label=label, predicate=predicate, value=value,
            operation="update",
        )
        self.discovery.store.add_instance(
            prop["id"], source_kind="user_prompt", source_session_id=self.session["id"], source_turn_id=turn["id"],
            origin_session_id=self.session["id"], origin_turn_id=turn["id"], source_revision=f"R-{suffix}",
            project_id=self.project["id"], world_id=self.world_id, branch_id=self.branch["id"],
            story_order=float(turn.get("ordinal") or 0), span_text=turn["user_prompt"], extraction_confidence=1,
            explicitness="explicit", qualifies_review=True,
        )
        return turn, prop


class V123ContextIntelligenceTests(unittest.TestCase):
    def test_dialogue_plan_prioritizes_pov_relationship_and_continuity(self):
        planner = NarrativeContextPlanner()
        scope = MemoryQueryContext(context_lens="pov", pov_variant_id="VAR-A", token_budget=2000)
        ws = WorkspaceContext(
            version="0.2", text="", scope={"active_scene": {"pov_variant_id": "VAR-A", "participants": ["VAR-B"]}},
            auto_selected=[{"type":"entity_variant","id":"VAR-A","label":"Alex"},{"type":"entity_variant","id":"VAR-B","label":"Mira"}],
        )
        plan = planner.plan("Continue their dialogue while Alex listens carefully.", scope, workspace_context=ws, route="STORY_CONTINUE")
        self.assertEqual(plan.intent, "dialogue")
        self.assertEqual(plan.dimensions["pov"], 1.0)
        self.assertGreaterEqual(plan.dimensions["relationships"], .95)
        self.assertIn("continuity", plan.preserve_lanes)
        self.assertIn("epistemic", plan.preserve_lanes)
        self.assertIn("relationships", plan.optional_lanes)

    def test_active_scene_anchors_become_focus_resources_without_prompt_names(self):
        planner = NarrativeContextPlanner()
        scope = MemoryQueryContext(token_budget=1200)
        ws = WorkspaceContext(version="0.2", text="", scope={"active_scene": {
            "pov_variant_id":"VAR-P", "location_variant_id":"VAR-L", "participants":["VAR-X"]
        }})
        plan = planner.plan("Continue.", scope, workspace_context=ws, route="STORY_CONTINUE")
        self.assertEqual({x["id"] for x in plan.focus_resources}, {"VAR-P", "VAR-L", "VAR-X"})

    def test_plan_allocates_lane_budget_but_keeps_hard_global_ceiling(self):
        plan = NarrativeContextPlanner().plan(
            "Continue the action scene.", MemoryQueryContext(token_budget=1000), route="STORY_CONTINUE"
        )
        self.assertTrue(plan.lane_token_budget)
        self.assertTrue(all(value >= 96 for value in plan.lane_token_budget.values()))
        self.assertIn("continuity", plan.preserve_lanes)

    def test_query_compiler_injects_scene_focus_and_plan_lanes(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            family, variant = fx.family_variant("Alex")
            ws = fx.ws(participants=[variant["id"]])
            ctx = fx.context()
            plan = fx.memory.context_planner.plan("Continue.", ctx, workspace_context=ws, route="STORY_CONTINUE")
            compiled = fx.memory.query_engine.compiler.compile("Continue.", ctx, context_plan=plan.to_dict())
            self.assertTrue(any(x["id"] == variant["id"] and x["method"] == "context_plan" for x in compiled.resolved_entities))
            self.assertIn(RetrievalLane.CONTINUITY, compiled.optional_lanes)
            self.assertIn(RetrievalLane.RELATIONSHIPS, compiled.optional_lanes)

    def test_continuity_lane_retrieves_current_head_for_active_scene_entity(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            family, variant = fx.family_variant("Alex")
            fx.discovery.store.upsert_subject_link(
                project_id=fx.project["id"], world_id=fx.world_id,
                subject_key="char:alex", resource_type="entity_family", resource_id=family["id"],
            )
            fx.add_claim(subject_key="char:alex", label="Alex", predicate="state.form", value="human", suffix="HEAD")
            ws = fx.ws(participants=[variant["id"]])
            result = fx.memory.retrieve("Continue Alex's scene.", fx.context(), workspace_context=ws)
            continuity = [x for x in result.selected if x.lane == RetrievalLane.CONTINUITY]
            self.assertTrue(any("CURRENT Alex.state.form" in x.text for x in continuity))
            self.assertIn("@ARLINE-NARRATIVE-CONTEXT 1.2.3", result.packed_text)

    def test_unresolved_continuity_is_surfaced_not_guessed(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            family, variant = fx.family_variant("Alex")
            fx.discovery.store.upsert_subject_link(
                project_id=fx.project["id"], world_id=fx.world_id,
                subject_key="char:alex", resource_type="entity_family", resource_id=family["id"],
            )
            _t1, p1 = fx.add_claim(subject_key="char:alex", label="Alex", predicate="state.form", value="human", suffix="AMB1")
            t2, p2 = fx.add_claim(subject_key="char:alex", label="Alex", predicate="state.form", value="wolf", suffix="AMB2")
            fx.discovery.continuity.resolve_turn(t2["id"])
            ws = fx.ws(participants=[variant["id"]])
            result = fx.memory.retrieve("Continue the scene.", fx.context(), workspace_context=ws)
            ambiguous = [x for x in result.selected if x.metadata.get("ambiguity")]
            self.assertTrue(ambiguous)
            self.assertIn("[UNRESOLVED CONTINUITY]", result.packed_text)
            self.assertEqual(fx.discovery.store.get_proposition(p1["id"])["authority_state"], "observed")
            self.assertEqual(fx.discovery.store.get_proposition(p2["id"])["authority_state"], "observed")

    def test_relationship_lane_uses_focused_variants(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            _fa, a = fx.family_variant("Alex")
            _fb, b = fx.family_variant("Mira")
            relationship = fx.workspace.create_relationship(
                fx.world_id, a["id"], b["id"], "friend_of",
                branch_id=fx.branch["id"], canon_status="canon",
            )
            ws = fx.ws(participants=[a["id"], b["id"]])
            result = fx.memory.retrieve("Continue their dialogue.", fx.context(), workspace_context=ws)
            rows = [x for x in result.selected if x.lane == RetrievalLane.RELATIONSHIPS]
            self.assertTrue(any(x.id == relationship["id"] for x in rows))
            self.assertIn("[RELATIONSHIPS]", result.packed_text)

    def test_tight_budget_preserves_semantic_lanes_before_verbose_source(self):
        candidates = [
            MemoryCandidate("SRC", RetrievalLane.FTS_MANUSCRIPT, "x" * 900, "document", "D"),
            MemoryCandidate("CONT", RetrievalLane.CONTINUITY, "current form human", "continuity_head", "P"),
            MemoryCandidate("POV", RetrievalLane.EPISTEMIC, "Alex knows secret A", "epistemic", "E"),
        ]
        fitted = fx_engine_fit(candidates, 190, {
            "preserve_lanes": ["continuity", "epistemic"],
            "lane_token_budget": {"continuity": 100, "epistemic": 100, "fts_manuscript": 100},
        })
        self.assertEqual([x.id for x in fitted], ["CONT", "POV"])

    def test_workspace_context_exposes_exact_context_plan(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            family, variant = fx.family_variant("Alex")
            ws = fx.ws(participants=[variant["id"]])
            result = fx.memory.retrieve("Continue.", fx.context(), workspace_context=ws)
            augmented = fx.memory.augment_workspace_context(ws, result)
            self.assertEqual(augmented.scope["context_intelligence"]["version"], "1.2.3a1")
            self.assertEqual(augmented.scope["memory"]["context_intelligence_version"], "1.2.3a1")
            self.assertIn("@ARLINE-NARRATIVE-CONTEXT 1.2.3", augmented.text)

    def test_memory_status_reports_context_intelligence_version(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            self.assertEqual(fx.memory.status()["context_intelligence_version"], "1.2.3a1")


def fx_engine_fit(candidates, budget, plan):
    from src.memory.query import MemoryQueryEngine
    return MemoryQueryEngine._fit_token_budget(candidates, budget, plan)


if __name__ == "__main__":
    unittest.main()
''')


# ---------------------------------------------------------------------------
# Milestone documentation.
# ---------------------------------------------------------------------------
write("docs/V123_NARRATIVE_CONTEXT_INTELLIGENCE.md", r'''# Arline v1.2.3 — Narrative Context Intelligence

v1.2.3 sits above the v1.2.2 continuity model. It does not invent a second
memory system and it does not ask an LLM to decide what is true. Its job is to
make the existing sources agree on **what matters for this scene**.

## Top-down contract

```text
Current request + active Scene Card
              ↓
      NarrativeContextPlan
       ├ intent
       ├ focus resources
       ├ POV / time / location anchors
       ├ narrative dimensions
       ├ lane weights
       └ token allocation
              ↓
 Workspace + Memory + Continuity + ScopeGate
              ↓
 @ARLINE-NARRATIVE-CONTEXT 1.2.3
       ├ unresolved continuity
       ├ active continuity
       ├ accepted/current state
       ├ POV knowledge & beliefs
       ├ relationships
       ├ events & causes
       ├ spatial context
       ├ open threads
       └ source evidence
              ↓
             Writer
```

The planner is deterministic and rebuildable. Canon authority, branch/fork
visibility, temporal visibility and POV access remain enforced by the layers
below it.

## Narrative intents

The first implementation distinguishes continuation, dialogue, action,
description, transition, causal lookup, recall, summary, continuity review and
branch comparison. The intent changes *priority and budget*, never truth.

Examples:

- dialogue prioritizes POV + relationships + continuity;
- action prioritizes events + state + continuity + spatial anchors;
- description prioritizes state + spatial detail;
- transition prioritizes continuity + before/after events;
- causal questions prioritize events/causes and supporting source evidence.

## Active-scene focus

Explicit `@` references are always first-class focus resources. When the prompt
is terse (`Continue.`), the planner also uses the active scene POV, location and
participants as focus anchors. This prevents the retrieval layer from requiring
the user to repeat names that the workspace already knows.

## Continuity retrieval lane

v1.2.2 continuity is now a real Memory lane. It can surface:

- current derived heads;
- FORM snapshots;
- EVENT/CAUSE history;
- unresolved ambiguity/conflict diagnostics.

Ambiguous state is rendered as an explicit abstention. The planner never chooses
one competing value merely to make the writer prompt look cleaner.

## Relationships lane

Relationships connected to focused variants are retrieved structurally rather
than rediscovered through text search. Canon relationships retain stronger
authority scoring while draft/non-canon relationships remain clearly lower
authority context.

## POV boundary

POV is a planning dimension, not a prompt decoration. POV/scene lenses preserve
the epistemic lane and continue to rely on ScopeGate to block inaccessible or
future knowledge. Author lens may see author-only future context only when the
existing scope explicitly allows it.

## Semantic token budgeting

The planner allocates the Memory token allowance across lanes. Under pressure,
important lanes receive one protected slot before verbose source evidence can
consume the remainder. Unused allocations may be reused afterward, so the plan
is a priority system rather than a rigid quota system.

The global token budget remains the hard ceiling.

## Authority rule

```text
Context relevance ≠ truth
Continuity reconstruction ≠ Canon
High retrieval score ≠ Canon
```

v1.2.3 may decide that a piece of evidence is important enough to show the
writer. It may not upgrade that evidence's authority.

## Deliberate non-goals

- no LLM context router;
- no fuzzy identity merge;
- no automatic Canon promotion;
- no autonomous retcon;
- no semantic branch merge;
- no second vector/database subsystem.

Those remain separate later milestones.
''')

status_path = "docs/V12_IMPLEMENTATION_STATUS.md"
status = read(status_path)
if "## v1.2.3 — Narrative Context Intelligence" not in status:
    status += r'''

## v1.2.3 — Narrative Context Intelligence

The v1.2.3 milestone adds one deterministic orchestration layer above Workspace,
Memory and the v1.2.2 continuity graph.

Implemented:

- `NarrativeContextPlan` classifies the current narrative intent and records the active POV, location, participants and explicit references as focus anchors;
- scene anchors are injected into retrieval even for terse prompts such as `Continue.`;
- Continuity is a real retrieval lane exposing current heads, Forms, Events/Causes and unresolved conflicts without granting Canon;
- Relationships are a real structured retrieval lane for focused variants;
- dialogue/action/description/transition/causal/recall/summary/continuity-review/branch-compare intents receive different deterministic dimension weights;
- POV, continuity and other high-value dimensions receive protected semantic slots under tight token budgets before verbose source evidence;
- lane weights influence RRF ranking while ScopeGate remains authoritative for branch, temporal and POV visibility;
- the packed generation context is now explicitly labeled `@ARLINE-NARRATIVE-CONTEXT 1.2.3` and separates unresolved continuity, active continuity, accepted state, POV knowledge, relationships, events, spatial context, threads and source evidence;
- the exact context plan is exposed in `workspace_context.scope.context_intelligence` and Memory diagnostics so every automatic selection remains inspectable;
- context relevance never mutates Discovery or Canon authority.

The milestone deliberately avoids an LLM-based context router. Context planning
is deterministic, cheap and rebuildable; model intelligence remains focused on
writing rather than deciding source authority.
'''
    write(status_path, status)

print("v1.2.3 top-down context intelligence pass applied")
