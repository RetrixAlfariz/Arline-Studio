from __future__ import annotations
from src.analytical_system.rule_registry import RuleSpec

GARMENT_RULES = [
    RuleSpec(
        "garment_drape",
        "garment",
        ("garment.material",),
        ("garment_drape",),
        .60,
    ),
    RuleSpec(
        "garment_body_fit",
        "garment",
        ("garment.fits", "physical.morphology.presentation"),
        ("garment_body_fit_compatibility",),
        .68,
    ),
]
