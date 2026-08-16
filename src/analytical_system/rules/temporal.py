from __future__ import annotations
from src.analytical_system.rule_registry import RuleSpec

TEMPORAL_RULES = [
    RuleSpec(
        "event_transition",
        "temporal",
        ("runtime_event",),
        ("state_delta",),
        .95,
    ),
    RuleSpec(
        "habitual_not_runtime",
        "temporal",
        ("aspect.habitual",),
        ("eventhood_suppressed",),
        .98,
    ),
]
