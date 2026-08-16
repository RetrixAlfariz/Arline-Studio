from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from src.context_compiler import AIFCompiler
from src.context import (
    ContextBudget,
    ContextBudgeter,
    TokenCounter,
    TraceResolver,
    WCFRenderer,
    WCFValidator,
    WriterContextBuilder,
)
from src.analytical_system.budget import ReasoningBudget
from src.analytical_system import ProjectionEngine
from src.core import SemanticCoreBuilder
from src.inference import LMStudioClient, LMStudioError, LMStudioModelManager
from src.narrative import NarrativeBriefBuilder, NarrativeRuntimeBuilder
from src.pipeline import ArlineAnalyticalPipeline
from src.runtime_config import RuntimeConfig
from src.writer import ArlineWriter, PostWriteValidator
from src.workspace import WorkspaceContext


@dataclass(slots=True)
class AnalysisBundle:
    pipeline_result: Any
    semantic_core: Any
    world_runtime: Any
    narrative_runtime: Any
    writer_context: Any
    rendered_context: Any
    wcf_validation: Any
    aif_core: str
    narrative_brief: Any
    workspace_context: WorkspaceContext | None = None


@dataclass(slots=True)
class GenerationBundle:
    analysis: AnalysisBundle
    story: str
    reasoning: str
    stats: dict[str, Any]
    raw_response: dict[str, Any]
    post_validation: Any
    model_input: str
    load_status: dict[str, Any]


