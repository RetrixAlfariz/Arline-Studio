from __future__ import annotations
from src.analytical_system.rule_registry import RuleSpec

PHYSICAL_RULES = [
    RuleSpec(
        "reach_estimate",
        "spatial",
        ("physical.height_cm",),
        ("estimated_reach",),
        .55,
    ),
    RuleSpec(
        "body_profile",
        "physical",
        ("physical.morphology.presentation", "physical.chest.reference_cup"),
        ("feminine_body_profile",),
        .70,
    ),
    RuleSpec(
        "hair_motion",
        "hair",
        ("hair.current.length_cm|hair.current.length_relative",),
        ("hair_motion_affordance",),
        .70,
    ),
]
