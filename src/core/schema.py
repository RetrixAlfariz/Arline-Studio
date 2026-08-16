from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Provenance:
    source_kind: str
    source_segment: str | None = None
    source_text: str | None = None
    rule: str | None = None
    authority: str = "user_explicit"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FactRecord:
    id: str
    entity_id: str | None
    path: str
    value: Any
    category: str
    authority: str
    epistemic: str
    confidence: float
    temporal_scope: str = "current_or_unspecified"
    persistence: str = "persistent"
    negated: bool = False
    priority: int = 2
    provenance: list[Provenance] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


@dataclass(slots=True)
class NegativeFact:
    subject: str
    predicate: str
    object: Any = None
    temporal_scope: str = "current"
    reason: str = "explicit_negative_or_invalidation"
    provenance: list[Provenance] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TransitionContract:
    event_id: str
    event_type: str
    actor: str | None = None
    target: str | None = None
    cause: str | None = None
    order: int | None = None
    preconditions: list[str] = field(default_factory=list)
    changes: list[dict[str, Any]] = field(default_factory=list)
    invalidates: list[dict[str, Any]] = field(default_factory=list)
    preserves: list[str] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)
    provenance: list[Provenance] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TemporalEntry:
    index: int
    label: str
    event_id: str | None
    event_type: str | None
    state_before: str | None
    state_after: str | None
    status: str = "realized"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RelevanceDecision:
    key: str
    priority: int
    include: bool
    reason: str
    score: float = 0.0
    domain: str = "general"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SemanticCore:
    version: str
    facts: list[FactRecord] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    negative_facts: list[NegativeFact] = field(default_factory=list)
    transitions: list[TransitionContract] = field(default_factory=list)
    temporal_ledger: list[TemporalEntry] = field(default_factory=list)
    knowledge: list[dict[str, Any]] = field(default_factory=list)
    beliefs: list[dict[str, Any]] = field(default_factory=list)
    norms: list[dict[str, Any]] = field(default_factory=list)
    experience: list[dict[str, Any]] = field(default_factory=list)
    relationship_timeline: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    trace_index: dict[str, dict[str, Any]] = field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def fact_map(self) -> dict[str, FactRecord]:
        return {f.id: f for f in self.facts}

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "facts": [x.to_dict() for x in self.facts],
            "relations": self.relations,
            "negative_facts": [x.to_dict() for x in self.negative_facts],
            "transitions": [x.to_dict() for x in self.transitions],
            "temporal_ledger": [x.to_dict() for x in self.temporal_ledger],
            "knowledge": self.knowledge,
            "beliefs": self.beliefs,
            "norms": self.norms,
            "experience": self.experience,
            "relationship_timeline": self.relationship_timeline,
            "contradictions": self.contradictions,
            "unresolved": self.unresolved,
            "trace_index": self.trace_index,
            "diagnostics": self.diagnostics,
        }
