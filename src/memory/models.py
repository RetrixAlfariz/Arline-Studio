from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class QueryRoute(StrEnum):
    CURRENT_STATE = "CURRENT_STATE"
    TEMPORAL_STATE = "TEMPORAL_STATE"
    EVENT_LOOKUP = "EVENT_LOOKUP"
    EPISTEMIC_STATE = "EPISTEMIC_STATE"
    SPATIAL_LOOKUP = "SPATIAL_LOOKUP"
    THREAD_LOOKUP = "THREAD_LOOKUP"
    WHY_CAUSAL = "WHY_CAUSAL"
    TEXT_RECALL = "TEXT_RECALL"
    GLOBAL_SUMMARY = "GLOBAL_SUMMARY"
    CONTINUITY_CHECK = "CONTINUITY_CHECK"
    BRANCH_COMPARE = "BRANCH_COMPARE"
    STORY_CONTINUE = "STORY_CONTINUE"


class ContextLens(StrEnum):
    AUTHOR = "author"
    SCENE = "scene"
    POV = "pov"


class RetrievalLane(StrEnum):
    STRUCTURED_STATE = "structured_state"
    TEMPORAL_STATE = "temporal_state"
    EVENTS = "events"
    EPISTEMIC = "epistemic"
    SPATIAL = "spatial"
    RELATIONSHIPS = "relationships"
    THREADS = "threads"
    FTS_MANUSCRIPT = "fts_manuscript"
    FTS_CHAT = "fts_chat"
    FTS_SUMMARY = "fts_summary"
    FTS_IMPORT = "fts_import"
    DENSE = "dense"
    GRAPH = "graph"
    SUMMARIES = "summaries"
    CONTINUITY = "continuity"


class Authority(StrEnum):
    USER_ACCEPTED_OVERLAY = "user_accepted_overlay"
    USER_ACCEPTED_BRANCH_CANON = "user_accepted_branch_canon"
    USER_ACCEPTED_WORLD_CANON = "user_accepted_world_canon"
    ACCEPTED_EVENT = "accepted_event"
    USER_EXPLICIT_NOTE = "user_explicit_note"
    ACCEPTED_GENERATED_OUTPUT = "accepted_generated_output"
    PROJECT_MANUSCRIPT = "project_manuscript"
    CHAT_DECISION = "chat_decision"
    CHAT_EXPLORATION = "chat_exploration"
    DERIVED_SUMMARY = "derived_summary"
    IMPORTED_REFERENCE = "imported_reference"
    SCRATCH = "scratch"


class TrustLevel(StrEnum):
    TRUSTED_LOCAL = "trusted_local"
    USER_PROVIDED = "user_provided"
    GENERATED = "generated"
    IMPORTED_UNREVIEWED = "imported_unreviewed"
    QUARANTINED = "quarantined"


class SemanticClass(StrEnum):
    EVIDENCE = "evidence"
    EXPLORATORY = "exploratory"
    HYPOTHESIS = "hypothesis"
    DECISION = "decision"
    ACCEPTED_CONCEPT = "accepted_concept"
    REJECTED_IDEA = "rejected_idea"
    SUMMARY = "summary"


class SemanticStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    SUPERSEDED = "superseded"
    DEPRECATED = "deprecated"
    WRONG_INFERENCE = "wrong_inference"
    WRONG_SCOPE = "wrong_scope"
    DUPLICATE = "duplicate"
    QUARANTINED = "quarantined"
    DELETED = "deleted"


