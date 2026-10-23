from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .engine import (
    COMMAND_ALIAS,
    COMMAND_REGISTRY_VERSION,
    DYNAMIC_REFERENCES,
    REFERENCE_SELECTORS,
    DirectiveEngine as LegacyDirectiveEngine,
    DirectiveIntent as LegacyDirectiveIntent,
)


COMMAND_RUNTIME_VERSION = "1.2.5a1"


@dataclass(frozen=True, slots=True)
class ArgSpec:
    name: str
    kind: str
    description: str = ""
    required: bool = False
    variadic: bool = False
    resource_types: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["resource_types"] = list(self.resource_types)
        return data


@dataclass(frozen=True, slots=True)
class OptionSpec:
    name: str
    kind: str = "string"
    description: str = ""
    choices: tuple[str, ...] = ()
    default: Any = None
    minimum: int | float | None = None
    maximum: int | float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["choices"] = list(self.choices)
        return data


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
    runtime_version: str = COMMAND_RUNTIME_VERSION
    command_stack: list[dict[str, Any]] = field(default_factory=list)
    execution_contract: dict[str, Any] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return bool(self.command or self.reference_expressions or self.command_stack)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def render(self) -> str:
        if not self.active:
            return ""
        lines = [
            "@ARLINE-DIRECTIVE 1.2.5",
            "authority: user_intent_not_story_fact",
            "canon_commit: forbidden",
            f"runtime: {self.runtime_version}",
        ]
        if self.command:
            lines += [
                f"command: {self.command.get('label')}",
                f"planner_intent: {self.planner_intent or 'auto'}",
                f"deliberation_mode: {self.deliberation_mode}",
                f"output_mode: {self.output_mode}",
            ]
        if len(self.command_stack) > 1:
            lines.append("command_stack: " + " -> ".join(str(item.get("label") or item.get("id")) for item in self.command_stack))
        if self.execution_contract:
            lines.append("retrieval_profile: " + str(self.execution_contract.get("retrieval_profile") or "default"))
            lines.append("realization_profile: " + str(self.execution_contract.get("realization_profile") or self.output_mode))
            lines.append("authority_mutation: forbidden")
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


PACING = ("auto", "immediate", "fast", "natural", "slow", "lingering")
CURVES = ("auto", "flat", "rising", "falling", "wave", "spike")
LEVELS = ("low", "medium", "high")

RETRIEVAL_PROFILES: dict[str, dict[str, float]] = {
    "scene_continue": dict(continuity=1.00, state=.92, relationships=.82, events=.72, spatial=.62, threads=.78, pov=.72, source=.32),
    "character_voice": dict(continuity=.96, state=.82, relationships=.90, events=.48, spatial=.30, threads=.55, pov=1.00, source=.20),
    "character_interaction": dict(continuity=1.00, state=.90, relationships=1.00, events=.58, spatial=.42, threads=.65, pov=1.00, source=.24),
    "scene_description": dict(continuity=.84, state=1.00, relationships=.46, events=.38, spatial=1.00, threads=.34, pov=.58, source=.34),
    "revision": dict(continuity=1.00, state=.88, relationships=.78, events=.70, spatial=.55, threads=.66, pov=.76, source=.68),
    "author_deliberation": dict(continuity=1.00, state=.92, relationships=.90, events=.90, spatial=.60, threads=.86, pov=.92, source=.42),
    "modifier": dict(continuity=0.00, state=0.00, relationships=0.00, events=0.00, spatial=0.00, threads=0.00, pov=0.00, source=0.00),
}


