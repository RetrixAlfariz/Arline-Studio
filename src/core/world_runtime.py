from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .schema import SemanticCore


@dataclass(slots=True)
class WorldRuntime:
    """
    Runtime projection of canonical semantics.

    `scene_start_state` is the state the writer should begin from when a prompt
    describes a sequence that still needs to be dramatized. `projected_state`
    is the state after every extracted realized transition is applied.
    """

    version: str
    scene_start_state: dict[str, Any] = field(default_factory=dict)
    projected_state: dict[str, Any] = field(default_factory=dict)
    state_sequence: list[dict[str, Any]] = field(default_factory=list)
    temporal_ledger: list[dict[str, Any]] = field(default_factory=list)
    invariants: list[dict[str, Any]] = field(default_factory=list)
    negative_state: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WorldRuntimeBuilder:
    VERSION = "0.1"

    @classmethod
    def default(cls) -> "WorldRuntimeBuilder":
        return cls()

    def build(self, semantic_core: SemanticCore, pipeline_result) -> WorldRuntime:
        snapshots = list(pipeline_result.events.get("state_snapshots", []) or [])
        runtime_events = list(pipeline_result.events.get("events", []) or [])

        if snapshots:
            scene_start = snapshots[0].get("state", {}) or {}
            projected = snapshots[-1].get("state", {}) or {}
        else:
            scene_start = {}
            projected = {}

        # If there is no event sequence, the scene-start and current/projected
        # state are the same. If events exist, the writer starts at S0 and the
        # projected state remains available for validation and transition logic.
        sequence = [
            {
                "state_id": snap.get("id"),
                "after_event": snap.get("after_event"),
                "state": snap.get("state", {}),
            }
            for snap in snapshots
        ]

        invariants = []
        for fact in semantic_core.facts:
            if fact.authority not in {"user_explicit", "latest_user_correction"}:
                continue
            if fact.temporal_scope == "historical_baseline":
                continue
            if fact.category not in {
                "identity", "physical", "garment", "location", "transformation", "appearance"
            }:
                continue
            invariants.append({
                "fact_id": fact.id,
                "entity_id": fact.entity_id,
                "path": fact.path,
                "value": fact.value,
                "authority": fact.authority,
                "confidence": fact.confidence,
            })

        return WorldRuntime(
            version=self.VERSION,
            scene_start_state=scene_start,
            projected_state=projected,
            state_sequence=sequence,
            temporal_ledger=[x.to_dict() for x in semantic_core.temporal_ledger],
            invariants=invariants,
            negative_state=[x.to_dict() for x in semantic_core.negative_facts],
            contradictions=list(semantic_core.contradictions),
            diagnostics=([] if snapshots or not runtime_events else [
                {
                    "type": "runtime_events_without_state_snapshots",
                    "event_count": len(runtime_events),
                }
            ]),
        )
