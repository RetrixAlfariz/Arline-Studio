from __future__ import annotations

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
        if command_spec is not None and command_spec.id == "pov":
            pov_ref = next((item for item in resolved if item.get("type") == "entity_variant"), None)
            if pov_ref is not None:
                options["pov_variant_id"] = str(pov_ref["id"])
            else:
                diagnostics.append("/pov requires one resolved character reference; the existing scene POV remains active.")
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
