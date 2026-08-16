from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from .voice import DescriptionLens, LanguageProfile, SceneEnergy, VoiceProfileExtractor


@dataclass(slots=True)
class StyleProfile:
    pov: str = "first_person"
    tense: str = "unspecified"
    detail: str = "high"
    atmosphere: str = "high"
    pacing: str = "slow"
    dialogue_density: str = "adaptive"

    def to_dict(self): return asdict(self)


@dataclass(slots=True)
class AuthorialFreedom:
    atmosphere: str = "high"
    dialogue: str = "high"
    minor_props: str = "medium"
    gestures: str = "high"
    body: str = "locked"
    relationship: str = "locked"
    measurements: str = "locked"
    persistent_location: str = "low"
    technology_mechanism: str = "locked"
    timeline: str = "locked"

    def to_dict(self): return asdict(self)


@dataclass(slots=True)
class SceneGoal:
    phase: str = "scene"
    focus: list[str] = field(default_factory=list)
    objective: str = "advance the requested scene without contradicting canonical state"
    do_not_advance_beyond: list[str] = field(default_factory=list)

    def to_dict(self): return asdict(self)


@dataclass(slots=True)
class BeatState:
    current_beat: str = "establish_current_scene"
    completed_beats: list[str] = field(default_factory=list)
    next_candidates: list[str] = field(default_factory=list)
    forbidden_future_beats: list[str] = field(default_factory=list)
    exit_condition: str = "end at a natural continuation point after the current material is meaningfully advanced"

    def to_dict(self): return asdict(self)


@dataclass(slots=True)
class SurfaceHistory:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    turn: int = 0

    @classmethod
    def from_input(cls, value: Any) -> "SurfaceHistory":
        if isinstance(value, cls):
            return value
        history = cls()
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    history.mark(item, explicit=True)
                elif isinstance(item, dict) and item.get("concept"):
                    concept = str(item["concept"])
                    history.records[concept] = {
                        "explicit_count": int(item.get("explicit_count", 0)),
                        "implicit_count": int(item.get("implicit_count", 0)),
                        "last_turn": int(item.get("last_turn", 0)),
                    }
        elif isinstance(value, dict):
            for concept, record in value.items():
                if isinstance(record, dict):
                    history.records[str(concept)] = dict(record)
        return history

    def mark(self, concept: str, *, explicit: bool = False, implicit: bool = False) -> None:
        record = self.records.setdefault(concept, {
            "explicit_count": 0,
            "implicit_count": 0,
            "last_turn": self.turn,
        })
        if explicit:
            record["explicit_count"] = int(record.get("explicit_count", 0)) + 1
        if implicit:
            record["implicit_count"] = int(record.get("implicit_count", 0)) + 1
        record["last_turn"] = self.turn

    def novelty(self, concept: str) -> float:
        record = self.records.get(concept)
        if not record:
            return 1.0
        explicit = int(record.get("explicit_count", 0))
        implicit = int(record.get("implicit_count", 0))
        age = max(0, self.turn - int(record.get("last_turn", self.turn)))
        base = 1.0 / (1.0 + 1.0 * explicit + .45 * implicit)
        # A concept gradually regains a little narrative novelty after many turns.
        return round(min(1.0, base + min(.25, age * .025)), 4)

    def to_dict(self):
        return {"turn": self.turn, "records": self.records}


@dataclass(slots=True)
class NarrativeRuntime:
    version: str
    language: LanguageProfile
    description_lens: DescriptionLens
    scene_energy: SceneEnergy
    paragraph_functions: list[str]
    style: StyleProfile
    freedom: AuthorialFreedom
    scene_goal: SceneGoal
    beat_state: BeatState
    surface_history: SurfaceHistory

    def to_dict(self):
        return {
            "version": self.version,
            "language": self.language.to_dict(),
            "description_lens": self.description_lens.to_dict(),
            "scene_energy": self.scene_energy.to_dict(),
            "paragraph_functions": self.paragraph_functions,
            "style": self.style.to_dict(),
            "freedom": self.freedom.to_dict(),
            "scene_goal": self.scene_goal.to_dict(),
            "beat_state": self.beat_state.to_dict(),
            "surface_history": self.surface_history.to_dict(),
        }


class NarrativeRuntimeBuilder:
    VERSION = "0.1"

    @classmethod
    def default(cls): return cls()

    def build(self, raw_prompt: str, pipeline_result, *, surface_history=None) -> NarrativeRuntime:
        state = pipeline_result.extracted_state
        events = pipeline_result.events
        analysis = pipeline_result.analysis
        directives = " ".join(x.get("text", "") for x in state.get("directives", [])).lower()
        focus = analysis.get("scene_focus", {}) or {}

        pov = "first_person" if re.search(r"\b(?:aku|ku|saya)\b", raw_prompt.lower()) else "unspecified"
        style = StyleProfile(
            pov=pov,
            detail="high" if "detail" in directives else "adaptive",
            atmosphere="high" if ("atmos" in directives or focus.get("atmosphere", 0) > .6) else "adaptive",
            pacing="slow" if ("prologue" in directives or "sangat-sangat panjang" in directives) else "adaptive",
        )

        phase = "prologue" if "prologue" in directives else "scene"
        active_focus = [k for k, v in sorted(focus.items()) if isinstance(v, (int, float)) and v >= .45]
        objective = (
            "explore the prologue and character naturally, then advance only through the active requested transformations"
            if phase == "prologue"
            else "advance the requested scene while preserving canonical world state"
        )
        scene_goal = SceneGoal(
            phase=phase,
            focus=active_focus,
            objective=objective,
            do_not_advance_beyond=[],
        )

        runtime_events = events.get("events", []) or []
        scenario_events = events.get("scenario_events", []) or []
        if phase == "prologue":
            current_beat = "character_and_scene_establishment"
        elif scenario_events:
            current_beat = str(scenario_events[0].get("type") or "requested_scene_event")
        elif runtime_events:
            current_beat = str(runtime_events[0].get("type") or "current_scene")
        else:
            current_beat = "establish_current_scene"

        next_candidates = []
        for event in scenario_events + runtime_events:
            etype = event.get("type")
            if etype and etype not in next_candidates:
                next_candidates.append(str(etype))
        beat = BeatState(
            current_beat=current_beat,
            completed_beats=[],
            next_candidates=next_candidates[:8],
            forbidden_future_beats=[],
        )
        history = SurfaceHistory.from_input(surface_history)
        language = VoiceProfileExtractor.extract(raw_prompt)
        description_lens = VoiceProfileExtractor.description_lens(raw_prompt)
        scene_energy = SceneEnergy(
            level="low" if phase == "prologue" else "adaptive",
            pacing=style.pacing,
            change_rate="low_medium" if phase == "prologue" else "adaptive",
            introspection="medium",
        )
        paragraph_functions = [
            "establish_space",
            "establish_character",
            "physical_or_social_interaction",
            "state_or_scene_progression",
            "reaction_or_new_observation",
        ]
        return NarrativeRuntime(
            version="0.2",
            language=language,
            description_lens=description_lens,
            scene_energy=scene_energy,
            paragraph_functions=paragraph_functions,
            style=style,
            freedom=AuthorialFreedom(),
            scene_goal=scene_goal,
            beat_state=beat,
            surface_history=history,
        )
