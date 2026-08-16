from __future__ import annotations

from typing import Iterable

from .schema import FactRecord


AUTHORITY_RANK = {
    "writer_guess": 0,
    "assumed": 10,
    "estimate": 20,
    "analytical_inference": 30,
    "retrieved_canonical_lore": 40,
    "verified_story_state": 50,
    "current_runtime_state": 55,
    "user_explicit": 60,
    "latest_user_correction": 70,
}


class AuthorityResolver:
    """Resolve competing facts without silently flattening their provenance."""

    @staticmethod
    def score(fact: FactRecord) -> tuple[int, float, int]:
        temporal_bonus = 2 if fact.temporal_scope in {"current", "current_after_transition"} else 0
        return (
            AUTHORITY_RANK.get(fact.authority, 0) + temporal_bonus,
            fact.confidence,
            len(fact.provenance),
        )

    def resolve(self, facts: Iterable[FactRecord]) -> FactRecord | None:
        facts = list(facts)
        if not facts:
            return None
        return max(facts, key=self.score)

    def resolve_by_slot(self, facts: Iterable[FactRecord]) -> dict[tuple[str | None, str, str], FactRecord]:
        buckets: dict[tuple[str | None, str, str], list[FactRecord]] = {}
        for fact in facts:
            key = (fact.entity_id, fact.path, fact.temporal_scope)
            buckets.setdefault(key, []).append(fact)
        return {key: self.resolve(items) for key, items in buckets.items() if items}