COMMAND_SCHEMA: dict[str, dict[str, Any]] = {
    "continue": dict(role="operation", retrieval_profile="scene_continue", deliberation_profile="scene", realization_profile="fiction", why_use="Continue the active scene without restating continuity, cast, POV, and open threads manually.", arguments=[ArgSpec("refs", "reference", "Optional explicit grounding", variadic=True), ArgSpec("goal", "text", "Semantic continuation goal")], options=[OptionSpec("pace", "enum", "Narrative pacing", PACING, "auto")], examples=["/continue @scene", "/continue @scene pace=slow \"let the tension settle naturally\""]),
    "rewrite": dict(role="operation", retrieval_profile="revision", deliberation_profile="revision", realization_profile="fiction_revision", why_use="Revise prose while keeping current authoritative state and continuity visible to the writer.", arguments=[ArgSpec("refs", "reference", variadic=True), ArgSpec("goal", "text")], options=[OptionSpec("pace", "enum", choices=PACING), OptionSpec("tone", "string"), OptionSpec("preserve", "string")], examples=["/rewrite @scene \"make the exchange less formal\""]),
    "mono": dict(role="operation", retrieval_profile="character_voice", deliberation_profile="character", realization_profile="fiction_monologue", why_use="Realize one character's expression through their voice, state, relationships, and POV boundaries.", arguments=[ArgSpec("character", "reference", "Character to realize", required=True, resource_types=("entity_variant",)), ArgSpec("goal", "text")], options=[OptionSpec("pace", "enum", choices=PACING), OptionSpec("delivery", "enum", choices=("internal", "spoken", "whisper", "murmur", "mutter"))], examples=["/mono @Fila internal slow \"why did I say that?\""]),
    "dia": dict(role="operation", retrieval_profile="character_interaction", deliberation_profile="interaction", realization_profile="fiction_dialogue", why_use="Use a relationship-aware dialogue profile instead of merely asking the model to write dialogue.", arguments=[ArgSpec("participants", "reference", "Dialogue participants", required=True, variadic=True, resource_types=("entity_variant",)), ArgSpec("goal", "text")], options=[OptionSpec("pace", "enum", choices=PACING, default="natural"), OptionSpec("curve", "enum", choices=CURVES, default="auto"), OptionSpec("tension", "enum", choices=LEVELS, default="medium")], examples=["/dia @Fila @Mira pace=slow tension=high \"awkward apology\"", "/dia @Fila @Mira curve=wave \"discuss moving away\""]),
    "ambience": dict(role="operation", retrieval_profile="scene_description", deliberation_profile="scene", realization_profile="fiction_description", why_use="Steer atmosphere and sensory density without silently creating persistent location facts.", arguments=[ArgSpec("refs", "reference", variadic=True), ArgSpec("goal", "text")], options=[OptionSpec("pace", "enum", choices=PACING), OptionSpec("detail", "enum", choices=LEVELS)], examples=["/ambience @location pace=lingering \"quiet after closing time\""]),
    "intimacy": dict(role="operation", retrieval_profile="character_interaction", deliberation_profile="interaction", realization_profile="fiction_interaction", why_use="Use the same continuity, agency, POV, relationship, pacing, and aftermath rails as other character interaction.", arguments=[ArgSpec("participants", "reference", required=True, variadic=True, resource_types=("entity_variant",)), ArgSpec("goal", "text")], options=[OptionSpec("pace", "enum", choices=PACING), OptionSpec("curve", "enum", choices=CURVES)], examples=["/intimacy @Fila @Mira pace=slow \"reconciliation and vulnerability\""]),
    "intuition": dict(role="operation", retrieval_profile="author_deliberation", deliberation_profile="inspect", realization_profile="author_intuition", why_use="Ask what most naturally follows before committing to prose. Output remains non-canonical author-facing reasoning.", arguments=[ArgSpec("refs", "reference", variadic=True), ArgSpec("question", "text")], options=[], examples=["/intuition @scene \"what naturally happens next?\""]),
    "alternatives": dict(role="operation", retrieval_profile="author_deliberation", deliberation_profile="alternatives", realization_profile="author_alternatives", why_use="Generate bounded non-canonical alternatives without silently choosing one.", arguments=[ArgSpec("refs", "reference", variadic=True), ArgSpec("goal", "text")], options=[OptionSpec("count", "integer", "Number of alternatives", minimum=1, maximum=8, default=4)], examples=["/alternatives @scene count=5 \"next beat\""]),
    "describe": dict(role="operation", retrieval_profile="scene_description", deliberation_profile="scene", realization_profile="fiction_description", why_use="Description becomes selector-aware, so @Fila.appearance and @Fila.state can request different evidence.", arguments=[ArgSpec("subject", "reference", required=True), ArgSpec("focus", "text")], options=[OptionSpec("detail", "enum", choices=LEVELS, default="medium")], examples=["/describe @Fila.appearance detail=high"]),
    "pov": dict(role="modifier", retrieval_profile="modifier", deliberation_profile="character", realization_profile="modifier", why_use="Temporarily set the epistemic anchor for one request without mutating the active scene.", arguments=[ArgSpec("character", "reference", required=True, resource_types=("entity_variant",))], options=[], examples=["/pov @Fila"]),
    "pace": dict(role="modifier", retrieval_profile="modifier", deliberation_profile="scene", realization_profile="modifier", why_use="Apply pacing as structured request metadata rather than repeating prose instructions.", arguments=[], options=[OptionSpec("pace", "enum", choices=PACING, default="natural")], examples=["/pace slow"]),
}


