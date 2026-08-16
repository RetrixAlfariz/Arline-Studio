from .physical import PHYSICAL_RULES
from .garment import GARMENT_RULES
from .relationship import RELATIONSHIP_RULES
from .temporal import TEMPORAL_RULES

DEFAULT_RULES = [
    *PHYSICAL_RULES,
    *GARMENT_RULES,
    *RELATIONSHIP_RULES,
    *TEMPORAL_RULES,
]

__all__ = [
    "PHYSICAL_RULES",
    "GARMENT_RULES",
    "RELATIONSHIP_RULES",
    "TEMPORAL_RULES",
    "DEFAULT_RULES",
]
