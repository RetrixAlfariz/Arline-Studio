from __future__ import annotations
from src.analytical_system.rule_registry import RuleSpec

RELATIONSHIP_RULES = [
    RuleSpec(
        "relationship_familiarity",
        "relationship",
        ("relationship.dating", "relationship.friend_of@historical"),
        ("relationship_familiarity",),
        .70,
    ),
    RuleSpec(
        "family_acceptance",
        "social",
        ("social.family_close|social.approves_of|social.arranged_relationship",),
        ("family_acceptance",),
        .65,
    ),
]
