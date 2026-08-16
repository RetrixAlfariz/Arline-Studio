from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.core import SemanticCore


VALID_PROJECTION_MODES = {"off", "conservative", "balanced", "vivid"}


@dataclass(slots=True)
class ProjectionRecord:
    """Approximate mental model derived from canonical facts.

    A projection is intentionally *not* canonical state. It may be surfaced to
    help the writer visualize the scene, but it must remain approximate and may
    never override facts, transitions, or explicit unknowns.
    """

    id: str
    name: str
    subject: str | None
    value: Any
    confidence: float
    priority: int
    basis_fact_ids: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    target_unknown: str | None = None
    applies_after: str | None = None
    surface_policy: str = "visualize_naturally"
    language_hint: str | None = None
    exact_claim_forbidden: bool = True
    canonical: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProjectionEngine:
    """Build bounded visual projections from canonical state.

    The engine deliberately focuses on mental-model assistance, not filling
    missing database fields. Every record declares the assumptions that make
    the projection possible and keeps exact unknowns unknown.
    """

    VERSION = "0.1"

    # Coarse body landmarks ordered from higher to lower on a standing body.
    # These are qualitative visualization anchors, not anthropometric truth.
    REGION_ORDER = [
        "shoulder",
        "upper_back",
        "mid_back",
        "lower_back",
        "waist",
        "hip",
        "upper_thigh",
        "mid_thigh",
        "knee",
        "calf",
        "ankle",
        "floor",
    ]

    def __init__(self, *, mode: str = "balanced", min_confidence: float = 0.5, max_items: int = 12):
        mode = str(mode).lower()
        if mode not in VALID_PROJECTION_MODES:
            raise ValueError(f"projection mode must be one of {sorted(VALID_PROJECTION_MODES)}")
        self.mode = mode
        self.min_confidence = float(min_confidence)
        self.max_items = int(max_items)

    @classmethod
    def default(cls) -> "ProjectionEngine":
        return cls()

    def project(self, core: SemanticCore, pipeline_result, narrative=None) -> list[ProjectionRecord]:
        if self.mode == "off":
            return []

        state = pipeline_result.extracted_state
        entities = {e.get("id"): e for e in state.get("entities", []) or []}
        self_id = self._self_id(state, entities)

        projections: list[ProjectionRecord] = []
        counter = 1

        def add(record: ProjectionRecord) -> None:
            nonlocal counter
            if record.confidence < self.min_confidence:
                return
            record.id = f"proj_{counter:04d}"
            counter += 1
            projections.append(record)

        hair = self._hair_projection(core, self_id)
        if hair is not None:
            add(hair)

        for eid, entity in entities.items():
            if entity.get("type") != "garment":
                continue
            garment = self._garment_projection(core, eid, entity)
            if garment is not None:
                add(garment)

        # Stable deterministic ordering matters for future fine-tuning.
        projections.sort(key=lambda p: (p.priority, p.subject or "", p.name, p.id))
        return projections[: self.max_items]

    def _hair_projection(self, core: SemanticCore, self_id: str | None) -> ProjectionRecord | None:
        if not self_id:
            return None
        height = self._fact(core, self_id, "physical.height_cm")
        length = self._fact(core, self_id, "hair.current.length_cm")
        if height is None or length is None:
            return None
        if not isinstance(height.value, (int, float)) or not isinstance(length.value, (int, float)):
            return None
        if height.value <= 0 or length.value <= 0:
            return None

        ratio = float(length.value) / float(height.value)
        region_from, region_to = self._hair_region_range(ratio)
        visual_class = self._hair_visual_class(ratio)
        confidence = min(float(height.confidence), float(length.confidence), self._projection_confidence(ratio))
        applies_after = self._transition_label(core, self_id, "hair_transformation")

        if self.mode == "conservative":
            value = {
                "visual_class": visual_class,
                "relative_description": self._conservative_hair_description(ratio),
            }
            hint = "Describe the hair as visually very long using broad relative language; avoid naming an exact endpoint."
            priority = 1
        else:
            value = {
                "visual_class": visual_class,
                "probable_region": {"from": region_from, "to": region_to},
                "relative_description": self._balanced_hair_description(region_from, region_to),
            }
            if self.mode == "vivid":
                value["visual_consequences"] = [
                    "large back coverage when hanging freely",
                    "noticeable motion lag when turning or stopping",
                    "may enter the foreground of body movement when loose",
                ]
                hint = (
                    "Use the projected range and movement consequences for vivid imagery, "
                    "but keep the endpoint approximate and never convert it into an exact measurement."
                )
            else:
                hint = (
                    "Use natural relative language such as 'well below the waist' or an approximate "
                    "hip/upper-thigh region when it helps visualization."
                )
            priority = 1

        return ProjectionRecord(
            id="",
            name="hair_visual_extent",
            subject=self_id,
            value=value,
            confidence=round(confidence, 4),
            priority=priority,
            basis_fact_ids=[height.id, length.id],
            assumptions=[
                "hair length is interpreted as strand length from a scalp/crown-like origin",
                "hair hangs approximately straight under gravity",
                "character is standing in an ordinary upright posture",
                "no extreme curl/shrinkage or unusual styling changes the hanging length",
            ],
            target_unknown="hair.exact_body_relative_endpoint",
            applies_after=applies_after,
            language_hint=hint,
            metadata={
                "projection_mode": self.mode,
                "length_to_height_ratio": round(ratio, 4),
                **(
                    {"allowed_region": {"from": region_from, "to": region_to}}
                    if self.mode in {"balanced", "vivid"}
                    else {}
                ),
                "domain": "hair",
            },
        )

    def _garment_projection(self, core: SemanticCore, entity_id: str, entity: dict[str, Any]) -> ProjectionRecord | None:
        attrs = entity.get("attributes", {}) or {}
        lexical = self._fact_value((attrs.get("ontology") or {}).get("lexical_type")) or entity.get("label")
        if lexical not in {"dress", "gamis"}:
            return None
        length = self._fact(core, entity_id, "length_cm") or self._fact(core, entity_id, "length")
        if length is None:
            return None
        raw_length = self._fact_value(length.value)
        if not isinstance(raw_length, (int, float)) or raw_length <= 0:
            return None

        basis = self._fact(core, entity_id, "measurement_basis")
        material = self._fact(core, entity_id, "material")
        length_value = float(raw_length)
        if length_value >= 125:
            visual_class = "very_long_or_maxi_scale"
            coverage = "large vertical fabric presence"
        elif length_value >= 100:
            visual_class = "long"
            coverage = "substantial vertical fabric presence"
        elif length_value >= 70:
            visual_class = "medium_length"
            coverage = "moderate vertical fabric presence"
        else:
            visual_class = "short_to_moderate"
            coverage = "limited vertical fabric presence"

        basis_value = self._fact_value(basis.value) if basis else None
        basis_unknown = basis_value in {None, "unspecified", "unknown"}
        assumptions = [
            "the stated length is a longitudinal garment dimension",
            "the garment is hanging normally rather than being folded or heavily gathered",
        ]
        value: dict[str, Any] = {
            "visual_class": visual_class,
            "vertical_coverage": coverage,
            "exact_body_endpoint": "not projected" if basis_unknown else "may be estimated only from the declared measurement basis",
        }
        if material and str(material.value).lower() == "rayon":
            value["visual_texture"] = "soft, flexible drape is plausible"

        if self.mode == "conservative":
            hint = "Use only the garment's broad visual length class; do not infer a body landmark for the hem."
        elif self.mode == "vivid":
            value["visual_consequences"] = [
                "the garment creates a long uninterrupted vertical silhouette",
                "fabric movement is visually noticeable during turns or steps",
            ]
            hint = (
                "Use the long/maxi visual footprint and material drape for imagery. "
                "Do not invent a precise hem landmark while the measurement basis is unknown."
            )
        else:
            hint = (
                "Describe the garment as visually very long/maxi-scale and use its drape, "
                "without claiming an exact ankle/floor endpoint unless the basis becomes known."
            )

        basis_ids = [length.id]
        if basis:
            basis_ids.append(basis.id)
        if material:
            basis_ids.append(material.id)
        applies_after = self._transition_label(core, None, "dress_change", target=entity_id)
        confidence = min(float(length.confidence), 0.84 if basis_unknown else 0.9)
        return ProjectionRecord(
            id="",
            name="garment_visual_footprint",
            subject=entity_id,
            value=value,
            confidence=round(confidence, 4),
            priority=2,
            basis_fact_ids=basis_ids,
            assumptions=assumptions,
            target_unknown=(f"{entity_id}.exact_body_relative_hem_endpoint_of_known_garment_length" if basis_unknown else None),
            applies_after=applies_after,
            language_hint=hint,
            metadata={
                "projection_mode": self.mode,
                "domain": "garment",
                "measurement_basis_known": not basis_unknown,
            },
        )

    def _hair_region_range(self, ratio: float) -> tuple[str, str]:
        # The ratio is only used to choose a broad visualization bucket. The
        # range intentionally spans multiple landmarks because human body
        # proportions and hair measurement origin vary.
        if ratio < 0.22:
            center = 0
        elif ratio < 0.32:
            center = 1
        elif ratio < 0.42:
            center = 2
        elif ratio < 0.50:
            center = 3
        elif ratio < 0.57:
            center = 4
        elif ratio < 0.65:
            center = 5
        elif ratio < 0.73:
            center = 6
        elif ratio < 0.81:
            center = 7
        elif ratio < 0.89:
            center = 8
        elif ratio < 0.97:
            center = 9
        else:
            center = 10

        if self.mode == "vivid":
            lo = max(0, center - 1)
            hi = min(len(self.REGION_ORDER) - 1, center + 1)
        else:
            lo = max(0, center - 2)
            hi = min(len(self.REGION_ORDER) - 1, center + 1)
        return self.REGION_ORDER[lo], self.REGION_ORDER[hi]

    @staticmethod
    def _hair_visual_class(ratio: float) -> str:
        if ratio >= 0.55:
            return "very_long"
        if ratio >= 0.38:
            return "long"
        if ratio >= 0.22:
            return "medium_to_long"
        return "short_to_medium"

    @staticmethod
    def _projection_confidence(ratio: float) -> float:
        # Classification confidence is higher than landmark confidence. We cap
        # it because anthropometric anchors are assumptions, not measurements.
        if 0.25 <= ratio <= 0.9:
            return 0.68
        return 0.60

    @staticmethod
    def _conservative_hair_description(ratio: float) -> str:
        if ratio >= 0.55:
            return "visually very long and extending far down the back"
        if ratio >= 0.38:
            return "long enough to dominate the back silhouette"
        return "noticeably long relative to the body"

    @staticmethod
    def _balanced_hair_description(region_from: str, region_to: str) -> str:
        human = lambda s: s.replace("_", " ")
        return f"likely falls within a broad {human(region_from)} to {human(region_to)} visual region"

    @staticmethod
    def _fact(core: SemanticCore, entity_id: str | None, path: str):
        candidates = [
            f for f in core.facts
            if f.entity_id == entity_id and f.path == path
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda f: (-float(f.confidence), f.id))[0]

    @staticmethod
    def _fact_value(value: Any) -> Any:
        if isinstance(value, dict) and "value" in value:
            return value.get("value")
        return value

    @staticmethod
    def _self_id(state: dict[str, Any], entities: dict[str, dict[str, Any]]) -> str | None:
        for alias in state.get("entity_aliases", []) or []:
            if alias.get("alias") == "char:self":
                return alias.get("canonical")
        if "char:self" in entities:
            return "char:self"
        for eid, entity in entities.items():
            if entity.get("type") == "character" and entity.get("label") not in {"fano", "self_mother", "fano_mother"}:
                return eid
        return None

    @staticmethod
    def _transition_label(core: SemanticCore, actor: str | None, event_type: str, target: str | None = None) -> str | None:
        for transition in core.transitions:
            if transition.event_type != event_type:
                continue
            if actor is not None and transition.actor != actor:
                continue
            if target is not None and transition.target != target:
                continue
            return event_type.replace("_", " ")
        return None