def _schema_row(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    schema = COMMAND_SCHEMA.get(str(item.get("id") or ""), {})
    item.update({
        "runtime_version": COMMAND_RUNTIME_VERSION,
        "role": schema.get("role", "operation"),
        "arguments": [arg.to_dict() for arg in schema.get("arguments", [])],
        "options": [opt.to_dict() for opt in schema.get("options", [])],
        "why_use": schema.get("why_use", ""),
        "examples": list(schema.get("examples", [])),
        "execution_contract": _contract_for([str(item.get("id") or "")], str(item.get("id") or "")),
    })
    return item


def _contract_for(ids: list[str], primary_id: str) -> dict[str, Any]:
    weights = {key: 0.0 for key in next(iter(RETRIEVAL_PROFILES.values())).keys()}
    for command_id in ids:
        profile_name = str(COMMAND_SCHEMA.get(command_id, {}).get("retrieval_profile") or "modifier")
        for key, value in RETRIEVAL_PROFILES.get(profile_name, {}).items():
            weights[key] = max(weights.get(key, 0.0), float(value))
    primary = COMMAND_SCHEMA.get(primary_id, {})
    return {
        "runtime_version": COMMAND_RUNTIME_VERSION,
        "retrieval_profile": primary.get("retrieval_profile", "scene_continue"),
        "retrieval_weights": {key: round(value, 3) for key, value in weights.items()},
        "deliberation_profile": primary.get("deliberation_profile", "auto"),
        "realization_profile": primary.get("realization_profile", "fiction"),
        "capabilities": ["read_context", "deliberate", "generate"],
        "authority": "generation_only",
        "mutates_authority": False,
        "writer_calls_hint": 1,
    }


def _as_v125(base: LegacyDirectiveIntent, *, command: dict[str, Any] | None = None, stack: list[dict[str, Any]] | None = None, contract: dict[str, Any] | None = None, options: dict[str, Any] | None = None, semantic_prompt: str | None = None, planner_intent: str | None = None, deliberation_mode: str | None = None, output_mode: str | None = None, diagnostics: list[str] | None = None) -> DirectiveIntent:
    return DirectiveIntent(
        version=base.version,
        raw_prompt=base.raw_prompt,
        semantic_prompt=semantic_prompt if semantic_prompt is not None else base.semantic_prompt,
        command=command if command is not None else base.command,
        options=dict(options if options is not None else base.options),
        reference_expressions=list(base.reference_expressions),
        resolved_references=[dict(item) for item in base.resolved_references],
        dynamic_scopes=list(base.dynamic_scopes),
        unresolved_references=list(base.unresolved_references),
        planner_intent=planner_intent if planner_intent is not None else base.planner_intent,
        deliberation_mode=deliberation_mode if deliberation_mode is not None else base.deliberation_mode,
        output_mode=output_mode if output_mode is not None else base.output_mode,
        generation_only=base.generation_only,
        diagnostics=list(diagnostics if diagnostics is not None else base.diagnostics),
        command_stack=list(stack or []),
        execution_contract=dict(contract or {}),
    )


def _normalized_options(options: dict[str, Any], command_ids: list[str], diagnostics: list[str]) -> dict[str, Any]:
    result = dict(options)
    if "pace" in result:
        result["pacing"] = result.pop("pace")
    allowed: dict[str, OptionSpec] = {}
    for command_id in command_ids:
        for spec in COMMAND_SCHEMA.get(command_id, {}).get("options", []):
            allowed[spec.name] = spec
            if spec.name == "pace":
                allowed["pacing"] = spec
    for key in list(result):
        spec = allowed.get(key)
        if spec is None:
            continue
        value = result[key]
        if spec.kind == "integer":
            try:
                number = int(value)
            except (TypeError, ValueError):
                diagnostics.append(f"Option {key} expects an integer; ignored {value!r}.")
                result.pop(key, None)
                continue
            if spec.minimum is not None:
                number = max(int(spec.minimum), number)
            if spec.maximum is not None:
                number = min(int(spec.maximum), number)
            result[key] = number
        elif spec.choices:
            text = str(value).casefold()
            if text not in spec.choices:
                diagnostics.append(f"Option {key}={value!r} is invalid; allowed: {', '.join(spec.choices)}.")
                result.pop(key, None)
            else:
                result[key] = text
    return result


class DirectiveEngine:
    COMMAND_LINE = LegacyDirectiveEngine.COMMAND_LINE
    REFERENCE = LegacyDirectiveEngine.REFERENCE
    PACING = LegacyDirectiveEngine.PACING
    SOFT_FLAGS = LegacyDirectiveEngine.SOFT_FLAGS

    @classmethod
    def catalog(cls) -> list[dict[str, Any]]:
        return [_schema_row(row) for row in LegacyDirectiveEngine.catalog()]

    @classmethod
    def dynamic_reference_suggestions(cls, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return LegacyDirectiveEngine.dynamic_reference_suggestions(*args, **kwargs)

    @classmethod
    def parse(cls, prompt: str, *, explicit_references: list[dict[str, Any]] | None = None, active_scene: dict[str, Any] | None = None, project_id: str | None = None, world_id: str | None = None, branch_id: str | None = None) -> DirectiveIntent:
        kwargs = dict(explicit_references=explicit_references, active_scene=active_scene, project_id=project_id, world_id=world_id, branch_id=branch_id)
        raw = str(prompt or "")
        base = LegacyDirectiveEngine.parse(raw, **kwargs)
        known_lines: list[tuple[str, str, Any]] = []
        for line in raw.splitlines():
            match = cls.COMMAND_LINE.match(line)
            if not match:
                continue
            legacy_spec = COMMAND_ALIAS.get(match.group(1).casefold())
            if legacy_spec is not None:
                known_lines.append((line, legacy_spec.id, legacy_spec))
        if not known_lines:
            return _as_v125(base)

        diagnostics = list(base.diagnostics)
        command_ids = [command_id for _, command_id, _ in known_lines]
        primary_id = next((command_id for _, command_id, _ in reversed(known_lines) if COMMAND_SCHEMA.get(command_id, {}).get("role") != "modifier"), command_ids[-1])
        catalog_by_id = {row["id"]: row for row in cls.catalog()}
        primary_row = catalog_by_id.get(primary_id) or dict(base.command or {})
        merged_options: dict[str, Any] = {}
        stack: list[dict[str, Any]] = []
        goals: list[str] = []
        for line, command_id, legacy_spec in known_lines:
            parsed = LegacyDirectiveEngine.parse(line, **kwargs)
            merged_options.update(parsed.options)
            semantic = str(parsed.semantic_prompt or "").strip()
            default_prefixes = ("Execute the /", "Continue the active scene naturally.", "Assess the most natural next narrative beat.", "Propose distinct plausible next narrative beats.", "Describe the explicitly grounded subject.")
            if semantic and not semantic.startswith(default_prefixes):
                goals.append(semantic)
            stack.append({
                "id": command_id,
                "label": legacy_spec.label,
                "role": COMMAND_SCHEMA.get(command_id, {}).get("role", "operation"),
                "raw": line.strip(),
                "options": dict(parsed.options),
            })
        merged_options.update(base.options)
        merged_options = _normalized_options(merged_options, command_ids, diagnostics)
        if primary_id == "pov" and "pov_variant_id" not in merged_options:
            pov = next((item for item in base.resolved_references if item.get("type") == "entity_variant"), None)
            if pov:
                merged_options["pov_variant_id"] = str(pov["id"])

        non_command = "\n".join(line for line in raw.splitlines() if not cls.COMMAND_LINE.match(line)).strip()
        semantic = non_command or next((goal for goal in reversed(goals) if goal), "") or base.semantic_prompt
        contract = _contract_for(command_ids, primary_id)
        if len(stack) > 1:
            diagnostics.append("v1.2.5 compiled multiple slash directives into one generation execution contract.")
        return _as_v125(
            base,
            command=primary_row,
            stack=stack,
            contract=contract,
            options=merged_options,
            semantic_prompt=semantic,
            planner_intent=str(primary_row.get("planner_intent") or base.planner_intent or "continue"),
            deliberation_mode=str(primary_row.get("deliberation_mode") or contract.get("deliberation_profile") or "auto"),
            output_mode=str(primary_row.get("output_mode") or base.output_mode or "fiction"),
            diagnostics=diagnostics,
        )


__all__ = [
    "COMMAND_RUNTIME_VERSION", "RETRIEVAL_PROFILES", "ArgSpec", "OptionSpec",
    "DirectiveIntent", "DirectiveEngine",
]
