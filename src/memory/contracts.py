from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceSpan(StrictContract):
    source_id: str = Field(min_length=1)
    start_id: str | None = None
    end_id: str | None = None
    quote: str = ""


class EventProposal(StrictContract):
    event_type: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    participants: list[str] = Field(default_factory=list)
    state_patch: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceSpan] = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class StateChangeProposal(StrictContract):
    owner_type: str = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    proposed_value: Any
    old_value: Any = None
    evidence: list[EvidenceSpan] = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class EpistemicChangeProposal(StrictContract):
    character_variant_id: str = Field(min_length=1)
    topic_type: str = Field(min_length=1)
    topic_id: str = Field(min_length=1)
    state_type: Literal[
        "knowledge_acquired",
        "knowledge_revealed",
        "belief_formed",
        "belief_revised",
        "misinformation_received",
        "suspicion_formed",
        "secret_shared",
    ]
    value: Any
    evidence: list[EvidenceSpan] = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class RelationshipChangeProposal(StrictContract):
    subject_variant_id: str = Field(min_length=1)
    object_variant_id: str = Field(min_length=1)
    relation_type: str = Field(min_length=1)
    status: str = "current"
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceSpan] = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class StoryThreadProposal(StrictContract):
    thread_type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    status: Literal["open", "developing", "resolved", "abandoned", "invalidated"] = "open"
    related_resource_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceSpan] = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class UncertaintyRecord(StrictContract):
    description: str = Field(min_length=1)
    evidence: list[EvidenceSpan] = Field(default_factory=list)


class UnresolvedReference(StrictContract):
    text: str = Field(min_length=1)
    source_id: str | None = None
    candidates: list[str] = Field(default_factory=list)


class MemoryProposalsV1(StrictContract):
    events: list[EventProposal] = Field(default_factory=list)
    state_changes: list[StateChangeProposal] = Field(default_factory=list)
    knowledge_changes: list[EpistemicChangeProposal] = Field(default_factory=list)
    belief_changes: list[EpistemicChangeProposal] = Field(default_factory=list)
    relationship_changes: list[RelationshipChangeProposal] = Field(default_factory=list)
    story_threads: list[StoryThreadProposal] = Field(default_factory=list)
    uncertainties: list[UncertaintyRecord] = Field(default_factory=list)
    unresolved_references: list[UnresolvedReference] = Field(default_factory=list)


class MemorySummaryV1(StrictContract):
    summary_type: str = Field(min_length=1)
    subject_type: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    explicit_facts: list[str] = Field(default_factory=list)
    inferences: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    source_chunk_ids: list[str] = Field(min_length=1)
    story_order_from: float | None = None
    story_order_to: float | None = None


SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "memory_proposals_v1": MemoryProposalsV1,
    "memory_summary_v1": MemorySummaryV1,
}


def validate_structured_output(schema_id: str, payload: Any) -> dict[str, Any]:
    try:
        model = SCHEMA_MODELS[schema_id]
    except KeyError as exc:
        raise KeyError(f"Unknown memory output schema: {schema_id}") from exc
    return model.model_validate(payload).model_dump(mode="json")


def schema_document(schema_id: str) -> dict[str, Any]:
    try:
        model = SCHEMA_MODELS[schema_id]
    except KeyError as exc:
        raise KeyError(f"Unknown memory output schema: {schema_id}") from exc
    return model.model_json_schema()
