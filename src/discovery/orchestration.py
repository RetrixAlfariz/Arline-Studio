from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .continuity import ContinuityResolver
from .coreference import CrossTurnCoreferenceResolver
from .entity_resolver import NarrativeEntityResolver, ResolvedEntityFrame
from .events import NarrativeEventProjector


@dataclass(slots=True)
class NarrativeSemanticFrame:
    entities: dict[str, dict[str, Any]]
    key_map: dict[str, str]
    event_ids: dict[str, str]


class NarrativeSemanticOrchestrator:
    """Explicit v1.2.2 semantic spine.

    Order is a contract rather than an installer accident:
      analytical extraction -> stable entity resolution -> coreference ->
      EVENT projection -> proposition/state capture -> continuity resolution.
    """

    def __init__(self, service):
        self.service = service
        self.coreference = CrossTurnCoreferenceResolver(service)
        self.entity_resolver = NarrativeEntityResolver(service, self.coreference)
        self.events = NarrativeEventProjector(service)
        self.continuity = ContinuityResolver(service)

    def prepare(
        self,
        *,
        result,
        text: str,
        source: dict[str, Any],
        entities: dict[str, dict[str, Any]],
    ) -> NarrativeSemanticFrame:
        entity_frame: ResolvedEntityFrame = self.entity_resolver.resolve_entities(
            entities, text=text, source=source
        )
        event_ids = self.events.capture_events(
            getattr(result, "events", None), source=source, key_map=entity_frame.key_map
        )
        return NarrativeSemanticFrame(
            entities=entity_frame.entities,
            key_map=entity_frame.key_map,
            event_ids=event_ids,
        )

    def finalize_turn(self, turn_id: str, *, source_kind: str) -> dict[str, Any]:
        return self.continuity.resolve_turn(turn_id, source_kind=source_kind)