@dataclass(slots=True)
class MemoryQueryContext:
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    session_id: str | None = None
    current_turn_id: str | None = None
    world_time: Any = None
    story_order: float | None = None
    pov_variant_id: str | None = None
    context_lens: ContextLens | str = ContextLens.SCENE
    retrieval_mode: str = "standard"
    explicit_references: list[dict[str, Any]] = field(default_factory=list)
    explicit_cross_scope_sources: list[dict[str, str]] = field(default_factory=list)
    allow_scratch: bool = False
    allow_future_author_knowledge: bool = False
    token_budget: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.context_lens, ContextLens):
            self.context_lens = ContextLens(str(self.context_lens or "scene"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "world_id": self.world_id,
            "branch_id": self.branch_id,
            "session_id": self.session_id,
            "current_turn_id": self.current_turn_id,
            "world_time": self.world_time,
            "story_order": self.story_order,
            "pov_variant_id": self.pov_variant_id,
            "context_lens": self.context_lens.value,
            "retrieval_mode": self.retrieval_mode,
            "explicit_references": self.explicit_references,
            "explicit_cross_scope_sources": self.explicit_cross_scope_sources,
            "allow_scratch": self.allow_scratch,
            "allow_future_author_knowledge": self.allow_future_author_knowledge,
            "token_budget": self.token_budget,
        }


@dataclass(slots=True)
class QueryPlan:
    route: QueryRoute
    scope: MemoryQueryContext
    resolved_entities: list[dict[str, Any]] = field(default_factory=list)
    predicates: list[str] = field(default_factory=list)
    world_time_range: dict[str, Any] | None = None
    story_order_range: tuple[float | None, float | None] | None = None
    required_lanes: list[RetrievalLane] = field(default_factory=list)
    optional_lanes: list[RetrievalLane] = field(default_factory=list)
    forbidden_lanes: list[RetrievalLane] = field(default_factory=list)
    per_lane_candidate_budget: dict[str, int] = field(default_factory=dict)
    final_candidate_budget: int = 12
    require_provenance: bool = True
    require_abstention: bool = True
    trace: bool = True
    normalized_query: str = ""
    context_plan: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route.value,
            "scope": self.scope.to_dict(),
            "resolved_entities": self.resolved_entities,
            "predicates": self.predicates,
            "world_time_range": self.world_time_range,
            "story_order_range": list(self.story_order_range) if self.story_order_range else None,
            "required_lanes": [item.value for item in self.required_lanes],
            "optional_lanes": [item.value for item in self.optional_lanes],
            "forbidden_lanes": [item.value for item in self.forbidden_lanes],
            "per_lane_candidate_budget": self.per_lane_candidate_budget,
            "final_candidate_budget": self.final_candidate_budget,
            "require_provenance": self.require_provenance,
            "require_abstention": self.require_abstention,
            "trace": self.trace,
            "normalized_query": self.normalized_query,
            "context_plan": self.context_plan,
        }


@dataclass(slots=True)
class MemoryCandidate:
    id: str
    lane: RetrievalLane
    text: str
    source_type: str
    source_id: str
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    session_id: str | None = None
    world_time: Any = None
    story_order: float | None = None
    semantic_class: str = SemanticClass.EVIDENCE.value
    semantic_status: str = SemanticStatus.ACTIVE.value
    authority: str = Authority.PROJECT_MANUSCRIPT.value
    trust_level: str = TrustLevel.TRUSTED_LOCAL.value
    importance: float = 0.5
    extraction_confidence: float = 1.0
    identity_confidence: float = 1.0
    relevance_confidence: float = 0.0
    score: float = 0.0
    ranks: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "lane": self.lane.value,
            "text": self.text,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "project_id": self.project_id,
            "world_id": self.world_id,
            "branch_id": self.branch_id,
            "session_id": self.session_id,
            "world_time": self.world_time,
            "story_order": self.story_order,
            "semantic_class": self.semantic_class,
            "semantic_status": self.semantic_status,
            "authority": self.authority,
            "trust_level": self.trust_level,
            "importance": self.importance,
            "extraction_confidence": self.extraction_confidence,
            "identity_confidence": self.identity_confidence,
            "relevance_confidence": self.relevance_confidence,
            "score": self.score,
            "ranks": self.ranks,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class ScopeDecision:
    allowed: bool
    reason: str
    rule: str

    def to_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reason": self.reason, "rule": self.rule}


@dataclass(slots=True)
class RetrievalResult:
    run_id: str
    plan: QueryPlan
    selected: list[MemoryCandidate]
    excluded: list[dict[str, Any]]
    packed_text: str
    lane_counts: dict[str, int]
    abstain: bool = False
    abstention_reason: str = ""
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "plan": self.plan.to_dict(),
            "selected": [item.to_dict() for item in self.selected],
            "excluded": self.excluded,
            "packed_text": self.packed_text,
            "lane_counts": self.lane_counts,
            "abstain": self.abstain,
            "abstention_reason": self.abstention_reason,
            "diagnostics": self.diagnostics,
        }
