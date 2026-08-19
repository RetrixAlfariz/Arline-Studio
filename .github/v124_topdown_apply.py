from __future__ import annotations

from pathlib import Path
import re

ROOT = Path.cwd()
VERSION = "1.2.4a1"
CACHE_KEY = "1.2.4-directives"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise SystemExit(f"anchor missing in {path}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


def replace_all(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        return
    write(path, text.replace(old, new))


DIRECTIVES = r'''from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
import shlex
from typing import Any


COMMAND_REGISTRY_VERSION = "1.2.4a1"
REFERENCE_SELECTORS = (
    "voice", "state", "appearance", "knowledge", "beliefs",
    "relationships", "timeline", "evidence", "conflicts",
)
DYNAMIC_REFERENCES = (
    "scene", "pov", "location", "cast", "world", "branch", "threads", "recent",
)


@dataclass(frozen=True, slots=True)
class CommandSpec:
    id: str
    label: str
    category: str
    description: str
    text: str
    planner_intent: str
    deliberation_mode: str = "auto"
    output_mode: str = "fiction"
    aliases: tuple[str, ...] = ()
    syntax: str = ""
    generation_only: bool = True
    action: str = "insert"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["aliases"] = list(self.aliases)
        return data


COMMAND_SPECS: tuple[CommandSpec, ...] = (
    CommandSpec("continue", "/continue", "Writing", "Continue the active scene with continuity-aware context", "/continue ", "continue", syntax="/continue [@refs] [options] [\"goal\"]"),
    CommandSpec("rewrite", "/rewrite", "Writing", "Rewrite current/selected material while preserving requested constraints", "/rewrite ", "description", "rewrite", syntax="/rewrite [@refs] [tone=...] [preserve=...] \"goal\""),
    CommandSpec("mono", "/mono", "Character Rails", "Character-aware monologue or expression seed", "/mono @characterA \"intent or thought\" ", "dialogue", "character", syntax="/mono @character [internal|spoken] [pacing] \"intent\""),
    CommandSpec("dia", "/dia", "Character Rails", "Character-aware adaptive dialogue / interaction", "/dia @characterA @characterB \"topic or interaction goal\" ", "dialogue", "interaction", syntax="/dia @characterA @characterB [pacing] [curve=...] \"topic\""),
    CommandSpec("ambience", "/ambience", "Scene Rails", "Guide atmosphere and sensory emphasis without changing canon", "/ambience @location slow \"scene atmosphere\" ", "description", "scene", syntax="/ambience [@location] [pacing] \"atmosphere\""),
    CommandSpec("intimacy", "/intimacy", "Scene Rails", "Guide character-aware intimate scene dynamics and aftermath", "/intimacy @characterA @characterB slow \"scene intent\" ", "dialogue", "interaction", syntax="/intimacy @characterA [@characterB] [pacing] [curve=...] \"intent\""),
    CommandSpec("intuition", "/intuition", "Deliberation", "Ask the narrative deliberator what most naturally follows from the current state", "/intuition @scene \"what should naturally happen next?\" ", "deliberate", "inspect", "author_intuition", aliases=("think", "next-beat"), syntax="/intuition [@refs] [\"question\"]"),
    CommandSpec("alternatives", "/alternatives", "Deliberation", "Generate several non-canonical next-beat alternatives", "/alternatives @scene count=4 \"next beat\" ", "deliberate", "alternatives", "author_alternatives", aliases=("alts", "options"), syntax="/alternatives [@refs] [count=N] [\"goal\"]"),
    CommandSpec("describe", "/describe", "Writing", "Describe a referenced subject with selector-aware context", "/describe @subject.appearance detail=high ", "description", "scene", syntax="/describe @ref[.selector] [detail=...] [\"focus\"]"),
    CommandSpec("pov", "/pov", "Writing", "Temporarily emphasize a POV reference for this generation", "/pov @character \"scene intent\" ", "continue", "character", syntax="/pov @character [\"scene intent\"]"),
    CommandSpec("pace", "/pace", "Writing", "Temporarily steer narrative pacing for this generation", "/pace slow \"scene goal\" ", "continue", "scene", syntax="/pace [immediate|fast|natural|slow|lingering] [\"goal\"]"),
)
COMMAND_BY_ID = {item.id: item for item in COMMAND_SPECS}
COMMAND_ALIAS = {
    alias.casefold(): item for item in COMMAND_SPECS for alias in (item.id, item.label.lstrip("/"), *item.aliases)
}


@dataclass(slots=True)
class DirectiveIntent:
    version: str
    raw_prompt: str
    semantic_prompt: str
    command: dict[str, Any] | None = None
    options: dict[str, Any] = field(default_factory=dict)
    reference_expressions: list[str] = field(default_factory=list)
    resolved_references: list[dict[str, Any]] = field(default_factory=list)
    dynamic_scopes: list[str] = field(default_factory=list)
    unresolved_references: list[str] = field(default_factory=list)
    planner_intent: str | None = None
    deliberation_mode: str = "auto"
    output_mode: str = "fiction"
    generation_only: bool = True
    diagnostics: list[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return bool(self.command or self.reference_expressions)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def render(self) -> str:
        if not self.active:
            return ""
        lines = [
            "@ARLINE-DIRECTIVE 1.2.4",
            "authority: user_intent_not_story_fact",
            "canon_commit: forbidden",
        ]
        if self.command:
            lines += [
                f"command: {self.command.get('label')}",
                f"planner_intent: {self.planner_intent or 'auto'}",
                f"deliberation_mode: {self.deliberation_mode}",
                f"output_mode: {self.output_mode}",
            ]
        if self.options:
            lines.append("options: " + ", ".join(f"{k}={v}" for k, v in sorted(self.options.items())))
        if self.resolved_references:
            rendered = []
            for ref in self.resolved_references:
                label = str(ref.get("label") or ref.get("id") or "?")
                selector = str(ref.get("selector") or "").strip()
                rendered.append("@" + label + ("." + selector if selector else ""))
            lines.append("grounding: " + ", ".join(rendered))
        if self.dynamic_scopes:
            lines.append("dynamic_scopes: " + ", ".join(self.dynamic_scopes))
        if self.unresolved_references:
            lines.append("unresolved: " + ", ".join(self.unresolved_references))
            lines.append("unresolved_policy: abstain; do not fabricate identity")
        return "\n".join(lines).rstrip() + "\n"


class DirectiveEngine:
    COMMAND_LINE = re.compile(r"^\s*/([\w-]+)\b(.*)$", re.I)
    REFERENCE = re.compile(r"@([\w.:-]+)", re.UNICODE)
    PACING = {"auto", "immediate", "fast", "natural", "slow", "lingering"}
    SOFT_FLAGS = PACING | {"internal", "spoken", "speech", "solo", "literal", "low", "medium", "high"}

    @classmethod
    def catalog(cls) -> list[dict[str, Any]]:
        return [item.to_dict() for item in COMMAND_SPECS]

    @classmethod
    def dynamic_reference_suggestions(
        cls, query: str, *, active_scene: dict[str, Any] | None = None,
        world_id: str | None = None, branch_id: str | None = None,
    ) -> list[dict[str, Any]]:
        needle = str(query or "").lstrip("@").casefold().strip()
        scene = dict(active_scene or {})
        availability = {
            "scene": bool(scene.get("document_id")),
            "pov": bool(scene.get("pov_variant_id")),
            "location": bool(scene.get("location_variant_id")),
            "cast": bool(scene.get("participants")),
            "world": bool(world_id),
            "branch": bool(branch_id),
            "threads": True,
            "recent": True,
        }
        subtitle = {
            "scene": "dynamic · active scene document",
            "pov": "dynamic · active scene POV",
            "location": "dynamic · active scene location",
            "cast": "dynamic · active scene participants",
            "world": "dynamic · current world",
            "branch": "dynamic · current branch",
            "threads": "dynamic · open story threads",
            "recent": "dynamic · recent scoped evidence",
        }
        out = []
        for name in DYNAMIC_REFERENCES:
            if needle and needle not in name:
                continue
            out.append({
                "type": "dynamic_reference", "id": name, "label": name,
                "subtitle": subtitle[name], "dynamic": True,
                "available": availability[name], "current_world": True,
            })
        return out

    @staticmethod
    def _split_selector(expression: str) -> tuple[str, str | None]:
        if "." not in expression:
            return expression, None
        base, selector = expression.rsplit(".", 1)
        if selector.casefold() in REFERENCE_SELECTORS:
            return base, selector.casefold()
        return expression, None

    @staticmethod
    def _dedupe(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for ref in refs:
            typ, rid = str(ref.get("type") or ""), str(ref.get("id") or "")
            selector = str(ref.get("selector") or "")
            if not typ or not rid:
                continue
            key = (typ, rid, selector)
            if key in seen:
                continue
            seen.add(key)
            out.append(dict(ref))
        return out

    @classmethod
    def _resolve_dynamic(
        cls, base: str, selector: str | None, *, active_scene: dict[str, Any],
        project_id: str | None, world_id: str | None, branch_id: str | None,
    ) -> tuple[list[dict[str, Any]], list[str], str | None]:
        scene = active_scene or {}
        refs: list[dict[str, Any]] = []
        scopes: list[str] = []
        error: str | None = None

        def add(typ: str, rid: Any, label: str) -> None:
            if rid:
                refs.append({"type": typ, "id": str(rid), "label": label, "mode": "context", "selector": selector, "dynamic_source": base})

        if base == "scene":
            add("document", scene.get("document_id"), "scene")
        elif base == "pov":
            add("entity_variant", scene.get("pov_variant_id"), "pov")
        elif base == "location":
            add("entity_variant", scene.get("location_variant_id"), "location")
        elif base == "cast":
            for rid in list(scene.get("participants") or [])[:16]:
                add("entity_variant", rid, "cast")
        elif base == "world":
            add("world", world_id, "world")
        elif base == "branch":
            add("branch", branch_id, "branch")
        elif base in {"threads", "recent"}:
            scopes.append(base)
        if base not in {"threads", "recent"} and not refs:
            error = f"@{base} is unavailable in the current scene/scope"
        return refs, scopes, error

    @classmethod
    def parse(
        cls, prompt: str, *, explicit_references: list[dict[str, Any]] | None = None,
        active_scene: dict[str, Any] | None = None, project_id: str | None = None,
        world_id: str | None = None, branch_id: str | None = None,
    ) -> DirectiveIntent:
        raw = str(prompt or "")
        explicit = [dict(item) for item in (explicit_references or [])]
        active_scene = dict(active_scene or {})
        diagnostics: list[str] = []
        command_spec: CommandSpec | None = None
        command_line_index: int | None = None
        command_rest = ""
        lines = raw.splitlines()
        for index, line in enumerate(lines):
            match = cls.COMMAND_LINE.match(line)
            if not match:
                continue
            spec = COMMAND_ALIAS.get(match.group(1).casefold())
            if spec is not None:
                command_spec = spec
                command_line_index = index
                command_rest = match.group(2).strip()
                break

        options: dict[str, Any] = {}
        seed_parts: list[str] = []
        if command_spec is not None:
            try:
                tokens = shlex.split(command_rest, posix=True)
            except ValueError as exc:
                tokens = command_rest.split()
                diagnostics.append(f"slash command parse fallback: {exc}")
            for token in tokens:
                if token.startswith("@"):
                    continue
                if "=" in token:
                    key, value = token.split("=", 1)
                    if key.strip():
                        options[key.strip().casefold()] = value.strip()
                        continue
                low = token.casefold()
                if low in cls.SOFT_FLAGS:
                    options.setdefault("pacing" if low in cls.PACING else low, low)
                    continue
                seed_parts.append(token)

        expressions = cls.REFERENCE.findall(raw)
        resolved = [dict(item) for item in explicit]
        dynamic_scopes: list[str] = []
        unresolved: list[str] = []

        explicit_lookup: dict[str, dict[str, Any]] = {}
        for ref in explicit:
            for value in (ref.get("label"), ref.get("name"), ref.get("id")):
                if value:
                    explicit_lookup[str(value).casefold()] = ref

        for expression in expressions:
            base_raw, selector = cls._split_selector(expression)
            base = base_raw.casefold()
            if base in DYNAMIC_REFERENCES:
                dynamic, scopes, error = cls._resolve_dynamic(
                    base, selector, active_scene=active_scene,
                    project_id=project_id, world_id=world_id, branch_id=branch_id,
                )
                resolved.extend(dynamic)
                dynamic_scopes.extend(scopes)
                if error:
                    diagnostics.append(error)
                continue
            matched = explicit_lookup.get(base)
            if matched is None:
                unresolved.append("@" + expression)
                continue
            candidate = dict(matched)
            if selector:
                candidate["selector"] = selector
            resolved.append(candidate)

        resolved = cls._dedupe(resolved)
        kept_lines = [line for index, line in enumerate(lines) if index != command_line_index]
        prose_tail = "\n".join(kept_lines).strip()
        seed = " ".join(seed_parts).strip()
        if command_spec is None:
            semantic = raw.strip()
        else:
            semantic_parts = [part for part in (seed, prose_tail) if part]
            if semantic_parts:
                semantic = "\n".join(semantic_parts)
            elif command_spec.id == "continue":
                semantic = "Continue the active scene naturally."
            elif command_spec.id == "intuition":
                semantic = "Assess the most natural next narrative beat."
            elif command_spec.id == "alternatives":
                semantic = "Propose distinct plausible next narrative beats."
            elif command_spec.id == "describe":
                semantic = "Describe the explicitly grounded subject."
            elif command_spec.id == "rewrite":
                semantic = "Rewrite the requested material while preserving authoritative constraints."
            else:
                semantic = f"Execute the {command_spec.label} generation directive using the active scene."

        if unresolved:
            diagnostics.append("Unresolved @ reference expressions are not guessed or fabricated.")
        return DirectiveIntent(
            version=COMMAND_REGISTRY_VERSION,
            raw_prompt=raw,
            semantic_prompt=semantic or raw.strip(),
            command=command_spec.to_dict() if command_spec else None,
            options=options,
            reference_expressions=["@" + item for item in expressions],
            resolved_references=resolved,
            dynamic_scopes=list(dict.fromkeys(dynamic_scopes)),
            unresolved_references=list(dict.fromkeys(unresolved)),
            planner_intent=command_spec.planner_intent if command_spec else None,
            deliberation_mode=command_spec.deliberation_mode if command_spec else "auto",
            output_mode=command_spec.output_mode if command_spec else "fiction",
            generation_only=command_spec.generation_only if command_spec else True,
            diagnostics=diagnostics,
        )
'''

DIRECTIVES_INIT = r'''from .engine import (
    COMMAND_REGISTRY_VERSION,
    DYNAMIC_REFERENCES,
    REFERENCE_SELECTORS,
    CommandSpec,
    DirectiveEngine,
    DirectiveIntent,
)

__all__ = [
    "COMMAND_REGISTRY_VERSION", "DYNAMIC_REFERENCES", "REFERENCE_SELECTORS",
    "CommandSpec", "DirectiveEngine", "DirectiveIntent",
]
'''

DELIBERATION = r'''from __future__ import annotations

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
'''

DELIBERATION_INIT = r'''from .engine import DELIBERATION_VERSION, NarrativeDeliberation, NarrativeDeliberator

__all__ = ["DELIBERATION_VERSION", "NarrativeDeliberation", "NarrativeDeliberator"]
'''

TESTS = r'''from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from src.context.intelligence import NarrativeContextPlanner
from src.deliberation import NarrativeDeliberator
from src.directives import COMMAND_REGISTRY_VERSION, DirectiveEngine, DYNAMIC_REFERENCES, REFERENCE_SELECTORS
from src.runtime_config import RuntimeConfig


class _FakeChatResult:
    def __init__(self, text: str):
        self.text = text
        self.reasoning = ""
        self.stats = {}
        self.raw = {"output": []}


class _FakeClient:
    def __init__(self, text: str | None = None, failure: Exception | None = None):
        self.text = text
        self.failure = failure
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            raise self.failure
        return _FakeChatResult(self.text or "{}")


class V124DirectiveDeliberationTests(unittest.TestCase):
    def test_registry_and_reference_contract(self):
        ids = {item["id"] for item in DirectiveEngine.catalog()}
        self.assertEqual(COMMAND_REGISTRY_VERSION, "1.2.4a1")
        self.assertTrue({"intuition", "alternatives", "describe", "pov", "pace", "dia"} <= ids)
        self.assertIn("voice", REFERENCE_SELECTORS)
        self.assertIn("pov", DYNAMIC_REFERENCES)

    def test_typed_dialogue_directive(self):
        refs = [
            {"type": "entity_variant", "id": "V-FILA", "label": "Fila", "mode": "context"},
            {"type": "entity_variant", "id": "V-MIRA", "label": "Mira", "mode": "context"},
        ]
        result = DirectiveEngine.parse('/dia @Fila @Mira slow curve=wave "awkward apology"', explicit_references=refs)
        self.assertEqual(result.command["id"], "dia")
        self.assertEqual(result.planner_intent, "dialogue")
        self.assertEqual(result.options["pacing"], "slow")
        self.assertEqual(result.options["curve"], "wave")
        self.assertEqual(result.semantic_prompt, "awkward apology")
        self.assertEqual({x["id"] for x in result.resolved_references}, {"V-FILA", "V-MIRA"})

    def test_dynamic_references_resolve_at_request_time(self):
        scene = {"document_id": "DOC-1", "pov_variant_id": "V-POV", "location_variant_id": "V-ROOM", "participants": ["V-POV", "V-GUEST"]}
        result = DirectiveEngine.parse('/continue @scene @pov @cast @location', active_scene=scene, project_id="P", world_id="W", branch_id="B")
        pairs = {(x["type"], x["id"]) for x in result.resolved_references}
        self.assertIn(("document", "DOC-1"), pairs)
        self.assertIn(("entity_variant", "V-POV"), pairs)
        self.assertIn(("entity_variant", "V-GUEST"), pairs)
        self.assertIn(("entity_variant", "V-ROOM"), pairs)

    def test_named_selector_stays_on_stable_reference(self):
        refs = [{"type": "entity_variant", "id": "V-FILA", "label": "Fila", "mode": "context"}]
        result = DirectiveEngine.parse('/describe @Fila.voice', explicit_references=refs)
        matched = next(x for x in result.resolved_references if x["id"] == "V-FILA" and x.get("selector"))
        self.assertEqual(matched["selector"], "voice")

    def test_unresolved_reference_abstains_without_fake_id(self):
        result = DirectiveEngine.parse('/continue @DefinitelyNotACharacter')
        self.assertIn("@DefinitelyNotACharacter", result.unresolved_references)
        self.assertFalse(result.resolved_references)

    def test_dynamic_suggestions_are_virtual(self):
        rows = DirectiveEngine.dynamic_reference_suggestions("po", active_scene={"pov_variant_id": "V1"}, world_id="W", branch_id="B")
        self.assertEqual(rows[0]["id"], "pov")
        self.assertTrue(rows[0]["dynamic"])
        self.assertTrue(rows[0]["available"])

    def test_planner_obeys_directive_intent_and_selector(self):
        class Scope:
            explicit_references = [{"type": "entity_variant", "id": "V1", "label": "Fila", "selector": "voice"}]
            pov_variant_id = None
            world_time = None
            story_order = None
            token_budget = 1500
            context_lens = "scene"
            allow_future_author_knowledge = False
        ws = SimpleNamespace(
            scope={"directive": {
                "planner_intent": "deliberate",
                "resolved_references": [{"type": "entity_variant", "id": "V1", "label": "Fila", "selector": "voice"}],
                "dynamic_scopes": [],
            }}, auto_selected=[], explicit_references=[],
        )
        plan = NarrativeContextPlanner().plan("next?", Scope(), workspace_context=ws, route="STORY_CONTINUE")
        self.assertEqual(plan.intent, "deliberate")
        self.assertGreaterEqual(plan.dimensions["relationships"], 0.8)
        self.assertTrue(any(x.get("selector") == "voice" for x in plan.focus_resources))

    def _config(self, root: Path) -> RuntimeConfig:
        cfg = root / "arline.toml"
        (root / "writer_system.txt").write_text("write", encoding="utf-8")
        (root / "reasoning_guard.txt").write_text("guard", encoding="utf-8")
        cfg.write_text('''[lmstudio]\nbase_url="http://127.0.0.1:1"\nmodel="fake-model"\napi_key=""\nauto_load=false\n[writer]\nsystem_prompt_file="writer_system.txt"\n[reasoning_runtime]\nguard_prompt_file="reasoning_guard.txt"\n[deliberation]\nenabled=true\nmax_tokens=500\ntemperature=0.2\nalternatives=3\ncontext_chars=8000\n''', encoding="utf-8")
        return RuntimeConfig.load(cfg)

    def test_model_deliberation_is_soft_noncanon(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self._config(Path(td))
            client = _FakeClient('{"scene_goal":"defuse tension","likely_beats":["Fila hesitates"],"character_intentions":["Mira wants clarity"],"emotional_trajectories":["tension softens"],"opportunities":["use silence"],"alternatives":["Mira changes topic"],"uncertainties":["reason for anger is unknown"],"constraints":["do not reveal secret"]}')
            out = NarrativeDeliberator(cfg).deliberate(client=client, model="fake-model", directive={"planner_intent":"dialogue","output_mode":"fiction","semantic_prompt":"apology"}, context_plan={"intent":"dialogue"}, workspace_text="trusted", wcf_text="LOCKED", narrative_brief="brief")
            self.assertEqual(out.status, "model")
            self.assertIn("soft_non_canon", out.render())
            self.assertIn("canon_commit: forbidden", out.render())
            self.assertEqual(out.likely_beats, ["Fila hesitates"])

    def test_deliberation_failure_fails_soft(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self._config(Path(td))
            out = NarrativeDeliberator(cfg).deliberate(client=_FakeClient(failure=RuntimeError("offline")), model="fake-model", directive={"planner_intent":"continue","output_mode":"fiction","semantic_prompt":"continue"}, context_plan={}, workspace_text="", wcf_text="", narrative_brief="")
            self.assertEqual(out.status, "fallback")
            self.assertTrue(out.uncertainties)

    def test_source_integration_contracts(self):
        service = Path("src/service/arline_service.py").read_text(encoding="utf-8")
        streaming = Path("src/service/streaming.py").read_text(encoding="utf-8")
        rails = Path("src/service/v121_rails.py").read_text(encoding="utf-8")
        app = Path("src/interface/web/app.py").read_text(encoding="utf-8")
        self.assertIn("<NARRATIVE_DELIBERATION>", service)
        self.assertIn("self.deliberator.deliberate", service)
        self.assertIn("deliberation=deliberation", service)
        self.assertIn("deliberation=deliberation", rails)
        self.assertIn("deliberation = await asyncio.to_thread", streaming)
        self.assertIn('"command_registry_version"', app)
        self.assertIn('"reference_selectors"', app)

    def test_frontend_has_remote_commands_dynamic_refs_and_intuition_panel(self):
        js = Path("src/interface/web/static/arline.js").read_text(encoding="utf-8")
        html = Path("src/interface/web/static/index.html").read_text(encoding="utf-8")
        commands = Path("src/interface/web/static/js/commands.js").read_text(encoding="utf-8")
        self.assertIn("loadCommandRegistry", js)
        self.assertIn("referenceSelectors", js)
        self.assertIn("item.dynamic", js)
        self.assertIn("deliberationOutput", html)
        self.assertIn('/intuition', commands)
        self.assertIn('/alternatives', commands)
'''

DOC = r'''# v1.2.4 — Narrative Directives, Semantic References & Deliberation

v1.2.4 adds one top-down control/intelligence layer above v1.2.3 context planning.

```text
user input
  ├─ / typed directive     = explicit user intent
  ├─ @ semantic reference = explicit grounding
  └─ prose                 = semantic request
        ↓
DirectiveEngine
        ↓
NarrativeContextPlanner
        ↓
Memory / Continuity / ScopeGate
        ↓
authoritative writer context
        ↓
NarrativeDeliberator       = soft possibilities, never authority
        ↓
Writer                     = realization
```

## Authority rule

- `/` changes what the user is asking Arline to do. It is not a story fact.
- `@` binds a stable or dynamic story resource into the request. It does not change Canon.
- Context/Continuity decide what evidence is allowed and what is currently derivable.
- Deliberation proposes plausible beats, intentions, emotional motion, opportunities, alternatives, and uncertainty.
- Deliberation is explicitly `soft_non_canon` and cannot resolve UNKNOWN/conflicts or create character knowledge.
- Only accepted/reviewed story/world workflows may later change authoritative state.

## Reference expressions

Stable references may be selector-qualified:

`@Fila.voice`, `@Fila.state`, `@Fila.appearance`, `@Fila.knowledge`, `@Fila.beliefs`, `@Fila.relationships`, `@Fila.timeline`, `@Fila.evidence`, `@Fila.conflicts`.

Dynamic references are resolved on every request rather than persisted as stale IDs:

`@scene`, `@pov`, `@location`, `@cast`, `@world`, `@branch`, `@threads`, `@recent`.

## Deliberation commands

`/intuition` exposes author-facing narrative intuition. `/alternatives` asks for several possible next beats. Normal writing commands use the same deliberation internally before prose realization.

The same selected local LM Studio writer model performs deliberation using a bounded JSON-only call. Deliberation failure is fail-soft: generation continues with conservative context-only guidance.
'''

write("src/directives/engine.py", DIRECTIVES)
write("src/directives/__init__.py", DIRECTIVES_INIT)
write("src/deliberation/engine.py", DELIBERATION)
write("src/deliberation/__init__.py", DELIBERATION_INIT)
write("tests/test_v124_directives_deliberation.py", TESTS)
write("docs/V124_DIRECTIVES_DELIBERATION.md", DOC)

# Version contract.
replace_once("src/version.py", '__version__ = "1.2.3a1"', f'__version__ = "{VERSION}"')
replace_once("pyproject.toml", 'version = "1.2.3a1"', f'version = "{VERSION}"')
replace_once("uv.lock", 'version = "1.2.3a1"', f'version = "{VERSION}"')

# Runtime configuration: add a bounded deliberation profile without breaking positional RuntimeConfig construction.
path = "src/runtime_config.py"
text = read(path)
anchor = '''@dataclass(slots=True)\nclass ArtifactConfig:\n'''
insert = '''@dataclass(slots=True)\nclass DeliberationConfig:\n    enabled: bool = True\n    max_tokens: int = 700\n    temperature: float = 0.35\n    alternatives: int = 3\n    context_chars: int = 24000\n\n\n'''
if insert not in text:
    if anchor not in text: raise SystemExit("runtime DeliberationConfig anchor missing")
    text = text.replace(anchor, insert + anchor, 1)
old = '''    workspace: WorkspaceConfig\n    ui: UIConfig\n'''
new = '''    workspace: WorkspaceConfig\n    ui: UIConfig\n    deliberation: DeliberationConfig = field(default_factory=DeliberationConfig)\n'''
if old not in text: raise SystemExit("RuntimeConfig field anchor missing")
text = text.replace(old, new, 1)
old = '''        ws = raw.get("workspace", {})\n        ui = raw.get("ui", {})\n'''
new = '''        ws = raw.get("workspace", {})\n        ui = raw.get("ui", {})\n        deli = raw.get("deliberation", {})\n'''
if old not in text: raise SystemExit("runtime raw sections anchor missing")
text = text.replace(old, new, 1)
old = '''            ui=UIConfig(\n                host=str(ui.get("host", "127.0.0.1")),\n                port=int(ui.get("port", 7860)),\n                show_reasoning=bool(ui.get("show_reasoning", True)),\n            ),\n        )\n'''
new = '''            ui=UIConfig(\n                host=str(ui.get("host", "127.0.0.1")),\n                port=int(ui.get("port", 7860)),\n                show_reasoning=bool(ui.get("show_reasoning", True)),\n            ),\n            deliberation=DeliberationConfig(\n                enabled=bool(deli.get("enabled", True)),\n                max_tokens=max(128, int(deli.get("max_tokens", 700))),\n                temperature=max(0.0, min(2.0, float(deli.get("temperature", 0.35)))),\n                alternatives=max(1, min(8, int(deli.get("alternatives", 3)))),\n                context_chars=max(4000, int(deli.get("context_chars", 24000))),\n            ),\n        )\n'''
if old not in text: raise SystemExit("runtime load constructor anchor missing")
text = text.replace(old, new, 1)
old = '''            "context_budget", "reasoning_budget", "projection", "reasoning_runtime", "artifacts", "history", "workspace", "ui",\n'''
new = '''            "context_budget", "reasoning_budget", "projection", "reasoning_runtime", "artifacts", "history", "workspace", "ui", "deliberation",\n'''
if old not in text: raise SystemExit("runtime save sections anchor missing")
text = text.replace(old, new, 1)
anchor = '''        doc["projection"].update({\n'''
block = '''        doc["deliberation"].update({\n            "enabled": self.deliberation.enabled,\n            "max_tokens": self.deliberation.max_tokens,\n            "temperature": self.deliberation.temperature,\n            "alternatives": self.deliberation.alternatives,\n            "context_chars": self.deliberation.context_chars,\n        })\n'''
if block not in text:
    if anchor not in text: raise SystemExit("runtime save deliberation anchor missing")
    text = text.replace(anchor, block + anchor, 1)
write(path, text)

cfg = read("config/arline.toml")
if "[deliberation]" not in cfg:
    cfg += '''\n\n[deliberation]\n# Soft model intuition after authoritative context assembly and before prose.\n# It never writes Canon and fails soft when the local model is unavailable.\nenabled = true\nmax_tokens = 700\ntemperature = 0.35\nalternatives = 3\ncontext_chars = 24000\n'''
write("config/arline.toml", cfg)

# v1.2.3 planner becomes directive/selector aware while staying deterministic.
path = "src/context/intelligence.py"
text = read(path)
text = text.replace('CONTEXT_INTELLIGENCE_VERSION = "1.2.3a1"', f'CONTEXT_INTELLIGENCE_VERSION = "{VERSION}"', 1)
old = '''    BRANCH_COMPARE = "branch_compare"\n'''
new = '''    BRANCH_COMPARE = "branch_compare"\n    DELIBERATE = "deliberate"\n'''
if old not in text: raise SystemExit("intent enum anchor missing")
text = text.replace(old, new, 1)
old = '''        def add(typ: str, rid: Any, reason: str, label: str | None = None) -> None:\n'''
new = '''        def add(typ: str, rid: Any, reason: str, label: str | None = None, selector: str | None = None) -> None:\n'''
if old not in text: raise SystemExit("planner focus add anchor missing")
text = text.replace(old, new, 1)
old = '''                "confidence": 1.0,\n            })\n\n        for ref in list(getattr(scope, "explicit_references", []) or []):\n            add(str(ref.get("type") or ""), ref.get("id"), "explicit reference", str(ref.get("label") or "") or None)\n'''
new = '''                "confidence": 1.0,\n                **({"selector": selector} if selector else {}),\n            })\n\n        for ref in list(getattr(scope, "explicit_references", []) or []):\n            add(str(ref.get("type") or ""), ref.get("id"), "explicit reference", str(ref.get("label") or "") or None, str(ref.get("selector") or "") or None)\n        directive = dict(ws_scope.get("directive") or {})\n        for ref in list(directive.get("resolved_references") or []):\n            add(str(ref.get("type") or ""), ref.get("id"), "directive grounding", str(ref.get("label") or "") or None, str(ref.get("selector") or "") or None)\n'''
if old not in text: raise SystemExit("planner explicit ref anchor missing")
text = text.replace(old, new, 1)
old = '''            NarrativeIntent.BRANCH_COMPARE: dict(continuity=1.00, state=.92, relationships=.68, events=.82, spatial=.42, threads=.38, pov=.35, source=.28),\n'''
new = '''            NarrativeIntent.BRANCH_COMPARE: dict(continuity=1.00, state=.92, relationships=.68, events=.82, spatial=.42, threads=.38, pov=.35, source=.28),\n            NarrativeIntent.DELIBERATE: dict(continuity=1.00, state=.92, relationships=.90, events=.90, spatial=.60, threads=.82, pov=.90, source=.38),\n'''
if old not in text: raise SystemExit("planner dimension table anchor missing")
text = text.replace(old, new, 1)
old = '''        route_value = self._route_value(route)\n        intent = self._intent(prompt, route_value)\n        focus, anchors = self._focus_resources(scope, workspace_context)\n'''
new = '''        route_value = self._route_value(route)\n        ws_scope = self._workspace_scope(workspace_context)\n        directive = dict(ws_scope.get("directive") or {})\n        directive_intent = str(directive.get("planner_intent") or "").strip()\n        try:\n            intent = NarrativeIntent(directive_intent) if directive_intent else self._intent(prompt, route_value)\n        except ValueError:\n            intent = self._intent(prompt, route_value)\n        focus, anchors = self._focus_resources(scope, workspace_context)\n'''
if old not in text: raise SystemExit("planner intent anchor missing")
text = text.replace(old, new, 1)
old = '''        if not anchors.get("participants") and len([x for x in focus if x["type"] == "entity_variant"]) < 2:\n            dimensions["relationships"] *= .74\n\n        lane_weights: dict[str, float] = {}\n'''
new = '''        if not anchors.get("participants") and len([x for x in focus if x["type"] == "entity_variant"]) < 2:\n            dimensions["relationships"] *= .74\n\n        selectors = {str(item.get("selector") or "").casefold() for item in focus if item.get("selector")}\n        if "voice" in selectors:\n            dimensions["pov"] = max(dimensions["pov"], .92)\n            dimensions["relationships"] = max(dimensions["relationships"], .84)\n            dimensions["state"] = max(dimensions["state"], .78)\n        if selectors & {"state", "appearance"}:\n            dimensions["state"] = max(dimensions["state"], 1.0)\n        if selectors & {"knowledge", "beliefs"}:\n            dimensions["pov"] = max(dimensions["pov"], 1.0)\n        if "relationships" in selectors:\n            dimensions["relationships"] = 1.0\n        if "timeline" in selectors:\n            dimensions["events"] = max(dimensions["events"], 1.0)\n            dimensions["continuity"] = max(dimensions["continuity"], .92)\n        if "evidence" in selectors:\n            dimensions["source"] = 1.0\n        if "conflicts" in selectors:\n            dimensions["continuity"] = 1.0\n\n        lane_weights: dict[str, float] = {}\n'''
if old not in text: raise SystemExit("planner selector anchor missing")
text = text.replace(old, new, 1)
old = '''                "fuzzy_identity_merge": False,\n            },\n'''
new = '''                "fuzzy_identity_merge": False,\n                "directive_version": directive.get("version"),\n                "reference_selectors": sorted(selectors),\n                "dynamic_scopes": list(directive.get("dynamic_scopes") or []),\n            },\n'''
if old not in text: raise SystemExit("planner policies anchor missing")
text = text.replace(old, new, 1)
write(path, text)

# Memory compiler carries selectors and structured retrieval honors selected character sections.
path = "src/memory/query.py"
text = read(path)
old = '''                resolved.append({"type": key[0], "id": key[1], "label": ref.get("label") or key[1], "method": "explicit", "confidence": 1.0})\n'''
new = '''                resolved.append({"type": key[0], "id": key[1], "label": ref.get("label") or key[1], "method": "explicit", "confidence": 1.0, **({"selector": ref.get("selector")} if ref.get("selector") else {})})\n'''
if old not in text: raise SystemExit("query explicit selector anchor missing")
text = text.replace(old, new, 1)
old = '''                "method": "context_plan", "confidence": float(focus.get("confidence") or 1.0),\n            })\n'''
new = '''                "method": "context_plan", "confidence": float(focus.get("confidence") or 1.0),\n                **({"selector": focus.get("selector")} if focus.get("selector") else {}),\n            })\n'''
if old not in text: raise SystemExit("query focus selector anchor missing")
text = text.replace(old, new, 1)
old = '''    def _structured_state(self, plan: QueryPlan, lane: RetrievalLane) -> list[MemoryCandidate]:\n        if not plan.scope.world_id:\n            return []\n        output: list[MemoryCandidate] = []\n        for variant in self._variant_targets(plan):\n            rows = self.store.query_current_state(plan.scope.world_id, plan.scope.branch_id, "entity_variant", variant["id"])\n            if not rows:\n                current = variant.get("current_state") or {}\n                attributes = variant.get("attributes") or {}\n                rows = [\n                    {"state_key": key, "value": value, "source_type": "entity_variant", "source_id": variant["id"], "authority": Authority.USER_ACCEPTED_WORLD_CANON.value}\n                    for key, value in {**attributes, **current}.items()\n                ]\n'''
new = '''    @staticmethod\n    def _selector_for_variant(plan: QueryPlan, variant: dict[str, Any]) -> str | None:\n        for item in plan.resolved_entities:\n            selector = str(item.get("selector") or "").strip().casefold()\n            if not selector:\n                continue\n            if item.get("type") == "entity_variant" and item.get("id") == variant.get("id"):\n                return selector\n            if item.get("type") == "entity_family" and item.get("id") == variant.get("family_id"):\n                return selector\n        return None\n\n    def _structured_state(self, plan: QueryPlan, lane: RetrievalLane) -> list[MemoryCandidate]:\n        if not plan.scope.world_id:\n            return []\n        output: list[MemoryCandidate] = []\n        for variant in self._variant_targets(plan):\n            selector = self._selector_for_variant(plan, variant)\n            rows = self.store.query_current_state(plan.scope.world_id, plan.scope.branch_id, "entity_variant", variant["id"])\n            current = variant.get("current_state") or {}\n            attributes = variant.get("attributes") or {}\n            selected_section: dict[str, Any] | None = None\n            if selector == "voice":\n                selected_section = variant.get("voice") or {}\n            elif selector == "knowledge":\n                selected_section = variant.get("knowledge") or {}\n            elif selector == "beliefs":\n                selected_section = variant.get("beliefs") or {}\n            elif selector == "state":\n                selected_section = current\n            elif selector == "appearance":\n                merged = {**attributes, **current}\n                appearance_words = ("appearance", "hair", "face", "skin", "eye", "height", "body", "chest", "clothing", "outfit", "physical", "form", "voice")\n                filtered = {k: v for k, v in merged.items() if any(word in str(k).casefold() for word in appearance_words)}\n                selected_section = filtered or merged\n            if selected_section is not None:\n                rows = [\n                    {"state_key": f"{selector}.{key}", "value": value, "source_type": "entity_variant", "source_id": variant["id"], "authority": Authority.USER_ACCEPTED_WORLD_CANON.value}\n                    for key, value in selected_section.items()\n                ]\n            elif not rows:\n                rows = [\n                    {"state_key": key, "value": value, "source_type": "entity_variant", "source_id": variant["id"], "authority": Authority.USER_ACCEPTED_WORLD_CANON.value}\n                    for key, value in {**attributes, **current}.items()\n                ]\n'''
if old not in text: raise SystemExit("structured selector anchor missing")
text = text.replace(old, new, 1)
write(path, text)

# ArlineService: parse directives deterministically, reserve deliberation budget, run intuition after hard context validation, then pass it to writer.
path = "src/service/arline_service.py"
text = read(path)
old = '''from src.runtime_config import RuntimeConfig\nfrom src.writer import ArlineWriter, PostWriteValidator\n'''
new = '''from src.runtime_config import RuntimeConfig\nfrom src.directives import DirectiveEngine, DirectiveIntent\nfrom src.deliberation import NarrativeDeliberation, NarrativeDeliberator\nfrom src.writer import ArlineWriter, PostWriteValidator\n'''
if old not in text: raise SystemExit("service imports anchor missing")
text = text.replace(old, new, 1)
old = '''    narrative_brief: Any\n    workspace_context: WorkspaceContext | None = None\n'''
new = '''    narrative_brief: Any\n    workspace_context: WorkspaceContext | None = None\n    directive: DirectiveIntent | None = None\n'''
if old not in text: raise SystemExit("AnalysisBundle anchor missing")
text = text.replace(old, new, 1)
old = '''    model_input: str\n    load_status: dict[str, Any]\n'''
new = '''    model_input: str\n    load_status: dict[str, Any]\n    deliberation: NarrativeDeliberation | None = None\n'''
if old not in text: raise SystemExit("GenerationBundle anchor missing")
text = text.replace(old, new, 1)
old = '''        self.post_validator = PostWriteValidator()\n        self.projection_engine = ProjectionEngine(\n'''
new = '''        self.post_validator = PostWriteValidator()\n        self.directive_engine = DirectiveEngine()\n        self.deliberator = NarrativeDeliberator(config)\n        self.projection_engine = ProjectionEngine(\n'''
if old not in text: raise SystemExit("service init anchor missing")
text = text.replace(old, new, 1)
anchor = '''    def analyze(\n        self,\n        prompt: str,\n'''
helper = '''    def _directive_for(self, prompt: str, workspace_context: WorkspaceContext | None) -> DirectiveIntent:\n        scope = dict(getattr(workspace_context, "scope", {}) or {}) if workspace_context else {}\n        cached = scope.get("directive")\n        if isinstance(cached, dict) and cached.get("version") == "1.2.4a1" and cached.get("raw_prompt") == prompt:\n            return DirectiveIntent(**{key: value for key, value in cached.items() if key in DirectiveIntent.__dataclass_fields__})\n        refs = list(getattr(workspace_context, "explicit_references", []) or []) if workspace_context else []\n        active = dict(scope.get("active_scene") or {})\n        directive = self.directive_engine.parse(\n            prompt, explicit_references=refs, active_scene=active,\n            project_id=scope.get("project_id"), world_id=scope.get("world_id"), branch_id=scope.get("branch_id"),\n        )\n        if workspace_context is not None:\n            workspace_context.scope["directive"] = directive.to_dict()\n        return directive\n\n    def _build_deliberation(self, prompt: str, bundle: AnalysisBundle, client) -> NarrativeDeliberation:\n        directive = bundle.directive or self._directive_for(prompt, bundle.workspace_context)\n        context_plan = dict(getattr(bundle.workspace_context, "scope", {}).get("context_intelligence") or {}) if bundle.workspace_context else {}\n        result = self.deliberator.deliberate(\n            client=client, model=self.config.lmstudio.model, directive=directive.to_dict(), context_plan=context_plan,\n            workspace_text=bundle.workspace_context.text if bundle.workspace_context else "",\n            wcf_text=bundle.rendered_context.text,\n            narrative_brief=bundle.narrative_brief.text if bundle.narrative_brief else "",\n        )\n        if bundle.workspace_context is not None:\n            bundle.workspace_context.scope["deliberation"] = result.to_dict()\n        return result\n\n'''
if helper not in text:
    if anchor not in text: raise SystemExit("service analyze anchor missing")
    text = text.replace(anchor, helper + anchor, 1)
old = '''    ) -> AnalysisBundle:\n        result = self.pipeline.run(prompt, surface_history=surface_history)\n        core = self.core_builder.build(result)\n        narrative = self.narrative_builder.build(\n            prompt, result, surface_history=surface_history\n        )\n'''
new = '''    ) -> AnalysisBundle:\n        directive = self._directive_for(prompt, workspace_context)\n        analysis_prompt = directive.semantic_prompt if directive.command else prompt\n        result = self.pipeline.run(analysis_prompt, surface_history=surface_history)\n        core = self.core_builder.build(result)\n        narrative = self.narrative_builder.build(\n            analysis_prompt, result, surface_history=surface_history\n        )\n'''
if old not in text: raise SystemExit("service analyze prompt anchor missing")
text = text.replace(old, new, 1)
old = '''        ctx = self.context_builder.build(\n            prompt, core, result, narrative, projections=projections\n        )\n'''
new = '''        ctx = self.context_builder.build(\n            analysis_prompt, core, result, narrative, projections=projections\n        )\n'''
if old not in text: raise SystemExit("service context build anchor missing")
text = text.replace(old, new, 1)
old = '''            system_prompt_tokens=self.config.context_budget.system_prompt_token_estimate,\n'''
new = '''            system_prompt_tokens=self.config.context_budget.system_prompt_token_estimate + (self.config.deliberation.max_tokens if self.config.deliberation.enabled else 0),\n'''
if old not in text: raise SystemExit("service heuristic budget anchor missing")
text = text.replace(old, new, 1)
old = '''            result, core, world_runtime, narrative, ctx, rendered, validation,\n            aif, brief, workspace_context\n        )\n'''
new = '''            result, core, world_runtime, narrative, ctx, rendered, validation,\n            aif, brief, workspace_context, directive\n        )\n'''
if old not in text: raise SystemExit("AnalysisBundle return anchor missing")
text = text.replace(old, new, 1)
old = '''        session_context: str | None = None,\n        beat_context: str | None = None,\n    ) -> str:\n'''
new = '''        session_context: str | None = None,\n        beat_context: str | None = None,\n        deliberation: NarrativeDeliberation | None = None,\n    ) -> str:\n'''
if old not in text: raise SystemExit("compose signature anchor missing")
text = text.replace(old, new, 1)
old = '''        parts += [\n            "<ARLINE_CONTEXT>",\n            bundle.rendered_context.text.rstrip(),\n            "</ARLINE_CONTEXT>",\n            "",\n            "<REQUEST>",\n'''
new = '''        parts += [\n            "<ARLINE_CONTEXT>",\n            bundle.rendered_context.text.rstrip(),\n            "</ARLINE_CONTEXT>",\n            "",\n        ]\n        if bundle.directive and bundle.directive.active:\n            parts += ["<DIRECTIVE>", bundle.directive.render().rstrip(), "</DIRECTIVE>", ""]\n        if deliberation is not None:\n            parts += ["<NARRATIVE_DELIBERATION>", deliberation.render().rstrip(), "</NARRATIVE_DELIBERATION>", ""]\n        parts += [\n            "<REQUEST>",\n'''
if old not in text: raise SystemExit("compose context block anchor missing")
text = text.replace(old, new, 1)
old = '''        parts += [\n            "",\n            "<WRITE>",\n            "Write the requested fiction using the structured context.",\n            "</WRITE>",\n        ]\n'''
new = '''        output_mode = deliberation.output_mode if deliberation is not None else (bundle.directive.output_mode if bundle.directive else "fiction")\n        write_instruction = "Write the requested fiction using the structured context."\n        if output_mode == "author_intuition":\n            write_instruction = "Respond to the author with concise narrative intuition, likely beats, and explicit uncertainty. Do not write story prose unless specifically requested."\n        elif output_mode == "author_alternatives":\n            write_instruction = "Respond to the author with distinct plausible next-beat alternatives and tradeoffs. Keep them non-canonical and do not silently choose one."\n        parts += [\n            "",\n            "<WRITE>",\n            write_instruction,\n            "</WRITE>",\n        ]\n'''
if old not in text: raise SystemExit("compose write instruction anchor missing")
text = text.replace(old, new, 1)
# Reserve exact writer space for the deliberation block.
text = text.replace('system_prompt_tokens=exact_counter.count(system_text),', 'system_prompt_tokens=exact_counter.count(system_text) + (self.config.deliberation.max_tokens if self.config.deliberation.enabled else 0),', 1)
old = '''        model_input = self.compose_model_input(\n            prompt,\n            bundle,\n            mode,\n            session_context=session_context,\n            beat_context=beat_context,\n        )\n'''
new = '''        deliberation = self._build_deliberation(prompt, bundle, client)\n        model_input = self.compose_model_input(\n            prompt,\n            bundle,\n            mode,\n            session_context=session_context,\n            beat_context=beat_context,\n            deliberation=deliberation,\n        )\n'''
if old not in text: raise SystemExit("generate compose anchor missing")
text = text.replace(old, new, 1)
old = '''        post = (\n            self.post_validator.validate(result.story, bundle.writer_context)\n'''
new = '''        result.stats["deliberation_version"] = deliberation.version\n        result.stats["deliberation_status"] = deliberation.status\n        result.stats["deliberation_model"] = deliberation.model\n        post = (\n            self.post_validator.validate(result.story, bundle.writer_context)\n'''
if old not in text: raise SystemExit("generate stats anchor missing")
text = text.replace(old, new, 1)
old = '''            model_input,\n            load,\n        )\n\n    def generate_beats(\n'''
new = '''            model_input,\n            load,\n            deliberation,\n        )\n\n    def generate_beats(\n'''
if old not in text: raise SystemExit("GenerationBundle single anchor missing")
text = text.replace(old, new, 1)
old = '''        effective_reasoning = self.resolve_reasoning_mode()\n        writer = ArlineWriter(self.config, client=client)\n\n        old_visible = self.config.generation.visible_output_tokens\n'''
new = '''        effective_reasoning = self.resolve_reasoning_mode()\n        deliberation = self._build_deliberation(prompt, bundle, client)\n        writer = ArlineWriter(self.config, client=client)\n\n        old_visible = self.config.generation.visible_output_tokens\n'''
if old not in text: raise SystemExit("beats deliberation anchor missing")
text = text.replace(old, new, 1)
old = '''                    beat_context=beat_instruction,\n                )\n'''
new = '''                    beat_context=beat_instruction,\n                    deliberation=deliberation,\n                )\n'''
if old not in text: raise SystemExit("beats compose anchor missing")
text = text.replace(old, new, 1)
old = '''            self.compose_model_input(\n                prompt, bundle, mode, session_context=session_context\n            ),\n            load,\n        )\n'''
new = '''            self.compose_model_input(\n                prompt, bundle, mode, session_context=session_context, deliberation=deliberation\n            ),\n            load,\n            deliberation,\n        )\n'''
if old not in text: raise SystemExit("beats final bundle anchor missing")
text = text.replace(old, new, 1)
# Save soft deliberation as an artifact for debugging, never as Canon.
old = '''            ("workspace_context.json", bundle.analysis.workspace_context.to_dict() if bundle.analysis.workspace_context else {}),\n            ("writer_context.json", bundle.analysis.writer_context.to_dict()),\n'''
new = '''            ("workspace_context.json", bundle.analysis.workspace_context.to_dict() if bundle.analysis.workspace_context else {}),\n            ("deliberation.json", bundle.deliberation.to_dict() if bundle.deliberation else {}),\n            ("writer_context.json", bundle.analysis.writer_context.to_dict()),\n'''
if old not in text: raise SystemExit("save deliberation artifact anchor missing")
text = text.replace(old, new, 1)
write(path, text)

# Character Rails wrapper forwards deliberation instead of swallowing the new keyword.
path = "src/service/v121_rails.py"
text = read(path)
old = '''    session_context: str | None = None,\n    beat_context: str | None = None,\n) -> str:\n'''
new = '''    session_context: str | None = None,\n    beat_context: str | None = None,\n    deliberation=None,\n) -> str:\n'''
if old not in text: raise SystemExit("v121 compose signature anchor missing")
text = text.replace(old, new, 1)
old = '''        session_context=clean_session,\n        beat_context=beat_context,\n    )\n'''
new = '''        session_context=clean_session,\n        beat_context=beat_context,\n        deliberation=deliberation,\n    )\n'''
if old not in text: raise SystemExit("v121 deliberation forward anchor missing")
text = text.replace(old, new, 1)
write(path, text)

# Streaming runs the same single bounded deliberation call after exact validation and before model_input.
path = "src/service/streaming.py"
text = read(path)
old = '''from src.service.arline_service import AnalysisBundle, ArlineService, GenerationBundle\n'''
new = '''from src.service.arline_service import AnalysisBundle, ArlineService, GenerationBundle\nfrom src.deliberation import NarrativeDeliberation\n'''
if old not in text: raise SystemExit("streaming import anchor missing")
text = text.replace(old, new, 1)
old = '''    system_prompt: str\n'''
new = '''    system_prompt: str\n    deliberation: NarrativeDeliberation\n'''
if old not in text: raise SystemExit("PreparedStreamingGeneration anchor missing")
text = text.replace(old, new, 1)
text = text.replace('system_prompt_tokens=exact_counter.count(system_text),', 'system_prompt_tokens=exact_counter.count(system_text) + (self.config.deliberation.max_tokens if self.config.deliberation.enabled else 0),', 1)
old = '''        model_input = self.base.compose_model_input(\n            prompt,\n            analysis,\n            mode,\n            session_context=session_context,\n            beat_context=beat_context,\n        )\n'''
new = '''        deliberation = await asyncio.to_thread(self.base._build_deliberation, prompt, analysis, client)\n        model_input = self.base.compose_model_input(\n            prompt,\n            analysis,\n            mode,\n            session_context=session_context,\n            beat_context=beat_context,\n            deliberation=deliberation,\n        )\n'''
if old not in text: raise SystemExit("streaming compose anchor missing")
text = text.replace(old, new, 1)
old = '''            load_status=load,\n            system_prompt=system_text,\n        )\n'''
new = '''            load_status=load,\n            system_prompt=system_text,\n            deliberation=deliberation,\n        )\n'''
if old not in text: raise SystemExit("streaming prepared return anchor missing")
text = text.replace(old, new, 1)
old = '''            prepared.model_input,\n            prepared.load_status,\n        )\n'''
new = '''            prepared.model_input,\n            prepared.load_status,\n            prepared.deliberation,\n        )\n'''
if old not in text: raise SystemExit("streaming final GenerationBundle anchor missing")
text = text.replace(old, new, 1)
write(path, text)

# App/API: selector-bearing references, dynamic mention suggestions, semantic command registry, and directive-enriched memory query.
path = "src/interface/web/app.py"
text = read(path)
old = '''from src.version import __version__\nfrom src.memory.web import create_memory_router\n'''
new = '''from src.version import __version__\nfrom src.directives import COMMAND_REGISTRY_VERSION, DYNAMIC_REFERENCES, REFERENCE_SELECTORS, DirectiveEngine\nfrom src.memory.web import create_memory_router\n'''
if old not in text: raise SystemExit("app directive import anchor missing")
text = text.replace(old, new, 1)
old = '''class ReferencePayload(BaseModel):\n    type: str\n    id: str\n    label: str = ""\n    mode: str = "context"\n'''
new = '''class ReferencePayload(BaseModel):\n    type: str\n    id: str\n    label: str = ""\n    mode: str = "context"\n    selector: str | None = None\n'''
if old not in text: raise SystemExit("ReferencePayload anchor missing")
text = text.replace(old, new, 1)
old = '''        active_scene = (ws_context.scope.get("active_scene") or {}) if ws_context else {}\n        lens = str(payload.context_lens or memory_config.default_lens or "scene").lower()\n'''
new = '''        active_scene = (ws_context.scope.get("active_scene") or {}) if ws_context else {}\n        directive = DirectiveEngine.parse(\n            prompt, explicit_references=refs, active_scene=active_scene,\n            project_id=project_id, world_id=world_id, branch_id=branch_id,\n        )\n        ws_context.scope["directive"] = directive.to_dict()\n        memory_refs = directive.resolved_references or refs\n        memory_query = directive.semantic_prompt or prompt\n        lens = str(payload.context_lens or memory_config.default_lens or "scene").lower()\n'''
if old not in text: raise SystemExit("app augment directive anchor missing")
text = text.replace(old, new, 1)
old = '''            explicit_references=refs,\n'''
new = '''            explicit_references=memory_refs,\n'''
# only first occurrence in helper after insertion.
if old not in text: raise SystemExit("app memory refs anchor missing")
text = text.replace(old, new, 1)
old = '''            result = memory_service.retrieve(prompt, memory_scope, workspace_context=ws_context)\n'''
new = '''            result = memory_service.retrieve(memory_query, memory_scope, workspace_context=ws_context)\n'''
if old not in text: raise SystemExit("app memory query anchor missing")
text = text.replace(old, new, 1)
old = '''    @app.get("/api/config")\n    def get_config():\n        return _public_config(RuntimeConfig.load(config_path))\n\n'''
new = '''    @app.get("/api/config")\n    def get_config():\n        return _public_config(RuntimeConfig.load(config_path))\n\n    @app.post("/api/directives/parse")\n    def parse_directive(payload: PromptPayload):\n        refs = [item.model_dump() for item in payload.references]\n        active_scene = workspace.get_active_scene(payload.project_id) if payload.project_id else {}\n        return DirectiveEngine.parse(\n            payload.prompt, explicit_references=refs, active_scene=active_scene or {},\n            project_id=payload.project_id, world_id=payload.world_id, branch_id=payload.branch_id,\n        ).to_dict()\n\n'''
if old not in text: raise SystemExit("app config endpoint anchor missing")
text = text.replace(old, new, 1)
old = '''        raw_results = workspace.search_mentions(\n            q, project_id=project_id, world_id=world_id,\n            branch_id=branch_id, limit=limit,\n        )\n        results = []\n'''
new = '''        active_scene = workspace.get_active_scene(project_id) if project_id else {}\n        dynamic_results = DirectiveEngine.dynamic_reference_suggestions(\n            q, active_scene=active_scene or {}, world_id=world_id, branch_id=branch_id,\n        )\n        raw_results = workspace.search_mentions(\n            q.split(".", 1)[0], project_id=project_id, world_id=world_id,\n            branch_id=branch_id, limit=limit,\n        )\n        results = list(dynamic_results)\n'''
if old not in text: raise SystemExit("mentions dynamic anchor missing")
text = text.replace(old, new, 1)
old = '''    @app.get("/api/commands")\n    def commands(q: str = Query(""), project_id: str | None = Query(None)):\n        return {"results": workspace.command_search(q, project_id=project_id)}\n'''
new = '''    @app.get("/api/commands")\n    def commands(q: str = Query(""), project_id: str | None = Query(None)):\n        return {\n            "results": workspace.command_search(q, project_id=project_id),\n            "command_registry_version": COMMAND_REGISTRY_VERSION,\n            "commands": DirectiveEngine.catalog(),\n            "reference_selectors": list(REFERENCE_SELECTORS),\n            "dynamic_references": list(DYNAMIC_REFERENCES),\n        }\n'''
if old not in text: raise SystemExit("commands endpoint anchor missing")
text = text.replace(old, new, 1)
write(path, text)

# Frontend fallback help gains the new model-intuition/directive commands and separated @ participants.
path = "src/interface/web/static/js/commands.js"
text = read(path)
text = text.replace('/dia @characterA@characterB', '/dia @characterA @characterB')
text = text.replace('/intimacy @characterA@characterB', '/intimacy @characterA @characterB')
anchor = '''  { id: "analyze", label: "/analyze", description: "Analyze the current prompt without generation", action: "analyze" },\n'''
new_commands = '''  { id: "intuition", label: "/intuition", category: "Deliberation", description: "Ask what most naturally follows without making it Canon", action: "insert", text: "/intuition @scene \\\"what should naturally happen next?\\\" " },\n  { id: "alternatives", label: "/alternatives", category: "Deliberation", description: "Generate several non-canonical next-beat alternatives", action: "insert", text: "/alternatives @scene count=4 \\\"next beat\\\" " },\n  { id: "describe", label: "/describe", category: "Writing", description: "Describe a subject using selector-aware grounding", action: "insert", text: "/describe @characterA.appearance detail=high " },\n  { id: "pov", label: "/pov", category: "Writing", description: "Temporarily emphasize a POV for this generation", action: "insert", text: "/pov @characterA \\\"scene intent\\\" " },\n  { id: "pace", label: "/pace", category: "Writing", description: "Temporarily steer narrative pacing", action: "insert", text: "/pace slow \\\"scene goal\\\" " },\n'''
if new_commands not in text:
    if anchor not in text: raise SystemExit("commands new entries anchor missing")
    text = text.replace(anchor, new_commands + anchor, 1)
write(path, text)

# Frontend consumes backend registry, supports selector-qualified @ refs and dynamic aliases, and exposes intuition diagnostics.
path = "src/interface/web/static/arline.js"
text = read(path)
old = '''  slashResults: [],\n  slashIndex: 0,\n  commandResults: [],\n'''
new = '''  slashResults: [],\n  slashIndex: 0,\n  commandRegistryVersion: null,\n  referenceSelectors: [],\n  dynamicReferences: [],\n  commandResults: [],\n'''
if old not in text: raise SystemExit("frontend state command anchor missing")
text = text.replace(old, new, 1)
old = '''    contextBreakdown: null,\n  },\n'''
new = '''    contextBreakdown: null,\n    deliberation: null,\n  },\n'''
if old not in text: raise SystemExit("frontend context cache anchor missing")
text = text.replace(old, new, 1)
anchor = '''const COMMANDS = window.ARLINE_COMMANDS || [];\n\n'''
helper = '''const COMMANDS = window.ARLINE_COMMANDS || [];\n\nasync function loadCommandRegistry() {\n  try {\n    const payload = await api("/api/commands");\n    const local = new Map(COMMANDS.map((item) => [item.id, item]));\n    const remote = payload.commands || [];\n    const merged = remote.map((item) => ({ ...(local.get(item.id) || {}), ...item, help: local.get(item.id)?.help || item.help }));\n    const remoteIds = new Set(remote.map((item) => item.id));\n    for (const item of COMMANDS) if (!remoteIds.has(item.id)) merged.push(item);\n    COMMANDS.splice(0, COMMANDS.length, ...merged);\n    state.commandRegistryVersion = payload.command_registry_version || null;\n    state.referenceSelectors = payload.reference_selectors || [];\n    state.dynamicReferences = payload.dynamic_references || [];\n  } catch (_) {\n    state.commandRegistryVersion = "frontend-fallback";\n  }\n}\n\n'''
if "async function loadCommandRegistry()" not in text:
    if anchor not in text: raise SystemExit("frontend command registry anchor missing")
    text = text.replace(anchor, helper, 1)
old = '''function addReference(ref) {\n  if (!state.selectedReferences.some((item) => item.type === ref.type && item.id === ref.id)) state.selectedReferences.push({ ...ref, mode: ref.mode || "context" });\n  updateContextChipUI();\n'''
new = '''function addReference(ref) {\n  const existing = state.selectedReferences.find((item) => item.type === ref.type && item.id === ref.id);\n  if (existing) {\n    if (ref.selector) existing.selector = ref.selector;\n    if (ref.mode) existing.mode = ref.mode;\n    if (ref.label) existing.label = ref.label;\n  } else state.selectedReferences.push({ ...ref, mode: ref.mode || "context" });\n  updateContextChipUI();\n'''
if old not in text: raise SystemExit("frontend addReference anchor missing")
text = text.replace(old, new, 1)
old = '''    merged.set(key, { type: ref.type, id: ref.id, label: ref.label || ref.name || ref.id, mode });\n'''
new = '''    merged.set(key, { type: ref.type, id: ref.id, label: ref.label || ref.name || ref.id, mode, selector: ref.selector || previous?.selector || null });\n'''
if old not in text: raise SystemExit("collect refs selector anchor missing")
text = text.replace(old, new, 1)
old = '''  container.innerHTML = state.selectedReferences.map((ref) => `<span class="context-chip" data-ref-key="${escapeHTML(`${ref.type}:${ref.id}`)}"><button class="context-peek" title="Peek">${escapeHTML(ENTITY_ICONS[ref.type] || "@")} <b>@${escapeHTML(ref.label)}</b></button>'''
new = '''  container.innerHTML = state.selectedReferences.map((ref) => `<span class="context-chip" data-ref-key="${escapeHTML(`${ref.type}:${ref.id}`)}"><button class="context-peek" title="Peek">${escapeHTML(ENTITY_ICONS[ref.type] || "@")} <b>@${escapeHTML(ref.label)}${ref.selector ? `.${escapeHTML(ref.selector)}` : ""}</b></button>'''
if old not in text: raise SystemExit("context chip selector anchor missing")
text = text.replace(old, new, 1)
old = '''  if (mention) {\n    const q = new URLSearchParams({ ...Object.fromEntries(scopeQuery()), q: mention[1], limit: "15" });\n    try {\n      const result = await api(`/api/mentions?${q}`);\n      state.mentionResults = result.results || [];\n      state.mentionIndex = 0;\n      renderMentionPopup();\n    } catch (_) { hideAutocomplete(); }\n  } else if (slash) {\n    const query = slash[1].toLowerCase();\n    state.slashResults = COMMANDS.filter((item) => item.label.toLowerCase().includes(query) || item.description.toLowerCase().includes(query));\n'''
new = '''  if (mention) {\n    const rawMention = mention[1];\n    const dot = rawMention.lastIndexOf(".");\n    const baseQuery = dot >= 0 ? rawMention.slice(0, dot) : rawMention;\n    const selectorQuery = dot >= 0 ? rawMention.slice(dot + 1).toLowerCase() : null;\n    const q = new URLSearchParams({ ...Object.fromEntries(scopeQuery()), q: baseQuery, limit: "15" });\n    try {\n      const result = await api(`/api/mentions?${q}`);\n      let rows = result.results || [];\n      if (selectorQuery !== null) {\n        const selectors = state.referenceSelectors.filter((name) => name.includes(selectorQuery));\n        rows = rows.flatMap((item) => selectors.map((selector) => ({\n          ...item, selector, baseLabel: item.label, label: `${item.label}.${selector}`,\n        })));\n      }\n      state.mentionResults = rows;\n      state.mentionIndex = 0;\n      renderMentionPopup();\n    } catch (_) { hideAutocomplete(); }\n  } else if (slash) {\n    const query = slash[1].toLowerCase();\n    const score = (item) => {\n      const label = String(item.label || "").toLowerCase();\n      const id = String(item.id || "").toLowerCase();\n      const aliases = (item.aliases || []).map((x) => String(x).toLowerCase());\n      const category = String(item.category || "").toLowerCase();\n      const description = String(item.description || "").toLowerCase();\n      if (label === `/${query}` || id === query) return 100;\n      if (label.startsWith(`/${query}`) || id.startsWith(query)) return 80;\n      if (aliases.some((x) => x.startsWith(query))) return 70;\n      if (label.includes(query) || id.includes(query)) return 55;\n      if (category.includes(query)) return 25;\n      if (description.includes(query)) return 15;\n      return 0;\n    };\n    state.slashResults = COMMANDS.map((item) => ({ item, score: score(item) })).filter((x) => x.score > 0 || !query).sort((a,b) => b.score - a.score).map((x) => x.item);\n'''
if old not in text: raise SystemExit("autocomplete semantic anchor missing")
text = text.replace(old, new, 1)
old = '''  const start = cursor - match[0].length; input.value = `${input.value.slice(0, start)}@${item.label} ${input.value.slice(cursor)}`;\n  const next = start + item.label.length + 2; input.setSelectionRange(next, next); addReference({ type: item.type, id: item.id, label: item.label }); hideAutocomplete(); refreshPromptHighlight(); input.focus();\n'''
new = '''  const start = cursor - match[0].length; input.value = `${input.value.slice(0, start)}@${item.label} ${input.value.slice(cursor)}`;\n  const next = start + item.label.length + 2; input.setSelectionRange(next, next);\n  if (!item.dynamic && item.type !== "dynamic_reference") addReference({ type: item.type, id: item.id, label: item.baseLabel || item.label.replace(/\\.[^.]+$/, ""), selector: item.selector || null });\n  hideAutocomplete(); refreshPromptHighlight(); input.focus();\n'''
if old not in text: raise SystemExit("chooseMention dynamic anchor missing")
text = text.replace(old, new, 1)
old = '''  state.contextCache.contextBreakdown = result.context_breakdown || null;\n  state.contextCache.promptText = byId("promptInput")?.value || "";\n'''
new = '''  state.contextCache.contextBreakdown = result.context_breakdown || null;\n  state.contextCache.deliberation = result.deliberation || result.workspace_context?.scope?.deliberation || null;\n  state.contextCache.promptText = byId("promptInput")?.value || "";\n'''
if old not in text: raise SystemExit("loadContextResult deliberation anchor missing")
text = text.replace(old, new, 1)
old = '''  if (byId("wcfOutput")) byId("wcfOutput").textContent = state.contextCache.wcf || "No WCF available.";\n'''
new = '''  if (byId("wcfOutput")) byId("wcfOutput").textContent = state.contextCache.wcf || "No WCF available.";\n  if (byId("deliberationOutput")) byId("deliberationOutput").textContent = pretty(state.contextCache.deliberation || {status:"No model intuition for this run."});\n'''
if old not in text: raise SystemExit("deliberation render anchor missing")
text = text.replace(old, new, 1)
old = '''    await Promise.all([refreshModels(), loadWorkspaceBootstrap(), loadDatasetStats()]);\n'''
new = '''    await Promise.all([refreshModels(), loadCommandRegistry(), loadWorkspaceBootstrap(), loadDatasetStats()]);\n'''
if old not in text: raise SystemExit("init command registry anchor missing")
text = text.replace(old, new, 1)
write(path, text)

# Intuition inspector tab + asset cache bump.
path = "src/interface/web/static/index.html"
text = read(path)
old = '''<div class="subtabs"><button class="active" data-subtab="wcf">WCF</button><button data-subtab="brief">Brief</button><button data-subtab="workspace">Workspace</button><button data-subtab="projection">Projection</button><button data-subtab="aif">AIF</button></div>\n        <pre id="wcfOutput" class="code-output active" data-subpanel="wcf">Analyze first.</pre><pre id="briefOutput" class="code-output" data-subpanel="brief">No brief.</pre><pre id="workspaceContextOutput" class="code-output" data-subpanel="workspace">No workspace context.</pre><pre id="projectionOutput" class="code-output" data-subpanel="projection">No projections.</pre><pre id="aifOutput" class="code-output" data-subpanel="aif">No AIF-Core.</pre>'''
new = '''<div class="subtabs"><button class="active" data-subtab="wcf">WCF</button><button data-subtab="brief">Brief</button><button data-subtab="workspace">Workspace</button><button data-subtab="intuition">Intuition</button><button data-subtab="projection">Projection</button><button data-subtab="aif">AIF</button></div>\n        <pre id="wcfOutput" class="code-output active" data-subpanel="wcf">Analyze first.</pre><pre id="briefOutput" class="code-output" data-subpanel="brief">No brief.</pre><pre id="workspaceContextOutput" class="code-output" data-subpanel="workspace">No workspace context.</pre><pre id="deliberationOutput" class="code-output" data-subpanel="intuition">Generate to inspect model intuition.</pre><pre id="projectionOutput" class="code-output" data-subpanel="projection">No projections.</pre><pre id="aifOutput" class="code-output" data-subpanel="aif">No AIF-Core.</pre>'''
if old not in text: raise SystemExit("index intuition subtab anchor missing")
text = text.replace(old, new, 1)
text = text.replace("?v=1.2.3-context", f"?v={CACHE_KEY}")
write(path, text)

# Browser smoke exercises backend command registry + dynamic @ references without requiring LM Studio generation.
path = "tests/frontend/browser_smoke.mjs"
text = read(path)
text = text.replace('contract.version !== "1.2.3a1"', f'contract.version !== "{VERSION}"')
old = '''  await page.click("#newChatBtn");\n  await page.waitForFunction(() => document.getElementById("chatView")?.classList.contains("active"));\n\n  if (pageErrors.length) throw new Error(`Page errors:\\n${pageErrors.join("\\n")}`);\n'''
new = '''  await page.click("#newChatBtn");\n  await page.waitForFunction(() => document.getElementById("chatView")?.classList.contains("active"));\n  await page.waitForFunction(() => window.ArlineRuntime?.getState?.().commandRegistryVersion === "1.2.4a1");\n  if (!document.getElementById("deliberationOutput")) throw new Error("Intuition inspector panel is missing");\n\n  await page.fill("#promptInput", "/intu");\n  await page.waitForFunction(() => !document.getElementById("slashPopup")?.classList.contains("hidden"));\n  if (!(await page.locator("#slashPopup").innerText()).includes("/intuition")) throw new Error("/intuition is missing from slash discovery");\n  await page.fill("#promptInput", "@po");\n  await page.waitForFunction(() => !document.getElementById("mentionPopup")?.classList.contains("hidden"));\n  if (!(await page.locator("#mentionPopup").innerText()).includes("pov")) throw new Error("@pov is missing from dynamic reference discovery");\n  await page.fill("#promptInput", "");\n\n  if (pageErrors.length) throw new Error(`Page errors:\\n${pageErrors.join("\\n")}`);\n'''
if old not in text: raise SystemExit("browser v124 anchor missing")
text = text.replace(old, new, 1)
write(path, text)

# Current contract/cache expectations move with the release; historical docs stay unchanged.
for test in (ROOT / "tests").glob("test_*.py"):
    body = test.read_text(encoding="utf-8")
    body2 = body.replace("1.2.3a1", VERSION).replace("?v=1.2.3-context", f"?v={CACHE_KEY}")
    if body2 != body:
        test.write_text(body2, encoding="utf-8")

# Update implementation status without rewriting historical milestone docs.
status = ROOT / "docs/V12_IMPLEMENTATION_STATUS.md"
if status.exists():
    body = status.read_text(encoding="utf-8")
    marker = "## v1.2.4 — Narrative Directives & Deliberation"
    if marker not in body:
        body += f'''\n\n{marker}\n\nImplemented top-down in `{VERSION}`:\n\n- typed backend slash-command registry and parser;\n- stable selector-qualified `@` grounding plus request-time dynamic refs;\n- directive-aware v1.2.3 context planning;\n- bounded model-intuition deliberation after ScopeGate/WCF validation and before writer realization;\n- soft-non-Canon deliberation diagnostics and fail-soft fallback;\n- shared semantics across normal and streaming generation;\n- browser autocomplete/Intuition inspector integration.\n'''
        status.write_text(body, encoding="utf-8")

print("v1.2.4 top-down directive/reference/deliberation pass applied")