class ArlineService:
    """Stable application boundary for CLI/Web/API frontends."""

    def __init__(self, config: RuntimeConfig):
        self.config = config
        self.pipeline = ArlineAnalyticalPipeline.default()
        self.core_builder = SemanticCoreBuilder.default()
        self.narrative_builder = NarrativeRuntimeBuilder.default()
        self.brief_builder = NarrativeBriefBuilder.default()
        self.context_builder = WriterContextBuilder.default()
        self.renderer = WCFRenderer.default()
        self.wcf_validator = WCFValidator.default()
        self.budgeter = ContextBudgeter(TokenCounter())
        self.aif = AIFCompiler()
        self.post_validator = PostWriteValidator()
        self.projection_engine = ProjectionEngine(
            mode=config.projection.mode,
            min_confidence=config.projection.min_confidence,
            max_items=config.projection.max_items,
        )
        self.pipeline.reasoning_budget_guard.budget = ReasoningBudget(
            max_depth=config.reasoning_budget.max_depth,
            max_nodes=config.reasoning_budget.max_nodes,
            min_confidence=config.reasoning_budget.min_confidence,
            min_relevance=config.reasoning_budget.min_relevance,
        )

    @classmethod
    def from_config(cls, path="config/arline.toml"):
        return cls(RuntimeConfig.load(path))

    def client(self) -> LMStudioClient:
        return LMStudioClient(
            base_url=self.config.lmstudio.base_url,
            api_key=self.config.lmstudio.api_key,
            timeout_seconds=self.config.lmstudio.timeout_seconds,
        )

    def reasoning_capabilities(self) -> dict[str, Any]:
        model = self.config.lmstudio.model
        if not model:
            return {"allowed_options": ["off"], "default": "off", "reported": False}
        return self.client().reasoning_config(model)

    def resolve_reasoning_mode(self) -> str | None:
        requested = self.config.generation.reasoning
        if not self.config.reasoning_runtime.enforce_model_capabilities:
            return requested
        return self.client().resolve_reasoning_option(
            self.config.lmstudio.model, requested
        )

    def analyze(
        self,
        prompt: str,
        *,
        surface_history=None,
        workspace_context: WorkspaceContext | None = None,
    ) -> AnalysisBundle:
        result = self.pipeline.run(prompt, surface_history=surface_history)
        core = self.core_builder.build(result)
        narrative = self.narrative_builder.build(
            prompt, result, surface_history=surface_history
        )
        if workspace_context and workspace_context.scope:
            project_settings = workspace_context.scope.get("project_settings") or {}
            world_settings = workspace_context.scope.get("world_settings") or {}
            language_setting = world_settings.get("language") or project_settings.get("language")
            register_setting = world_settings.get("register") or project_settings.get("register")
            narrator_pronoun = world_settings.get("narrator_pronoun") or project_settings.get("narrator_pronoun")
            if language_setting and language_setting not in {"follow_prompt", "auto"}:
                narrative.language.language = str(language_setting)
            if register_setting and register_setting not in {"follow_prompt", "auto"}:
                narrative.language.register = str(register_setting)
            if narrator_pronoun and narrator_pronoun not in {"follow_prompt", "auto"}:
                narrative.language.narrator_pronoun = str(narrator_pronoun)
            lens_settings = world_settings.get("description_lens") or project_settings.get("description_lens") or {}
            if isinstance(lens_settings, dict) and lens_settings:
                for key in ("visual", "tactile", "spatial", "emotional", "social", "auditory"):
                    if key in lens_settings:
                        try:
                            setattr(narrative.description_lens, key, max(0.0, float(lens_settings[key])))
                        except (TypeError, ValueError):
                            pass
                total = sum(narrative.description_lens.to_dict().values())
                if total > 0:
                    for key, value in narrative.description_lens.to_dict().items():
                        setattr(narrative.description_lens, key, round(value / total, 3))
        projections = self.projection_engine.project(core, result, narrative)
        ctx = self.context_builder.build(
            prompt, core, result, narrative, projections=projections
        )
        budget = ContextBudget(
            model_context_length=self.config.model_load.context_length,
            max_output_tokens=self.config.generation.api_max_output_tokens,
            system_prompt_tokens=self.config.context_budget.system_prompt_token_estimate,
            safety_margin=self.config.context_budget.safety_margin,
            minimum_writer_context=self.config.context_budget.minimum_writer_context_tokens,
        )
        ctx, rendered = self.budgeter.fit(ctx, budget)
        validation = self.wcf_validator.validate(ctx, rendered.text)
        aif = self.aif.compile(
            result.extracted_state, result.events, result.analysis, profile="teacher"
        ).text
        brief = self.brief_builder.build(
            ctx, narrative, workspace_context=workspace_context
        )
        world_runtime = result.world_runtime or {}
        return AnalysisBundle(
            result, core, world_runtime, narrative, ctx, rendered, validation,
            aif, brief, workspace_context
        )

    def compose_model_input(
        self,
        prompt: str,
        bundle: AnalysisBundle,
        mode: str | None = None,
        *,
        session_context: str | None = None,
        beat_context: str | None = None,
    ) -> str:
        mode = mode or self.config.writer.input_mode
        request = self._compact_request(prompt, bundle)
        if mode == "raw":
            return (
                f"<REQUEST>\n{prompt.strip()}\n</REQUEST>\n\n"
                "<WRITE>Write the requested fiction.</WRITE>"
            )
        if mode == "aif_core":
            return (
                f"<AIF_CORE>\n{bundle.aif_core.rstrip()}\n</AIF_CORE>\n\n"
                f"<REQUEST>\n{request}\n</REQUEST>\n\n"
                "<WRITE>Write the requested fiction.</WRITE>"
            )

        parts = []
        if bundle.workspace_context and bundle.workspace_context.text:
            parts += [
                "<WORKSPACE_CONTEXT>",
                bundle.workspace_context.text.rstrip(),
                "</WORKSPACE_CONTEXT>",
                "",
            ]
        if bundle.narrative_brief and bundle.narrative_brief.text:
            parts += [
                "<NARRATIVE_BRIEF>",
                bundle.narrative_brief.text.rstrip(),
                "</NARRATIVE_BRIEF>",
                "",
            ]
        parts += [
            "<ARLINE_CONTEXT>",
            bundle.rendered_context.text.rstrip(),
            "</ARLINE_CONTEXT>",
            "",
            "<REQUEST>",
            request,
            "</REQUEST>",
        ]
        if mode == "wcf_raw":
            parts += [
                "",
                "<RAW_SOURCE>",
                "Reference source only. REQUEST above is the normalized task. "
                "Raw wording does not override LOCKED/UNKNOWN/TRANSITIONS and "
                "does not authorize invention of missing precision.",
                prompt.strip(),
                "</RAW_SOURCE>",
            ]
        if mode == "smart_hybrid":
            fragments = []
            for item in bundle.semantic_core.unresolved[:8]:
                text = (item.get("text") or item.get("text_preview") or "").strip()
                if text:
                    fragments.append(text)
            if fragments:
                parts += [
                    "",
                    "<UNRESOLVED_SOURCE_CONTEXT>",
                    "Use these only to preserve intent; canonical ARLINE_CONTEXT "
                    "wins on conflicts and unknown precision remains unknown.",
                    *["- " + item for item in fragments],
                    "</UNRESOLVED_SOURCE_CONTEXT>",
                ]
            if session_context:
                parts += [
                    "",
                    "<SESSION_CONTINUITY_CONTEXT>",
                    "Earlier user messages are continuity source context. Later user "
                    "messages override earlier ones. Previous generated prose is only "
                    "surface continuity and must not override canonical ARLINE_CONTEXT, "
                    "UNKNOWN precision, or current user corrections.",
                    session_context.strip(),
                    "</SESSION_CONTINUITY_CONTEXT>",
                ]
        if beat_context:
            parts += [
                "",
                "<BEAT_CONTEXT>",
                beat_context.strip(),
                "</BEAT_CONTEXT>",
            ]
        parts += [
            "",
            "<WRITE>",
            "Write the requested fiction using the structured context.",
            "</WRITE>",
        ]
        return "\n".join(parts)

    def generate(
        self,
        prompt: str,
        *,
        mode: str | None = None,
        surface_history=None,
        session_context: str | None = None,
        workspace_context: WorkspaceContext | None = None,
        beat_context: str | None = None,
    ) -> GenerationBundle:
        bundle = self.analyze(
            prompt,
            surface_history=surface_history,
            workspace_context=workspace_context,
        )
        mode = mode or self.config.writer.input_mode
        client = self.client()
        manager = LMStudioModelManager(self.config, rest_client=client)
        load = manager.ensure_loaded()

        # Native reasoning modes are per-model. Validate after loading so the
        # current model metadata is authoritative. Models with no public
        # reasoning configuration use an omitted reasoning field for `off`.
        effective_reasoning = self.resolve_reasoning_mode()

        # Once the model is loaded, replace the heuristic context estimate with
        # the model's own tokenizer and re-apply semantic budgeting.
        exact_counter = TokenCounter.from_lmstudio(self.config.lmstudio.model)
        system_text = self.config.writer.system_prompt_file.read_text(encoding="utf-8")
        if self.config.generation.reasoning != "off":
            guard_path = self.config.reasoning_runtime.guard_prompt_file
            if guard_path.exists():
                system_text += "\n\n" + guard_path.read_text(encoding="utf-8")
        budget = ContextBudget(
            model_context_length=self.config.model_load.context_length,
            max_output_tokens=self.config.generation.api_max_output_tokens,
            system_prompt_tokens=exact_counter.count(system_text),
            safety_margin=self.config.context_budget.safety_margin,
            minimum_writer_context=self.config.context_budget.minimum_writer_context_tokens,
        )
        bundle.writer_context, bundle.rendered_context = ContextBudgeter(
            exact_counter
        ).fit(bundle.writer_context, budget)
        bundle.wcf_validation = self.wcf_validator.validate(
            bundle.writer_context, bundle.rendered_context.text
        )
        if mode != "raw" and not bundle.wcf_validation.valid and mode != "aif_core":
            raise ValueError(
                "Writer context validation failed: "
                + json.dumps(bundle.wcf_validation.to_dict(), ensure_ascii=False)
            )

        model_input = self.compose_model_input(
            prompt,
            bundle,
            mode,
            session_context=session_context,
            beat_context=beat_context,
        )
        writer = ArlineWriter(self.config, client=client)
        result = writer.generate(
            model_input=model_input,
            input_mode=mode,
            reasoning_for_api=effective_reasoning,
        )
        post = (
            self.post_validator.validate(result.story, bundle.writer_context)
            if self.config.writer.post_validate
            else None
        )
        return GenerationBundle(
            bundle,
            result.story,
            result.reasoning,
            result.stats,
            result.raw_response,
            post,
            model_input,
            load,
        )

    def generate_beats(
        self,
        prompt: str,
        *,
        beat_count: int | None = None,
        beat_tokens: int | None = None,
        mode: str | None = None,
        surface_history=None,
        session_context: str | None = None,
        workspace_context: WorkspaceContext | None = None,
    ) -> GenerationBundle:
        """Generate a long narrative as bounded sequential beats.

        Generated beats are continuity surface, not canonical state. Each beat
        receives the same validated WCF plus the previous surface and an
        explicit progression contract. This avoids asking one decoder call to
        fill an entire long story and reduces semantic looping.
        """
        count = max(1, int(beat_count or self.config.generation.beat_count))
        per_beat = max(256, int(beat_tokens or self.config.generation.beat_tokens))
        mode = mode or self.config.writer.input_mode
        bundle = self.analyze(
            prompt,
            surface_history=surface_history,
            workspace_context=workspace_context,
        )
        client = self.client()
        manager = LMStudioModelManager(self.config, rest_client=client)
        load = manager.ensure_loaded()
        effective_reasoning = self.resolve_reasoning_mode()
        writer = ArlineWriter(self.config, client=client)

        old_visible = self.config.generation.visible_output_tokens
        stories: list[str] = []
        reasonings: list[str] = []
        raw_responses: list[dict[str, Any]] = []
        beat_stats: list[dict[str, Any]] = []
        try:
            self.config.generation.visible_output_tokens = per_beat
            for index in range(1, count + 1):
                previous = "\n\n".join(stories)
                previous_tail = previous[-9000:] if previous else ""
                beat_instruction = (
                    f"Beat {index} of {count}. Advance one coherent narrative unit. "
                    "Do not recap or paraphrase earlier beats. Preserve all canonical "
                    "state and treat previous prose as non-canonical surface continuity. "
                    "End this beat at a natural handoff point."
                )
                if previous_tail:
                    beat_instruction += (
                        "\n\nPrevious generated surface (continue from it; do not repeat it):\n"
                        + previous_tail
                    )
                model_input = self.compose_model_input(
                    prompt,
                    bundle,
                    mode,
                    session_context=session_context,
                    beat_context=beat_instruction,
                )
                result = writer.generate(
                    model_input=model_input,
                    input_mode=mode,
                    reasoning_for_api=effective_reasoning,
                )
                stories.append(result.story.strip())
                if result.reasoning:
                    reasonings.append(f"[Beat {index}]\n{result.reasoning}")
                raw_responses.append(result.raw_response)
                beat_stats.append({"beat": index, **result.stats})
        finally:
            self.config.generation.visible_output_tokens = old_visible

        story = "\n\n".join(x for x in stories if x).strip()
        aggregate: dict[str, Any] = {
            "generation_mode": "beats",
            "beat_count": count,
            "tokens_per_beat": per_beat,
            "beats": beat_stats,
        }
        for key in (
            "input_tokens",
            "total_output_tokens",
            "reasoning_output_tokens",
            "story_output_tokens",
        ):
            values = [
                item.get(key)
                for item in beat_stats
                if isinstance(item.get(key), (int, float))
            ]
            if values:
                aggregate[key] = int(sum(values))
        speeds = [
            item.get("tokens_per_second")
            for item in beat_stats
            if isinstance(item.get("tokens_per_second"), (int, float))
        ]
        if speeds:
            aggregate["tokens_per_second_average"] = round(
                sum(speeds) / len(speeds), 3
            )
        post = (
            self.post_validator.validate(story, bundle.writer_context)
            if self.config.writer.post_validate
            else None
        )
        return GenerationBundle(
            bundle,
            story,
            "\n\n".join(reasonings),
            aggregate,
            {"beats": raw_responses},
            post,
            self.compose_model_input(
                prompt, bundle, mode, session_context=session_context
            ),
            load,
        )

    def reload_model(self):
        return LMStudioModelManager(
            self.config, rest_client=self.client()
        ).reload_model()

    def list_models(self):
        return [m for m in self.client().list_models() if m.get("type") == "llm"]

    def trace_fact(self, bundle: AnalysisBundle, trace_id: str):
        return TraceResolver.resolve(bundle.writer_context, trace_id)

    def save_generation(self, bundle: GenerationBundle, output_dir: Path | str = "output"):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        result = bundle.analysis.pipeline_result
        (out / "story.txt").write_text(bundle.story.rstrip() + "\n", encoding="utf-8")
        (out / "context.wcf").write_text(
            bundle.analysis.rendered_context.text, encoding="utf-8"
        )
        (out / "aif_core.txt").write_text(bundle.analysis.aif_core, encoding="utf-8")
        for name, payload in (
            ("extracted_state.json", result.extracted_state),
            ("events.json", result.events),
            ("analysis.json", result.analysis),
            ("semantic_core.json", bundle.analysis.semantic_core.to_dict()),
            ("world_runtime.json", bundle.analysis.world_runtime),
            ("narrative_runtime.json", bundle.analysis.narrative_runtime.to_dict()),
            ("narrative_brief.json", bundle.analysis.narrative_brief.to_dict()),
            ("workspace_context.json", bundle.analysis.workspace_context.to_dict() if bundle.analysis.workspace_context else {}),
            ("writer_context.json", bundle.analysis.writer_context.to_dict()),
            ("projections.json", [x.to_dict() for x in bundle.analysis.writer_context.projections]),
            ("wcf_validation.json", bundle.analysis.wcf_validation.to_dict()),
            (
                "post_write_validation.json",
                bundle.post_validation.to_dict() if bundle.post_validation else {},
            ),
            (
                "writer_request.json",
                {
                    "mode": self.config.writer.input_mode,
                    "projection_mode": self.config.projection.mode,
                    "model": self.config.lmstudio.model,
                    "model_input": bundle.model_input,
                },
            ),
            ("lmstudio_response.json", bundle.raw_response),
        ):
            (out / name).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        if bundle.reasoning:
            (out / "reasoning.txt").write_text(bundle.reasoning + "\n", encoding="utf-8")
        return out

    def _compact_request(self, prompt: str, bundle: AnalysisBundle) -> str:
        """Compile the user request without forwarding contradictory precision pressure.

        The raw source is still available in WCF+Raw mode, but the normalized
        REQUEST makes explicit that missing measurements remain unknown. This
        is especially important for native-thinking models, which otherwise
        tend to reason themselves into filling requested-but-unsupported gaps.
        """
        state = bundle.pipeline_result.extracted_state
        directives = [
            item.get("text", "").strip()
            for item in state.get("directives", [])
            if item.get("text")
        ]
        requests = [
            item.get("text", "").strip()
            for item in state.get("requests", [])
            if item.get("text")
        ]

        def is_measurement_request(text: str) -> bool:
            low = text.lower()
            return bool(
                re.search(
                    r"\b(?:ukuran|cm|centimeter|sentimeter|meter|panjangnya|seberapa panjang)\b",
                    low,
                )
            )

        # A request sometimes gets classified as both directive and request.
        # Do not repeat it, and do not forward unsafe pressure for invented
        # precision as if it were a canonical instruction.
        request_set = {text for text in requests}
        safe_directives = [
            text
            for text in directives
            if text not in request_set and not is_measurement_request(text)
        ]

        safe_requests: list[str] = []
        if any(is_measurement_request(text) for text in requests + directives):
            safe_requests.append(
                "Explain the physical scale of measurements that are canonical, "
                "safely derivable, or explicitly provided as a bounded PROJECTION. "
                "Use PROJECTION ranges for approximate visualization when useful. "
                "Do not invent additional exact garment/body measurements, and do "
                "not promote an approximate projection into a canonical endpoint."
            )
        safe_requests.extend(
            text for text in requests if not is_measurement_request(text)
        )

        parts: list[str] = []
        if safe_directives:
            parts.append(
                "Narrative directives:\n" + "\n".join("- " + x for x in safe_directives)
            )
        if safe_requests:
            parts.append(
                "Explicit requests (normalized against canonical uncertainty):\n"
                + "\n".join("- " + x for x in safe_requests)
            )
        scenarios = bundle.pipeline_result.events.get("scenario_events", []) or []
        if scenarios:
            parts.append(
                "Requested scene events:\n"
                + "\n".join("- " + str(x.get("type")) for x in scenarios)
            )
        return "\n\n".join(parts) if parts else prompt.strip()
