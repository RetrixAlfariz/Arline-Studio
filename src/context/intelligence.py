from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import re
from typing import Any


CONTEXT_INTELLIGENCE_VERSION = "1.2.3a1"


class NarrativeIntent(StrEnum):
    CONTINUE = "continue"
    DIALOGUE = "dialogue"
    ACTION = "action"
    DESCRIPTION = "description"
    TRANSITION = "transition"
    CAUSAL = "causal"
    RECALL = "recall"
    SUMMARY = "summary"
    CONTINUITY_REVIEW = "continuity_review"
    BRANCH_COMPARE = "branch_compare"


@dataclass(slots=True)
class NarrativeContextPlan:
    version: str
    route: str
    intent: str
    lens: str
    focus_resources: list[dict[str, Any]] = field(default_factory=list)
    scene_anchors: dict[str, Any] = field(default_factory=dict)
    dimensions: dict[str, float] = field(default_factory=dict)
    required_lanes: list[str] = field(default_factory=list)
    optional_lanes: list[str] = field(default_factory=list)
    preserve_lanes: list[str] = field(default_factory=list)
    lane_weights: dict[str, float] = field(default_factory=dict)
    lane_token_budget: dict[str, int] = field(default_factory=dict)
    policies: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NarrativeContextPlanner:
    """Deterministic narrative-context planner.

    This layer does not create truth. It tells existing Workspace/Memory/
    Continuity systems which dimensions matter for the current request and how
    much budget they may consume. ScopeGate and Canon authority remain below it.
    """

    VERSION = CONTEXT_INTELLIGENCE_VERSION

    DIALOGUE = re.compile(r"\b(dialogue|conversation|talk|talking|speak|speaks|said|says|whisper|berkata|bicara|ngobrol|percakapan|dialog)\b", re.I)
    ACTION = re.compile(r"\b(fight|attack|chase|run|escape|battle|action|combat|menyerang|bertarung|mengejar|kabur|aksi)\b", re.I)
    DESCRIPTION = re.compile(r"\b(describe|description|appearance|look|looks|outfit|clothes|room|setting|atmosphere|detail|gambarkan|deskripsi|penampilan|pakaian|ruangan|suasana)\b", re.I)
    TRANSITION = re.compile(r"\b(transform|transformed|become|became|change|changed|transition|after|now|berubah|menjadi|setelah|sekarang|transformasi)\b", re.I)

    DIMENSION_LANES = {
        "continuity": ("continuity",),
        "state": ("structured_state",),
        "pov": ("epistemic",),
        "relationships": ("relationships",),
        "events": ("events",),
        "spatial": ("spatial",),
        "threads": ("threads",),
        "source": ("fts_manuscript", "fts_chat", "dense"),
    }

    @staticmethod
    def _route_value(route: Any) -> str:
        return str(getattr(route, "value", route or "TEXT_RECALL"))

    def _intent(self, prompt: str, route: str) -> NarrativeIntent:
        if route == "WHY_CAUSAL":
            return NarrativeIntent.CAUSAL
        if route == "CONTINUITY_CHECK":
            return NarrativeIntent.CONTINUITY_REVIEW
        if route == "BRANCH_COMPARE":
            return NarrativeIntent.BRANCH_COMPARE
        if route == "GLOBAL_SUMMARY":
            return NarrativeIntent.SUMMARY
        if route in {"TEMPORAL_STATE", "EVENT_LOOKUP", "TEXT_RECALL"}:
            if self.TRANSITION.search(prompt):
                return NarrativeIntent.TRANSITION
            if self.DIALOGUE.search(prompt):
                return NarrativeIntent.DIALOGUE
            if self.ACTION.search(prompt):
                return NarrativeIntent.ACTION
            if self.DESCRIPTION.search(prompt):
                return NarrativeIntent.DESCRIPTION
            return NarrativeIntent.RECALL
        if self.DIALOGUE.search(prompt):
            return NarrativeIntent.DIALOGUE
        if self.ACTION.search(prompt):
            return NarrativeIntent.ACTION
        if self.DESCRIPTION.search(prompt):
            return NarrativeIntent.DESCRIPTION
        if self.TRANSITION.search(prompt):
            return NarrativeIntent.TRANSITION
        return NarrativeIntent.CONTINUE

    @staticmethod
    def _workspace_scope(workspace_context: Any | None) -> dict[str, Any]:
        return dict(getattr(workspace_context, "scope", {}) or {})

    def _focus_resources(self, scope: Any, workspace_context: Any | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        ws_scope = self._workspace_scope(workspace_context)
        active = dict(ws_scope.get("active_scene") or {})
        labels: dict[tuple[str, str], str] = {}
        for row in list(getattr(workspace_context, "auto_selected", []) or []) + list(getattr(workspace_context, "explicit_references", []) or []):
            typ, rid = str(row.get("type") or ""), str(row.get("id") or "")
            if typ and rid:
                labels[(typ, rid)] = str(row.get("label") or rid)

        output: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        def add(typ: str, rid: Any, reason: str, label: str | None = None) -> None:
            rid = str(rid or "").strip()
            if not typ or not rid or (typ, rid) in seen:
                return
            seen.add((typ, rid))
            output.append({
                "type": typ,
                "id": rid,
                "label": label or labels.get((typ, rid), rid),
                "reason": reason,
                "method": "context_plan",
                "confidence": 1.0,
            })

        for ref in list(getattr(scope, "explicit_references", []) or []):
            add(str(ref.get("type") or ""), ref.get("id"), "explicit reference", str(ref.get("label") or "") or None)
        if active.get("pov_variant_id"):
            add("entity_variant", active["pov_variant_id"], "active scene POV")
        if active.get("location_variant_id"):
            add("entity_variant", active["location_variant_id"], "active scene location")
        for variant_id in (active.get("participants") or [])[:16]:
            add("entity_variant", variant_id, "present in active scene")

        anchors = {
            "document_id": active.get("document_id"),
            "pov_variant_id": getattr(scope, "pov_variant_id", None) or active.get("pov_variant_id"),
            "location_variant_id": active.get("location_variant_id"),
            "participants": list(active.get("participants") or [])[:16],
            "world_time": getattr(scope, "world_time", None) or active.get("narrative_time"),
            "story_order": getattr(scope, "story_order", None),
        }
        return output[:24], anchors

    @staticmethod
    def _base_dimensions(intent: NarrativeIntent) -> dict[str, float]:
        table = {
            NarrativeIntent.CONTINUE: dict(continuity=1.00, state=.92, relationships=.82, events=.72, spatial=.62, threads=.78, pov=.65, source=.32),
            NarrativeIntent.DIALOGUE: dict(continuity=.96, state=.78, relationships=1.00, events=.48, spatial=.36, threads=.62, pov=1.00, source=.22),
            NarrativeIntent.ACTION: dict(continuity=.96, state=.92, relationships=.58, events=1.00, spatial=.78, threads=.55, pov=.72, source=.28),
            NarrativeIntent.DESCRIPTION: dict(continuity=.82, state=1.00, relationships=.48, events=.38, spatial=1.00, threads=.30, pov=.52, source=.34),
            NarrativeIntent.TRANSITION: dict(continuity=1.00, state=.96, relationships=.62, events=1.00, spatial=.52, threads=.58, pov=.72, source=.30),
            NarrativeIntent.CAUSAL: dict(continuity=.96, state=.68, relationships=.70, events=1.00, spatial=.42, threads=.48, pov=.55, source=.58),
            NarrativeIntent.RECALL: dict(continuity=.76, state=.66, relationships=.55, events=.78, spatial=.45, threads=.35, pov=.42, source=1.00),
            NarrativeIntent.SUMMARY: dict(continuity=.72, state=.55, relationships=.55, events=.68, spatial=.34, threads=.62, pov=.30, source=.82),
            NarrativeIntent.CONTINUITY_REVIEW: dict(continuity=1.00, state=.96, relationships=.72, events=.82, spatial=.48, threads=.30, pov=.62, source=.40),
            NarrativeIntent.BRANCH_COMPARE: dict(continuity=1.00, state=.92, relationships=.68, events=.82, spatial=.42, threads=.38, pov=.35, source=.28),
        }
        return dict(table[intent])

    def plan(self, prompt: str, scope: Any, *, workspace_context: Any | None = None, route: Any = "STORY_CONTINUE") -> NarrativeContextPlan:
        route_value = self._route_value(route)
        intent = self._intent(prompt, route_value)
        focus, anchors = self._focus_resources(scope, workspace_context)
        lens = str(getattr(getattr(scope, "context_lens", "scene"), "value", getattr(scope, "context_lens", "scene")) or "scene")
        dimensions = self._base_dimensions(intent)
        if anchors.get("pov_variant_id"):
            dimensions["pov"] = max(dimensions["pov"], 1.0 if lens == "pov" else .84)
        elif lens == "pov":
            dimensions["pov"] = .35
        if not anchors.get("location_variant_id"):
            dimensions["spatial"] *= .72
        if not anchors.get("participants") and len([x for x in focus if x["type"] == "entity_variant"]) < 2:
            dimensions["relationships"] *= .74

        lane_weights: dict[str, float] = {}
        lane_factor = {"fts_manuscript": .80, "fts_chat": .55, "dense": .70}
        for dimension, weight in dimensions.items():
            for lane in self.DIMENSION_LANES[dimension]:
                lane_weights[lane] = max(lane_weights.get(lane, 0.0), round(weight * lane_factor.get(lane, 1.0), 3))

        optional_lanes = [lane for lane, _ in sorted(lane_weights.items(), key=lambda item: (-item[1], item[0])) if _ >= .18]
        required_lanes: list[str] = ["continuity"] if route_value == "CONTINUITY_CHECK" else []
        preserve_order = ["continuity", "epistemic", "structured_state", "relationships", "events", "spatial", "threads"]
        preserve_lanes = [lane for lane in preserve_order if lane_weights.get(lane, 0.0) >= .55][:6]

        token_budget = max(0, int(getattr(scope, "token_budget", 0) or 0))
        lane_token_budget: dict[str, int] = {}
        if token_budget and optional_lanes:
            total_weight = sum(max(.05, lane_weights.get(lane, .05)) for lane in optional_lanes)
            distributable = max(0, token_budget - 96)
            for lane in optional_lanes:
                share = max(.05, lane_weights.get(lane, .05)) / total_weight
                lane_token_budget[lane] = max(96, int(distributable * share))

        diagnostics: list[str] = []
        if lens == "pov" and not anchors.get("pov_variant_id"):
            diagnostics.append("POV lens requested without an active POV variant; epistemic retrieval stays conservative.")
        if not focus:
            diagnostics.append("No explicit or active-scene entity anchors; retrieval may rely on scoped text evidence.")

        return NarrativeContextPlan(
            version=self.VERSION,
            route=route_value,
            intent=intent.value,
            lens=lens,
            focus_resources=focus,
            scene_anchors=anchors,
            dimensions={k: round(v, 3) for k, v in dimensions.items()},
            required_lanes=required_lanes,
            optional_lanes=optional_lanes,
            preserve_lanes=preserve_lanes,
            lane_weights=lane_weights,
            lane_token_budget=lane_token_budget,
            policies={
                "canon_precedence": True,
                "derived_continuity_is_non_authoritative": True,
                "ambiguity_policy": "abstain_and_surface",
                "pov_boundary": "enforce_scope_gate" if lens in {"scene", "pov"} else "author_lens",
                "future_knowledge": "allowed" if bool(getattr(scope, "allow_future_author_knowledge", False)) else "blocked",
                "fuzzy_identity_merge": False,
            },
            diagnostics=diagnostics,
        )
