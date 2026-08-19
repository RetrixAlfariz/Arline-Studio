from __future__ import annotations

from collections import Counter, defaultdict
import re
import time
from typing import Any

from .config import MemoryConfig
from .embedding import DisabledEmbeddingProvider, EmbeddingProvider, RerankerProvider, DisabledRerankerProvider
from .models import (
    Authority,
    MemoryCandidate,
    MemoryQueryContext,
    QueryPlan,
    QueryRoute,
    RetrievalLane,
    RetrievalResult,
    SemanticClass,
    TrustLevel,
)
from .scope import ScopeGate
from .security import evidence_wrapper
from .store import MemoryStore, make_id


class QueryCompiler:
    """Deterministic-first narrative query compiler."""

    STORY_CONTINUE_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:continue|write|lanjut(?:kan)?|tulis(?:kan)?)\b|"
        r"\bcontinue\s+(?:the\s+)?(?:current\s+)?(?:scene|dialogue)\b|"
        r"\b(?:write|tulis(?:kan)?)\s+(?:the\s+)?(?:next|current)?\s*(?:scene|adegan|dialogue)\b",
        re.I,
    )
    ROUTE_PATTERNS: list[tuple[QueryRoute, re.Pattern[str]]] = [
        (QueryRoute.EPISTEMIC_STATE, re.compile(r"\b(know|knew|believe|believed|suspect|aware|secret|tahu|percaya|curiga)\b", re.I)),
        (QueryRoute.TEMPORAL_STATE, re.compile(r"\b(before|after|at the time|used to|previously|historical|sebelum|setelah|saat itu|dulu)\b", re.I)),
        (QueryRoute.BRANCH_COMPARE, re.compile(r"\b(compare branches?|alternate timeline|what-if|bandingkan cabang|timeline alternatif)\b", re.I)),
        (QueryRoute.CONTINUITY_CHECK, re.compile(r"\b(continuity|contradiction|inconsistent|conflict|kontinuitas|kontradiksi|tidak konsisten)\b", re.I)),
        (QueryRoute.GLOBAL_SUMMARY, re.compile(r"\b(summar(?:y|ize)|overview|across the chapter|recap|ringkas|rangkuman)\b", re.I)),
        (QueryRoute.SPATIAL_LOOKUP, re.compile(r"\b(where|inside|contains?|room|stored|located|near|adjacent|happen(?:ed)?\s+where|di mana|ruang|berisi|tersimpan)\b", re.I)),
        (QueryRoute.THREAD_LOOKUP, re.compile(r"\b(unresolved|promise|mystery|goal|foreshadow|thread|belum selesai|janji|misteri|tujuan)\b", re.I)),
        (QueryRoute.WHY_CAUSAL, re.compile(r"\b(why|cause|caused|because|motivated|mengapa|kenapa|sebab)\b", re.I)),
        (QueryRoute.EVENT_LOOKUP, re.compile(r"\b(when|what happened|event|changed|happened|kapan|terjadi|peristiwa|berubah)\b", re.I)),
        (QueryRoute.CURRENT_STATE, re.compile(r"\b(current|currently|now|status|sekarang|punya|milik)\b", re.I)),
    ]

    def __init__(self, workspace, foundation=None, config: MemoryConfig | None = None):
        self.workspace = workspace
        self.foundation = foundation
        self.config = config or MemoryConfig()

    def resolve_entities(self, query: str, references: list[dict[str, Any]]) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for ref in references:
            key = (str(ref.get("type") or ""), str(ref.get("id") or ""))
            if key[0] and key[1] and key not in seen:
                seen.add(key)
                resolved.append({"type": key[0], "id": key[1], "label": ref.get("label") or key[1], "method": "explicit", "confidence": 1.0, **({"selector": ref.get("selector")} if ref.get("selector") else {})})
        needle = query.casefold()
        try:
            families = self.workspace.list_entity_families(None)
        except Exception:
            families = []
        for family in sorted(families, key=lambda item: len(item.get("name") or ""), reverse=True):
            name = str(family.get("name") or "").strip()
            if name and name.casefold() in needle:
                key = ("entity_family", family["id"])
                if key not in seen:
                    seen.add(key)
                    resolved.append({"type": key[0], "id": key[1], "label": name, "method": "name", "confidence": 1.0})
        if self.foundation is not None:
            for token in re.findall(r"[\w'-]{3,}", query, flags=re.UNICODE)[:20]:
                try:
                    matches = self.foundation.alias_matches(token, limit=5)
                except Exception:
                    matches = []
                for match in matches:
                    key = (match["resource_type"], match["resource_id"])
                    if key in seen:
                        continue
                    seen.add(key)
                    resolved.append({"type": key[0], "id": key[1], "label": match["alias"], "method": "alias", "confidence": 0.85})
        return resolved[:24]

    @classmethod
    def route(cls, query: str) -> QueryRoute:
        stripped = query.strip()
        for route, pattern in cls.ROUTE_PATTERNS:
            if route == QueryRoute.CURRENT_STATE:
                continue
            if pattern.search(stripped):
                return route
        if cls.STORY_CONTINUE_PATTERN.search(stripped):
            return QueryRoute.STORY_CONTINUE
        for route, pattern in cls.ROUTE_PATTERNS:
            if route == QueryRoute.CURRENT_STATE and pattern.search(stripped):
                return route
        return QueryRoute.TEXT_RECALL

    def compile(self, query: str, scope: MemoryQueryContext, context_plan: dict[str, Any] | None = None) -> QueryPlan:
        route = self.route(query)
        context_plan = dict(context_plan or {})
        entities = self.resolve_entities(query, scope.explicit_references)
        seen_entities = {(item.get("type"), item.get("id")) for item in entities}
        for focus in context_plan.get("focus_resources") or []:
            key = (str(focus.get("type") or ""), str(focus.get("id") or ""))
            if not key[0] or not key[1] or key in seen_entities:
                continue
            seen_entities.add(key)
            entities.append({
                "type": key[0], "id": key[1], "label": focus.get("label") or key[1],
                "method": "context_plan", "confidence": float(focus.get("confidence") or 1.0),
                **({"selector": focus.get("selector")} if focus.get("selector") else {}),
            })
        policies: dict[QueryRoute, tuple[list[RetrievalLane], list[RetrievalLane]]] = {
            QueryRoute.CURRENT_STATE: ([RetrievalLane.STRUCTURED_STATE], [RetrievalLane.RELATIONSHIPS, RetrievalLane.EVENTS]),
            QueryRoute.TEMPORAL_STATE: ([RetrievalLane.TEMPORAL_STATE], [RetrievalLane.EVENTS, RetrievalLane.FTS_MANUSCRIPT]),
            QueryRoute.EVENT_LOOKUP: ([RetrievalLane.EVENTS], [RetrievalLane.FTS_MANUSCRIPT, RetrievalLane.FTS_CHAT, RetrievalLane.DENSE]),
            QueryRoute.EPISTEMIC_STATE: ([RetrievalLane.EPISTEMIC], [RetrievalLane.RELATIONSHIPS, RetrievalLane.EVENTS, RetrievalLane.FTS_MANUSCRIPT]),
            QueryRoute.SPATIAL_LOOKUP: ([RetrievalLane.SPATIAL], [RetrievalLane.EVENTS, RetrievalLane.FTS_MANUSCRIPT]),
            QueryRoute.THREAD_LOOKUP: ([RetrievalLane.THREADS], [RetrievalLane.SUMMARIES, RetrievalLane.FTS_MANUSCRIPT]),
            QueryRoute.WHY_CAUSAL: ([RetrievalLane.EVENTS, RetrievalLane.GRAPH], [RetrievalLane.FTS_MANUSCRIPT, RetrievalLane.DENSE]),
            QueryRoute.GLOBAL_SUMMARY: ([RetrievalLane.SUMMARIES], [RetrievalLane.FTS_SUMMARY, RetrievalLane.FTS_MANUSCRIPT]),
            QueryRoute.CONTINUITY_CHECK: ([RetrievalLane.CONTINUITY, RetrievalLane.STRUCTURED_STATE], [RetrievalLane.EVENTS, RetrievalLane.SPATIAL, RetrievalLane.EPISTEMIC]),
            QueryRoute.BRANCH_COMPARE: ([RetrievalLane.STRUCTURED_STATE, RetrievalLane.EVENTS], [RetrievalLane.SUMMARIES]),
            QueryRoute.STORY_CONTINUE: ([], [RetrievalLane.CONTINUITY, RetrievalLane.STRUCTURED_STATE, RetrievalLane.EPISTEMIC, RetrievalLane.RELATIONSHIPS, RetrievalLane.EVENTS, RetrievalLane.SPATIAL, RetrievalLane.THREADS, RetrievalLane.FTS_MANUSCRIPT, RetrievalLane.FTS_CHAT, RetrievalLane.DENSE]),
            QueryRoute.TEXT_RECALL: ([], [RetrievalLane.FTS_MANUSCRIPT, RetrievalLane.FTS_CHAT, RetrievalLane.FTS_SUMMARY, RetrievalLane.FTS_IMPORT, RetrievalLane.DENSE]),
        }
        required, optional = [*policies[route][0]], [*policies[route][1]]
        for raw in context_plan.get("required_lanes") or []:
            try:
                lane = RetrievalLane(str(raw))
            except ValueError:
                continue
            if lane not in required:
                required.append(lane)
            optional = [item for item in optional if item != lane]
        for raw in context_plan.get("optional_lanes") or []:
            try:
                lane = RetrievalLane(str(raw))
            except ValueError:
                continue
            if lane not in required and lane not in optional:
                optional.append(lane)
        fts_lanes = {RetrievalLane.FTS_MANUSCRIPT, RetrievalLane.FTS_CHAT, RetrievalLane.FTS_SUMMARY, RetrievalLane.FTS_IMPORT}
        if not self.config.fts_enabled:
            required = [lane for lane in required if lane not in fts_lanes]
            optional = [lane for lane in optional if lane not in fts_lanes]
        if not self.config.dense_enabled:
            required = [lane for lane in required if lane != RetrievalLane.DENSE]
            optional = [lane for lane in optional if lane != RetrievalLane.DENSE]
        lanes = list(dict.fromkeys(required + optional))
        weights = {str(k): max(0.05, float(v)) for k, v in (context_plan.get("lane_weights") or {}).items()}
        total_weight = sum(weights.get(lane.value, 1.0) for lane in lanes) or 1.0
        candidate_budgets = {
            lane.value: max(2, int(round(self.config.max_candidates * weights.get(lane.value, 1.0) / total_weight)))
            for lane in lanes
        }
        for lane in lanes:
            if lane in fts_lanes:
                candidate_budgets[lane.value] = max(16, candidate_budgets[lane.value])
        return QueryPlan(
            route=route,
            scope=scope,
            resolved_entities=entities,
            required_lanes=required,
            optional_lanes=optional,
            forbidden_lanes=[],
            per_lane_candidate_budget=candidate_budgets,
            final_candidate_budget=self.config.final_k,
            trace=self.config.trace_enabled,
            normalized_query=" ".join(query.split()),
            context_plan=context_plan,
        )


