from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .rails import (
    CharacterRail,
    ExpressionChannel,
    RailCompilation,
    RailKind,
    RailPacing,
)


@dataclass(slots=True, frozen=True)
class BeatBudget:
    minimum: int
    target: int
    maximum: int

    def to_dict(self) -> dict[str, int]:
        return {"min": self.minimum, "target": self.target, "max": self.maximum}


@dataclass(slots=True, frozen=True)
class SceneDynamicsPlan:
    rail_index: int
    kind: str
    participants: tuple[str, ...]
    pacing: str
    intensity: str
    intensity_curve: str
    beat_budget: BeatBudget
    allowed_channels: tuple[str, ...]
    speaker_order: str
    internal_access: str
    termination: str
    narrative_rules: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rail_index": self.rail_index,
            "kind": self.kind,
            "participants": list(self.participants),
            "pacing": self.pacing,
            "intensity": self.intensity,
            "intensity_curve": self.intensity_curve,
            "beat_budget": self.beat_budget.to_dict(),
            "allowed_channels": list(self.allowed_channels),
            "speaker_order": self.speaker_order,
            "internal_access": self.internal_access,
            "termination": self.termination,
            "narrative_rules": list(self.narrative_rules),
        }


class SceneDynamicsPlanner:
    """Deterministic scene-shape planning; the writer still authors the prose."""

    BASE_BUDGETS = {
        RailPacing.AUTO: BeatBudget(2, 5, 8),
        RailPacing.IMMEDIATE: BeatBudget(1, 2, 4),
        RailPacing.FAST: BeatBudget(2, 3, 5),
        RailPacing.NATURAL: BeatBudget(2, 5, 8),
        RailPacing.SLOW: BeatBudget(4, 7, 11),
        RailPacing.LINGERING: BeatBudget(6, 10, 16),
    }

    @classmethod
    def _budget(cls, rail: CharacterRail) -> BeatBudget:
        base = cls.BASE_BUDGETS[rail.pacing]
        if rail.length == "short":
            budget = BeatBudget(max(1, base.minimum - 1), max(1, round(base.target * 0.65)), max(2, round(base.maximum * 0.65)))
        elif rail.length == "long":
            budget = BeatBudget(base.minimum + 1, max(base.target + 2, round(base.target * 1.35)), max(base.maximum + 3, round(base.maximum * 1.35)))
        else:
            budget = base

        if rail.kind == RailKind.MONOLOGUE:
            return BeatBudget(min(budget.minimum, 3), min(budget.target, 7), min(budget.maximum, 10))
        if rail.kind == RailKind.AMBIENCE:
            return BeatBudget(min(budget.minimum, 2), min(budget.target, 5), min(budget.maximum, 8))
        return budget

    @staticmethod
    def _channels(rail: CharacterRail) -> tuple[str, ...]:
        if rail.kind == RailKind.AMBIENCE:
            return (ExpressionChannel.AMBIENCE.value, ExpressionChannel.ACTION.value)
        if rail.kind == RailKind.MONOLOGUE:
            if rail.channel == ExpressionChannel.SPEECH:
                return (
                    ExpressionChannel.SPEECH.value,
                    ExpressionChannel.ACTION.value,
                    ExpressionChannel.SILENCE.value,
                    ExpressionChannel.AMBIENCE.value,
                )
            return (
                ExpressionChannel.INTERNAL.value,
                ExpressionChannel.ACTION.value,
                ExpressionChannel.AMBIENCE.value,
            )
        return (
            ExpressionChannel.SPEECH.value,
            ExpressionChannel.ACTION.value,
            ExpressionChannel.SILENCE.value,
            ExpressionChannel.VOCALIZATION.value,
            ExpressionChannel.INTERNAL.value,
            ExpressionChannel.AMBIENCE.value,
        )

    @staticmethod
    def _rules(rail: CharacterRail) -> tuple[str, ...]:
        rules = [
            "Treat the beat budget as a soft narrative-shape bound, never a turn quota.",
            "Every beat should change action, information, reaction, tension, distance, or atmosphere.",
            "Do not add filler beats only to reach the target count.",
        ]
        if rail.pacing in {RailPacing.SLOW, RailPacing.LINGERING}:
            rules.append("Preserve intermediate reactions, hesitation, processing, and pauses before resolution.")
        if rail.pacing in {RailPacing.IMMEDIATE, RailPacing.FAST}:
            rules.append("Move quickly toward the core interaction while preserving causally necessary reactions.")
        if rail.kind == RailKind.DIALOGUE:
            rules.append("Allocate initiative by character state; consecutive utterances and asymmetric silence are valid.")
        if rail.kind == RailKind.INTIMACY:
            rules.append("Preserve POV, character agency, scene logic, and meaningful aftermath within the configured narrative boundary.")
        if rail.kind == RailKind.MONOLOGUE and rail.channel == ExpressionChannel.INTERNAL:
            rules.append("Internal content remains private unless an established event makes it observable or known.")
        return tuple(rules)

    @classmethod
    def plan(cls, compilation: RailCompilation) -> list[SceneDynamicsPlan]:
        plans: list[SceneDynamicsPlan] = []
        for rail in compilation.rails:
            plans.append(SceneDynamicsPlan(
                rail_index=rail.index,
                kind=rail.kind.value,
                participants=tuple(rail.participants),
                pacing=rail.pacing.value,
                intensity=rail.intensity.value,
                intensity_curve=rail.intensity_curve,
                beat_budget=cls._budget(rail),
                allowed_channels=cls._channels(rail),
                speaker_order="adaptive" if rail.kind in {RailKind.DIALOGUE, RailKind.INTIMACY} else "not_applicable",
                internal_access="active_pov_only" if ExpressionChannel.INTERNAL.value in cls._channels(rail) else "none",
                termination=rail.termination,
                narrative_rules=cls._rules(rail),
            ))
        return plans

    @classmethod
    def render(cls, compilation: RailCompilation) -> str:
        plans = cls.plan(compilation)
        if not plans:
            return ""
        lines = [
            "@ARLINE-SCENE-DYNAMICS 1.0",
            "planner: deterministic_shape_only",
            "prose_authority: writer",
        ]
        for plan in plans:
            budget = plan.beat_budget
            lines.extend([
                "",
                f"[DYNAMICS {plan.rail_index}: {plan.kind.upper()}]",
                f"beat_budget: min={budget.minimum}, target={budget.target}, max={budget.maximum}",
                f"speaker_order: {plan.speaker_order}",
                f"internal_access: {plan.internal_access}",
                "allowed_channels: " + ", ".join(plan.allowed_channels),
                f"pacing: {plan.pacing}",
                f"intensity: {plan.intensity}",
                f"intensity_curve: {plan.intensity_curve}",
                f"termination: {plan.termination}",
                "rules:",
            ])
            lines.extend("- " + rule for rule in plan.narrative_rules)
        return "\n".join(lines).rstrip() + "\n"
