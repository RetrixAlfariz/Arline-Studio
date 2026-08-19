from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
from typing import Any


DELIBERATION_VERSION = "1.2.4a1"


@dataclass(slots=True)
class NarrativeDeliberation:
    version: str = DELIBERATION_VERSION
    status: str = "disabled"
    intent: str = "continue"
    output_mode: str = "fiction"
    scene_goal: str = ""
    likely_beats: list[str] = field(default_factory=list)
    character_intentions: list[str] = field(default_factory=list)
    emotional_trajectories: list[str] = field(default_factory=list)
    opportunities: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def render(self) -> str:
        lines = [
            "@ARLINE-NARRATIVE-DELIBERATION 1.2.4",
            "authority: soft_non_canon",
            "canon_commit: forbidden",
            "rule: possibilities guide realization but never override authoritative context, explicit directives, UNKNOWN values, POV boundaries, or unresolved conflicts.",
            f"status: {self.status}",
            f"intent: {self.intent}",
        ]
        if self.scene_goal:
            lines.append("scene_goal: " + self.scene_goal)
        for label, values in (
            ("likely_beats", self.likely_beats),
            ("character_intentions", self.character_intentions),
            ("emotional_trajectories", self.emotional_trajectories),
            ("opportunities", self.opportunities),
            ("alternatives", self.alternatives),
            ("uncertainties", self.uncertainties),
            ("constraints", self.constraints),
        ):
            if values:
                lines.append(f"[{label.upper()}]")
                lines.extend("- " + item for item in values)
        return "\n".join(lines).rstrip() + "\n"


class NarrativeDeliberator:
    SYSTEM = """You are Arline's Narrative Deliberator, not the prose writer.
Return ONE JSON object only. Do not write story prose. Do not invent canon.
Treat authoritative context as hard constraints. Treat unresolved conflicts and UNKNOWN precision as unresolved.
Infer only soft narrative possibilities: what characters may want, what beats are plausible, what emotional movement is natural, and what alternatives exist.
Never turn private knowledge into another character's knowledge. Never resolve ambiguity silently.
Required keys: scene_goal, likely_beats, character_intentions, emotional_trajectories, opportunities, alternatives, uncertainties, constraints.
All list values must be short strings. Keep each list concise."""

    def __init__(self, config):
        self.config = config

    @staticmethod
    def _clip_list(value: Any, limit: int = 8) -> list[str]:
        if not isinstance(value, list):
            return []
        out = []
        for item in value:
            text = str(item).strip()
            if text and text not in out:
                out.append(text[:500])
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _json_object(text: str) -> dict[str, Any]:
        cleaned = str(text or "").strip()
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I | re.S).strip()
        try:
            value = json.loads(cleaned)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start >= 0 and end > start:
                try:
                    value = json.loads(cleaned[start:end + 1])
                    return value if isinstance(value, dict) else {}
                except json.JSONDecodeError:
                    return {}
        return {}

    def fallback(self, directive: dict[str, Any], reason: str, *, model: str = "") -> NarrativeDeliberation:
        semantic = str(directive.get("semantic_prompt") or "").strip()
        return NarrativeDeliberation(
            status="fallback",
            intent=str(directive.get("planner_intent") or "continue"),
            output_mode=str(directive.get("output_mode") or "fiction"),
            scene_goal=semantic[:500],
            uncertainties=["Model intuition was unavailable; keep the realization conservative and grounded in authoritative context."],
            constraints=["Do not invent missing canon or resolve ambiguity silently."],
            diagnostics=[reason[:1000]],
            model=model,
        )

    def disabled(self, directive: dict[str, Any], *, model: str = "") -> NarrativeDeliberation:
        return NarrativeDeliberation(
            status="disabled", intent=str(directive.get("planner_intent") or "continue"),
            output_mode=str(directive.get("output_mode") or "fiction"), model=model,
        )

    def deliberate(self, *, client, model: str, directive: dict[str, Any], context_plan: dict[str, Any],
                   workspace_text: str, wcf_text: str, narrative_brief: str) -> NarrativeDeliberation:
        cfg = self.config.deliberation
        if not cfg.enabled:
            return self.disabled(directive, model=model)
        mode = str(directive.get("deliberation_mode") or "auto")
        if mode == "off":
            return self.disabled(directive, model=model)
        context = "\n\n".join(filter(None, [
            "<WORKSPACE>\n" + workspace_text.strip() + "\n</WORKSPACE>" if workspace_text.strip() else "",
            "<WCF>\n" + wcf_text.strip() + "\n</WCF>" if wcf_text.strip() else "",
            "<NARRATIVE_BRIEF>\n" + narrative_brief.strip() + "\n</NARRATIVE_BRIEF>" if narrative_brief.strip() else "",
        ]))
        context = context[-max(4000, int(cfg.context_chars)):]
        request = {
            "directive": directive,
            "context_plan": context_plan,
            "deliberation_mode": mode,
            "alternatives_requested": max(1, int(cfg.alternatives)),
        }
        input_text = (
            "<AUTHORITATIVE_CONTEXT>\n" + context + "\n</AUTHORITATIVE_CONTEXT>\n\n"
            "<DELIBERATION_REQUEST>\n" + json.dumps(request, ensure_ascii=False) + "\n</DELIBERATION_REQUEST>"
        )
        try:
            result = client.chat(
                model=model,
                input_text=input_text,
                system_prompt=self.SYSTEM,
                temperature=float(cfg.temperature),
                top_p=0.9,
                top_k=40,
                min_p=0.0,
                max_tokens=max(128, int(cfg.max_tokens)),
                repeat_penalty=1.02,
                reasoning=None,
                context_length=self.config.model_load.context_length,
                seed=self.config.generation.seed,
                extra_payload={},
            )
            payload = self._json_object(result.text)
            if not payload:
                return self.fallback(directive, "Deliberator returned non-JSON output.", model=model)
            return NarrativeDeliberation(
                status="model",
                intent=str(directive.get("planner_intent") or context_plan.get("intent") or "continue"),
                output_mode=str(directive.get("output_mode") or "fiction"),
                scene_goal=str(payload.get("scene_goal") or directive.get("semantic_prompt") or "")[:500],
                likely_beats=self._clip_list(payload.get("likely_beats")),
                character_intentions=self._clip_list(payload.get("character_intentions")),
                emotional_trajectories=self._clip_list(payload.get("emotional_trajectories")),
                opportunities=self._clip_list(payload.get("opportunities")),
                alternatives=self._clip_list(payload.get("alternatives"), max(1, int(cfg.alternatives))),
                uncertainties=self._clip_list(payload.get("uncertainties")),
                constraints=self._clip_list(payload.get("constraints")),
                model=model,
            )
        except Exception as exc:
            return self.fallback(directive, f"Deliberator failure: {exc}", model=model)