class MemoryQueryEngine:
    def __init__(self, *, store: MemoryStore, workspace, history=None, foundation=None,
                 config: MemoryConfig | None = None, embedding: EmbeddingProvider | None = None,
                 reranker: RerankerProvider | None = None):
        self.store = store
        self.workspace = workspace
        self.history = history
        self.foundation = foundation
        self.config = config or MemoryConfig()
        self.compiler = QueryCompiler(workspace, foundation, self.config)
        self.gate = ScopeGate(workspace, history)
        self.embedding = embedding or DisabledEmbeddingProvider()
        self.reranker = reranker or DisabledRerankerProvider()
        self.discovery = None

    @staticmethod
    def _candidate_from_chunk(row: dict[str, Any], lane: RetrievalLane, rank: int | None = None) -> MemoryCandidate:
        ranks = {lane.value: rank} if rank is not None else {}
        return MemoryCandidate(
            id=row["id"], lane=lane, text=row.get("display_excerpt") or row.get("text") or "",
            source_type=row.get("source_type") or "memory", source_id=row.get("source_id") or row["id"],
            project_id=row.get("project_id"), world_id=row.get("world_id"), branch_id=row.get("branch_id"),
            session_id=row.get("session_id"), world_time=row.get("world_time"), story_order=row.get("story_order"),
            semantic_class=row.get("semantic_class") or SemanticClass.EVIDENCE.value,
            semantic_status=row.get("semantic_status") or "active", authority=row.get("authority") or Authority.PROJECT_MANUSCRIPT.value,
            trust_level=row.get("trust_level") or TrustLevel.TRUSTED_LOCAL.value,
            importance=float(row.get("importance") or 0.5), extraction_confidence=float(row.get("extraction_confidence") or 1.0),
            identity_confidence=float(row.get("identity_confidence") or 1.0), ranks=ranks,
            metadata={"domain": row.get("domain"), "snippet": row.get("snippet"), "checksum": row.get("checksum"), "source_recorded_at": row.get("source_recorded_at")},
        )

    @staticmethod
    def _resource_targets(plan: QueryPlan) -> list[tuple[str, str]]:
        targets = []
        for item in plan.resolved_entities:
            targets.append((item["type"], item["id"]))
        return targets

    def _variant_targets(self, plan: QueryPlan) -> list[dict[str, Any]]:
        variants: list[dict[str, Any]] = []
        for resource_type, resource_id in self._resource_targets(plan):
            try:
                if resource_type == "entity_variant":
                    variants.append(self.workspace.get_variant(resource_id))
                elif resource_type == "entity_family":
                    rows = self.workspace.list_variants(family_id=resource_id, world_id=plan.scope.world_id, branch_id=plan.scope.branch_id)
                    variants.extend(rows[:2])
            except Exception:
                continue
        return variants

    @staticmethod
    def _selector_for_variant(plan: QueryPlan, variant: dict[str, Any]) -> str | None:
        for item in plan.resolved_entities:
            selector = str(item.get("selector") or "").strip().casefold()
            if not selector:
                continue
            if item.get("type") == "entity_variant" and item.get("id") == variant.get("id"):
                return selector
            if item.get("type") == "entity_family" and item.get("id") == variant.get("family_id"):
                return selector
        return None

    def _structured_state(self, plan: QueryPlan, lane: RetrievalLane) -> list[MemoryCandidate]:
        if not plan.scope.world_id:
            return []
        output: list[MemoryCandidate] = []
        for variant in self._variant_targets(plan):
            selector = self._selector_for_variant(plan, variant)
            rows = self.store.query_current_state(plan.scope.world_id, plan.scope.branch_id, "entity_variant", variant["id"])
            current = variant.get("current_state") or {}
            attributes = variant.get("attributes") or {}
            selected_section: dict[str, Any] | None = None
            if selector == "voice":
                selected_section = variant.get("voice") or {}
            elif selector == "knowledge":
                selected_section = variant.get("knowledge") or {}
            elif selector == "beliefs":
                selected_section = variant.get("beliefs") or {}
            elif selector == "state":
                selected_section = current
            elif selector == "appearance":
                merged = {**attributes, **current}
                appearance_words = ("appearance", "hair", "face", "skin", "eye", "height", "body", "chest", "clothing", "outfit", "physical", "form", "voice")
                filtered = {k: v for k, v in merged.items() if any(word in str(k).casefold() for word in appearance_words)}
                selected_section = filtered or merged
            if selected_section is not None:
                rows = [
                    {"state_key": f"{selector}.{key}", "value": value, "source_type": "entity_variant", "source_id": variant["id"], "authority": Authority.USER_ACCEPTED_WORLD_CANON.value}
                    for key, value in selected_section.items()
                ]
            elif not rows:
                rows = [
                    {"state_key": key, "value": value, "source_type": "entity_variant", "source_id": variant["id"], "authority": Authority.USER_ACCEPTED_WORLD_CANON.value}
                    for key, value in {**attributes, **current}.items()
                ]
            for row in rows:
                output.append(MemoryCandidate(
                    id=f"STATE:{variant['id']}:{row['state_key']}", lane=lane,
                    text=f"{variant.get('display_name', variant['id'])}.{row['state_key']} = {row.get('value')!r}",
                    source_type=row.get("source_type") or "entity_variant", source_id=row.get("source_id") or variant["id"],
                    world_id=plan.scope.world_id, branch_id=plan.scope.branch_id,
                    authority=row.get("authority") or Authority.USER_ACCEPTED_WORLD_CANON.value,
                    trust_level=TrustLevel.TRUSTED_LOCAL.value, importance=0.95,
                    metadata={"structured": True, "owner_id": variant["id"], "state_key": row["state_key"], "value": row.get("value")},
                ))
        return output

    def _temporal_state(self, plan: QueryPlan) -> list[MemoryCandidate]:
        if not plan.scope.world_id:
            return []
        output = []
        for variant in self._variant_targets(plan):
            for row in self.store.state_at(world_id=plan.scope.world_id, branch_id=plan.scope.branch_id,
                                           owner_type="entity_variant", owner_id=variant["id"], story_order=plan.scope.story_order):
                output.append(MemoryCandidate(
                    id=row["id"], lane=RetrievalLane.TEMPORAL_STATE,
                    text=f"At the requested story time, {variant.get('display_name', variant['id'])}.{row['state_key']} = {row.get('value')!r}",
                    source_type=row.get("source_type") or "state_interval", source_id=row.get("source_id") or row["id"],
                    world_id=row.get("world_id"), branch_id=row.get("branch_id"), story_order=row.get("story_order_from"),
                    authority=row.get("authority") or Authority.USER_ACCEPTED_WORLD_CANON.value,
                    trust_level=TrustLevel.TRUSTED_LOCAL.value, importance=0.95,
                    metadata={"structured": True, "interval": row},
                ))
        return output

    def _events(self, plan: QueryPlan) -> list[MemoryCandidate]:
        if not plan.scope.world_id:
            return []
        try:
            events = self.workspace.list_timeline_events(plan.scope.world_id, branch_id=plan.scope.branch_id)
        except Exception:
            events = []
        labels = {str(item.get("label") or "").casefold() for item in plan.resolved_entities}
        output = []
        for event in events:
            summary = str(event.get("summary") or "")
            if labels and not any(label and label in summary.casefold() for label in labels):
                patch_text = str(event.get("state_patch") or "").casefold()
                if not any(label and label in patch_text for label in labels):
                    continue
            order = event.get("order_key")
            output.append(MemoryCandidate(
                id=event["id"], lane=RetrievalLane.EVENTS, text=summary,
                source_type="timeline_event", source_id=event["id"], project_id=event.get("project_id"),
                world_id=event.get("world_id"), branch_id=event.get("branch_id"), story_order=order,
                authority=Authority.ACCEPTED_EVENT.value if event.get("status") in {"accepted", "canon"} else Authority.USER_EXPLICIT_NOTE.value,
                trust_level=TrustLevel.TRUSTED_LOCAL.value, importance=0.85,
                metadata={"event": event, "source_recorded_at": event.get("updated_at") or event.get("created_at")},
            ))
        output.sort(key=lambda item: (item.story_order is None, -(item.story_order or 0)))
        return output[:plan.per_lane_candidate_budget.get(RetrievalLane.EVENTS.value, 20)]

    def _spatial(self, plan: QueryPlan) -> list[MemoryCandidate]:
        if not plan.scope.world_id:
            return []
        output = []
        for resource_type, resource_id in self._resource_targets(plan):
            graph = self.store.spatial_neighborhood(world_id=plan.scope.world_id, branch_id=plan.scope.branch_id,
                                                    resource_type=resource_type, resource_id=resource_id, depth=2)
            for edge in graph["edges"]:
                output.append(MemoryCandidate(
                    id=edge["id"], lane=RetrievalLane.SPATIAL,
                    text=f"{edge['subject_type']}:{edge['subject_id']} {edge['relation']} {edge['object_type']}:{edge['object_id']}",
                    source_type=edge.get("source_type") or "spatial_edge", source_id=edge.get("source_id") or edge["id"],
                    world_id=edge["world_id"], branch_id=edge.get("branch_id"), authority=edge.get("authority") or Authority.USER_ACCEPTED_WORLD_CANON.value,
                    trust_level=TrustLevel.TRUSTED_LOCAL.value, importance=0.9,
                    metadata={"spatial_edge": edge, "structured": True},
                ))
        return output

    def _epistemic(self, plan: QueryPlan) -> list[MemoryCandidate]:
        if not plan.scope.world_id:
            return []
        character_ids = [plan.scope.pov_variant_id] if plan.scope.pov_variant_id else [v["id"] for v in self._variant_targets(plan)]
        output = []
        for character_id in filter(None, character_ids):
            for row in self.store.query_epistemic(world_id=plan.scope.world_id, branch_id=plan.scope.branch_id,
                                                  character_variant_id=character_id, story_order=plan.scope.story_order):
                output.append(MemoryCandidate(
                    id=row["id"], lane=RetrievalLane.EPISTEMIC,
                    text=f"{character_id} {row['state_type']} {row['topic_type']}:{row['topic_id']} = {row.get('value')!r}",
                    source_type=row.get("source_type") or "epistemic_interval", source_id=row.get("source_id") or row["id"],
                    world_id=row["world_id"], branch_id=row.get("branch_id"), story_order=row.get("story_order_from"),
                    authority=Authority.ACCEPTED_EVENT.value, trust_level=TrustLevel.TRUSTED_LOCAL.value,
                    importance=0.95, metadata={"epistemic": row, "structured": True},
                ))
        return output

    def _threads(self, plan: QueryPlan) -> list[MemoryCandidate]:
        if not plan.scope.world_id:
            return []
        output = []
        targets = self._resource_targets(plan)
        if targets:
            rows = []
            for resource_type, resource_id in targets:
                rows.extend(self.store.list_threads(world_id=plan.scope.world_id, branch_id=plan.scope.branch_id,
                                                   status="open", resource_type=resource_type, resource_id=resource_id))
        else:
            rows = self.store.list_threads(world_id=plan.scope.world_id, branch_id=plan.scope.branch_id, status="open")
        seen = set()
        for row in rows:
            if row["id"] in seen: continue
            seen.add(row["id"])
            output.append(MemoryCandidate(
                id=row["id"], lane=RetrievalLane.THREADS,
                text=f"Open {row['thread_type']}: {row['title']} — {row.get('description') or ''}",
                source_type=row.get("source_type") or "story_thread", source_id=row.get("source_id") or row["id"],
                project_id=row.get("project_id"), world_id=row.get("world_id"), branch_id=row.get("branch_id"),
                authority=row.get("authority") or Authority.USER_ACCEPTED_WORLD_CANON.value,
                trust_level=TrustLevel.TRUSTED_LOCAL.value, importance=0.8,
                metadata={"thread": row, "structured": True},
            ))
        return output

    def _relationships(self, plan: QueryPlan) -> list[MemoryCandidate]:
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
        if not self.config.fts_enabled:
            return []
        domain = {
            RetrievalLane.FTS_MANUSCRIPT: "manuscript",
            RetrievalLane.FTS_CHAT: "chat",
            RetrievalLane.FTS_SUMMARY: "summary",
            RetrievalLane.FTS_IMPORT: "import",
        }[lane]
        return [self._candidate_from_chunk(row, lane, rank=i) for i, row in enumerate(self.store.search_fts(query, domains=[domain], limit=budget), 1)]

    def _dense(self, query: str, budget: int) -> list[MemoryCandidate]:
        generation = self.store.active_generation()
        if not generation or not self.embedding.available():
            return []
        vector = self.embedding.embed_query(query)
        return [self._candidate_from_chunk(row, RetrievalLane.DENSE, rank=i) for i, row in enumerate(
            self.store.search_vectors(vector, generation_id=generation["generation_id"], limit=budget), 1
        )]

    def _run_lane(self, lane: RetrievalLane, plan: QueryPlan) -> list[MemoryCandidate]:
        budget = plan.per_lane_candidate_budget.get(lane.value, 20)
        if lane == RetrievalLane.STRUCTURED_STATE: return self._structured_state(plan, lane)
        if lane == RetrievalLane.TEMPORAL_STATE: return self._temporal_state(plan)
        if lane == RetrievalLane.EVENTS: return self._events(plan)
        if lane == RetrievalLane.SPATIAL: return self._spatial(plan)
        if lane == RetrievalLane.RELATIONSHIPS: return self._relationships(plan)
        if lane == RetrievalLane.EPISTEMIC: return self._epistemic(plan)
        if lane == RetrievalLane.THREADS: return self._threads(plan)
        if lane in {RetrievalLane.FTS_MANUSCRIPT, RetrievalLane.FTS_CHAT, RetrievalLane.FTS_SUMMARY, RetrievalLane.FTS_IMPORT}:
            return self._fts(plan.normalized_query, lane, budget)
        if lane == RetrievalLane.DENSE: return self._dense(plan.normalized_query, budget)
        if lane == RetrievalLane.SUMMARIES: return self._fts(plan.normalized_query, RetrievalLane.FTS_SUMMARY, budget)
        if lane == RetrievalLane.GRAPH: return self._events(plan) + self._spatial(plan)
        if lane == RetrievalLane.CONTINUITY: return self._continuity(plan)
        return []

    def _rrf(self, lane_results: dict[RetrievalLane, list[MemoryCandidate]], plan: QueryPlan) -> list[MemoryCandidate]:
        by_key: dict[tuple[str, str], MemoryCandidate] = {}
        for lane, candidates in lane_results.items():
            for rank, candidate in enumerate(candidates, 1):
                key = (candidate.source_type, candidate.id)
                current = by_key.get(key)
                if current is None:
                    current = candidate
                    by_key[key] = current
                current.ranks[lane.value] = rank
                lane_weight = float((plan.context_plan.get("lane_weights") or {}).get(lane.value, 1.0))
                current.score += max(0.05, lane_weight) / (self.config.rrf_k + rank)
        authority_boost = {
            Authority.USER_ACCEPTED_OVERLAY.value: 0.18,
            Authority.USER_ACCEPTED_BRANCH_CANON.value: 0.16,
            Authority.USER_ACCEPTED_WORLD_CANON.value: 0.15,
            Authority.ACCEPTED_EVENT.value: 0.14,
            Authority.USER_EXPLICIT_NOTE.value: 0.10,
            Authority.ACCEPTED_GENERATED_OUTPUT.value: 0.08,
            Authority.PROJECT_MANUSCRIPT.value: 0.07,
        }
        for candidate in by_key.values():
            candidate.score += authority_boost.get(candidate.authority, 0.0)
            candidate.score += min(0.05, candidate.importance * 0.05)
            if candidate.metadata.get("structured"):
                candidate.score += 0.10
        return sorted(by_key.values(), key=lambda item: item.score, reverse=True)

    def _diversify(self, candidates: list[MemoryCandidate], limit: int) -> list[MemoryCandidate]:
        selected = []; per_source: Counter[tuple[str, str]] = Counter()
        for item in candidates:
            key = (item.source_type, item.source_id)
            if per_source[key] >= self.config.max_per_source:
                continue
            selected.append(item); per_source[key] += 1
            if len(selected) >= limit: break
        return selected

    @staticmethod
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

    @staticmethod
    def _pack(plan: QueryPlan, selected: list[MemoryCandidate], excluded: list[dict[str, Any]]) -> str:
        if not selected and not plan.context_plan:
            return ""
        sections: dict[str, list[MemoryCandidate]] = defaultdict(list)
        for item in selected:
            if item.metadata.get("ambiguity"): key = "UNRESOLVED CONTINUITY"
            elif item.lane == RetrievalLane.CONTINUITY: key = "ACTIVE CONTINUITY"
            elif item.lane in {RetrievalLane.STRUCTURED_STATE, RetrievalLane.TEMPORAL_STATE}: key = "ACCEPTED STATE"
            elif item.lane == RetrievalLane.EPISTEMIC: key = "POV KNOWLEDGE & BELIEFS"
            elif item.lane == RetrievalLane.RELATIONSHIPS: key = "RELATIONSHIPS"
            elif item.lane == RetrievalLane.EVENTS: key = "RELEVANT EVENTS"
            elif item.lane == RetrievalLane.SPATIAL: key = "SPATIAL CONTEXT"
            elif item.lane == RetrievalLane.THREADS: key = "OPEN THREADS"
            elif item.lane in {RetrievalLane.SUMMARIES, RetrievalLane.FTS_SUMMARY}: key = "DERIVED SUMMARIES"
            else: key = "SOURCE EVIDENCE"
            sections[key].append(item)
        intelligence = plan.context_plan or {}
        if intelligence:
            lines = [
                "@ARLINE-NARRATIVE-CONTEXT 1.2.3",
                f"route: {plan.route.value}",
                f"intent: {intelligence.get('intent') or 'unspecified'}",
                f"lens: {plan.scope.context_lens.value}",
            ]
            focus = [str(item.get("label") or item.get("id")) for item in intelligence.get("focus_resources") or []]
            if focus:
                lines.append("focus: " + ", ".join(focus[:16]))
            lines += [
                "", "[CONTEXT POLICY]",
                "- Canon remains authoritative; derived continuity never grants Canon.",
                "- Unresolved continuity conflicts must remain ambiguous rather than being guessed.",
                "- POV/scene scope must not leak blocked future or inaccessible knowledge.",
            ]
        else:
            lines = ["@ARLINE-MEMORY 1.0", f"route: {plan.route.value}", f"lens: {plan.scope.context_lens.value}"]
        for title in ("UNRESOLVED CONTINUITY", "ACTIVE CONTINUITY", "ACCEPTED STATE", "POV KNOWLEDGE & BELIEFS", "RELATIONSHIPS", "RELEVANT EVENTS", "SPATIAL CONTEXT", "OPEN THREADS", "DERIVED SUMMARIES", "SOURCE EVIDENCE"):
            items = sections.get(title) or []
            if not items: continue
            lines += ["", f"[{title}]"]
            for item in items:
                label = f"{item.source_type}:{item.source_id}"
                lines.append(f"- {evidence_wrapper(item.text, label)}")
        if excluded:
            counts = Counter(item["decision"]["rule"] for item in excluded)
            lines += ["", "[EXCLUDED CANDIDATES]", "- " + ", ".join(f"{rule}={count}" for rule, count in sorted(counts.items()))]
        return "\n".join(lines).rstrip() + "\n"

    def execute(self, query: str, scope: MemoryQueryContext, context_plan: dict[str, Any] | None = None) -> RetrievalResult:
        started = time.perf_counter(); plan = self.compiler.compile(query, scope, context_plan=context_plan)
        lanes = []
        for lane in plan.required_lanes + plan.optional_lanes:
            if lane not in lanes and lane not in plan.forbidden_lanes: lanes.append(lane)
        lane_results = {lane: self._run_lane(lane, plan) for lane in lanes}
        gated_lane_results: dict[RetrievalLane, list[MemoryCandidate]] = {}
        excluded: list[dict[str, Any]] = []
        for lane, candidates in lane_results.items():
            allowed, rejected = self.gate.filter(candidates, scope)
            gated_lane_results[lane] = allowed
            excluded.extend(rejected)
        raw = self._rrf(gated_lane_results, plan)
        selected = self._diversify(raw, plan.final_candidate_budget)
        if self.config.reranker.enabled and self.reranker.available() and len(selected) > 1:
            payloads = [item.to_dict() for item in selected]
            reranked = self.reranker.rerank(query, payloads, plan.final_candidate_budget)
            order = {item["id"]: i for i, item in enumerate(reranked)}
            selected.sort(key=lambda item: order.get(item.id, 10_000))
        diagnostics = []
        if self.config.dense_enabled and RetrievalLane.DENSE in lanes and not gated_lane_results.get(RetrievalLane.DENSE):
            diagnostics.append("Dense retrieval unavailable; other enabled lanes remained active.")
        missing_required = [lane for lane in plan.required_lanes if not gated_lane_results.get(lane)]
        if missing_required:
            diagnostics.append("Required evidence lane(s) empty after Scope Gate: " + ", ".join(lane.value for lane in missing_required))
            if plan.require_abstention:
                selected = []
        selected = self._fit_token_budget(selected, scope.token_budget, plan.context_plan)
        abstain = bool(plan.require_abstention and (missing_required or not selected))
        if missing_required:
            reason = "Required structured evidence was not available in the active scope."
        elif abstain:
            reason = "No allowed evidence was found in the active scope."
        else:
            reason = ""
        run_id = make_id("RETRIEVE")
        result = RetrievalResult(run_id, plan, selected, excluded, self._pack(plan, selected, excluded),
                                 {lane.value: len(items) for lane, items in lane_results.items()}, abstain, reason, diagnostics)
        if self.config.trace_enabled and plan.trace:
            self.store.record_retrieval_run(
                run_id=run_id, query_text=query, route=plan.route.value, scope=scope.to_dict(), plan=plan.to_dict(),
                selected=[item.to_dict() for item in selected], excluded=excluded, diagnostics=diagnostics,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        return result
