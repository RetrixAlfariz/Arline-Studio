from __future__ import annotations

from typing import Any


class TemporalMemory:
    def __init__(self, store):
        self.store = store

    def current_state(self, *, world_id: str, branch_id: str | None, owner_type: str,
                      owner_id: str, state_key: str | None = None) -> list[dict[str, Any]]:
        return self.store.query_current_state(world_id, branch_id, owner_type, owner_id, state_key)

    def state_at(self, *, world_id: str, branch_id: str | None, owner_type: str,
                 owner_id: str, story_order: float | None = None) -> list[dict[str, Any]]:
        return self.store.state_at(
            world_id=world_id, branch_id=branch_id, owner_type=owner_type,
            owner_id=owner_id, story_order=story_order,
        )

    def epistemic_state(self, *, world_id: str, branch_id: str | None,
                        character_variant_id: str, topic_type: str | None = None,
                        topic_id: str | None = None, story_order: float | None = None) -> list[dict[str, Any]]:
        return self.store.query_epistemic(
            world_id=world_id, branch_id=branch_id,
            character_variant_id=character_variant_id,
            topic_type=topic_type, topic_id=topic_id,
            story_order=story_order,
        )
