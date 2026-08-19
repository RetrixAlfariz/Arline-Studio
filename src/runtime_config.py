from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import tomllib
from typing import Any

DEFAULT_CONFIG_PATH = Path("config/arline.toml")
VALID_INPUT_MODES = {"smart_hybrid", "wcf", "raw", "wcf_raw", "aif_core"}
VALID_REASONING = {"off", "on", "low", "medium", "high"}
VALID_PROJECTION_MODES = {"off", "conservative", "balanced", "vivid"}
VALID_GENERATION_MODES = {"single", "beats"}


@dataclass(slots=True)
class LMStudioConfig:
    base_url: str = "http://127.0.0.1:1234"
    model: str = ""
    api_key: str = ""
    timeout_seconds: float = 600
    auto_load: bool = True


@dataclass(slots=True)
class ModelLoadConfig:
    gpu_ratio: float = 1.0
    context_length: int = 32768
    flash_attention: bool = True


@dataclass(slots=True)
class GenerationConfig:
    temperature: float = 0.8
    top_p: float = 0.95
    top_k: int | None = 40
    min_p: float | None = 0.0
    repeat_penalty: float | None = 1.05
    reasoning: str = "off"
    visible_output_tokens: int = 4096
    reasoning_reserve_tokens: int = 4096
    generation_mode: str = "single"
    beat_count: int = 4
    beat_tokens: int = 2048
    total_story_target_tokens: int = 8192
    seed: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def api_max_output_tokens(self) -> int:
        """LM Studio's max_output_tokens includes reasoning + visible prose."""
        if self.reasoning == "off":
            return self.visible_output_tokens
        return self.visible_output_tokens + self.reasoning_reserve_tokens

    @property
    def max_tokens(self) -> int:
        """Backward-compatible alias for code that means total API output budget."""
        return self.api_max_output_tokens


@dataclass(slots=True)
class WriterConfig:
    input_mode: str = "smart_hybrid"
    system_prompt_file: Path = Path("writer_system.txt")
    story_filename: str = "story.txt"
    save_request_packet: bool = True
    post_validate: bool = True


@dataclass(slots=True)
class ContextBudgetConfig:
    safety_margin: int = 1536
    minimum_writer_context_tokens: int = 2048
    system_prompt_token_estimate: int = 1400


@dataclass(slots=True)
class ReasoningBudgetConfig:
    max_depth: int = 4
    max_nodes: int = 500
    min_confidence: float = 0.35
    min_relevance: float = 0.25


@dataclass(slots=True)
class ProjectionConfig:
    mode: str = "balanced"
    min_confidence: float = 0.5
    max_items: int = 12


@dataclass(slots=True)
class ReasoningRuntimeConfig:
    # Native LM Studio reasoning is model-specific. Arline validates the
    # selected option against GET /api/v1/models before generation.
    enforce_model_capabilities: bool = True
    guard_prompt_file: Path = Path("reasoning_guard.txt")
    dominance_ratio_warn: float = 2.0
    reasoning_share_warn: float = 0.65
    story_target_ratio_warn: float = 0.35


@dataclass(slots=True)
class ArtifactConfig:
    output_root: Path = Path("output")
    saved_root: Path = Path("output/saved")


@dataclass(slots=True)
class HistoryConfig:
    database_path: Path = Path("data/arline_history.db")
    dataset_root: Path = Path("data/datasets")
    recent_limit: int = 100
    continuity_turns: int = 2
    continuity_chars: int = 12000
    smart_hybrid_continuity: bool = True


@dataclass(slots=True)
class WorkspaceConfig:
    database_path: Path = Path("data/arline_history.db")
    default_project_id: str | None = None
    context_enabled: bool = True
    mention_limit: int = 20
    pinned_context_limit: int = 24
    autosave_drafts: bool = True
    language_mode: str = "follow_prompt"


@dataclass(slots=True)
class UIConfig:
    host: str = "127.0.0.1"
    port: int = 7860
    show_reasoning: bool = True


@dataclass(slots=True)
class RuntimeConfig:
    path: Path
    lmstudio: LMStudioConfig
    model_load: ModelLoadConfig
    generation: GenerationConfig
    writer: WriterConfig
    context_budget: ContextBudgetConfig
    reasoning_budget: ReasoningBudgetConfig
    projection: ProjectionConfig
    reasoning_runtime: ReasoningRuntimeConfig
    artifacts: ArtifactConfig
    history: HistoryConfig
    workspace: WorkspaceConfig
    ui: UIConfig

    @staticmethod
    def normalize_server_url(value: str) -> str:
        value = value.strip().rstrip("/")
        for suffix in ("/v1", "/api/v1"):
            if value.endswith(suffix):
                value = value[:-len(suffix)]
        return value.rstrip("/")

    @staticmethod
    def portable_path(value: str) -> Path:
        """Interpret config paths consistently on Windows, Linux, and WSL.

        Older Arline configs used Windows backslashes. On POSIX, ``Path`` treats
        those as literal filename characters, which could create a file named
        ``data\\arline_history.db`` beside the source tree. Normalize only on
        non-Windows hosts so existing Windows behavior stays unchanged.
        """
        text = str(value).strip()
        if os.name != "nt":
            text = text.replace("\\", "/")
        return Path(text)

    @classmethod
    def load(cls, path: Path | str = DEFAULT_CONFIG_PATH):
        path = Path(path)
        with path.open("rb") as fh:
            raw = tomllib.load(fh)

        lm = raw.get("lmstudio", {})
        load = raw.get("model_load", {})
        gen = raw.get("generation", {})
        wr = raw.get("writer", {})
        cb = raw.get("context_budget", {})
        rb = raw.get("reasoning_budget", {})
        proj = raw.get("projection", {})
        rr = raw.get("reasoning_runtime", {})
        art = raw.get("artifacts", {})
        hist = raw.get("history", {})
        ws = raw.get("workspace", {})
        ui = raw.get("ui", {})

        mode = str(wr.get("input_mode", "smart_hybrid"))
        reasoning = str(gen.get("reasoning", "off")).lower()
        if mode not in VALID_INPUT_MODES:
            raise ValueError(f"writer.input_mode must be one of {sorted(VALID_INPUT_MODES)}")
        if reasoning not in VALID_REASONING:
            raise ValueError(f"generation.reasoning must be one of {sorted(VALID_REASONING)}")
        generation_mode = str(gen.get("generation_mode", "single")).lower()
        if generation_mode not in VALID_GENERATION_MODES:
            raise ValueError(f"generation.generation_mode must be one of {sorted(VALID_GENERATION_MODES)}")
        projection_mode = str(proj.get("mode", "balanced")).lower()
        if projection_mode not in VALID_PROJECTION_MODES:
            raise ValueError(
                f"projection.mode must be one of {sorted(VALID_PROJECTION_MODES)}"
            )

        prompt_path = Path(str(wr.get("system_prompt_file", "writer_system.txt")))
        if not prompt_path.is_absolute():
            prompt_path = path.parent / prompt_path
        reasoning_guard_path = Path(str(rr.get("guard_prompt_file", "reasoning_guard.txt")))
        if not reasoning_guard_path.is_absolute():
            reasoning_guard_path = path.parent / reasoning_guard_path

        seed = gen.get("seed", -1)
        seed = None if seed in (-1, None) else int(seed)
        gpu = float(load.get("gpu_ratio", 1.0))
        if not 0 <= gpu <= 1:
            raise ValueError("gpu_ratio must be between 0 and 1")

        # v0.5 migration: old max_tokens becomes the visible target if the new
        # field does not exist. This avoids silently changing old configs.
        visible = int(gen.get("visible_output_tokens", gen.get("max_tokens", 4096)))
        reserve = int(gen.get("reasoning_reserve_tokens", 4096))
        if visible <= 0 or reserve < 0:
            raise ValueError("generation output budgets must be positive")

        return cls(
            path=path,
            lmstudio=LMStudioConfig(
                base_url=cls.normalize_server_url(os.getenv(
                    "ARLINE_LMSTUDIO_BASE_URL",
                    str(lm.get("base_url", "http://127.0.0.1:1234")),
                )),
                model=os.getenv("ARLINE_MODEL", str(lm.get("model", ""))).strip(),
                api_key=os.getenv("ARLINE_LMSTUDIO_API_KEY", str(lm.get("api_key", ""))).strip(),
                timeout_seconds=float(lm.get("timeout_seconds", 600)),
                auto_load=bool(lm.get("auto_load", True)),
            ),
            model_load=ModelLoadConfig(
                gpu_ratio=gpu,
                context_length=int(load.get("context_length", 32768)),
                flash_attention=bool(load.get("flash_attention", True)),
            ),
            generation=GenerationConfig(
                temperature=float(gen.get("temperature", 0.8)),
                top_p=float(gen.get("top_p", 0.95)),
                top_k=None if gen.get("top_k") is None else int(gen.get("top_k")),
                min_p=None if gen.get("min_p") is None else float(gen.get("min_p")),
                repeat_penalty=None if gen.get("repeat_penalty") is None else float(gen.get("repeat_penalty")),
                reasoning=reasoning,
                visible_output_tokens=visible,
                reasoning_reserve_tokens=reserve,
                generation_mode=generation_mode,
                beat_count=max(1, int(gen.get("beat_count", 4))),
                beat_tokens=max(256, int(gen.get("beat_tokens", 2048))),
                total_story_target_tokens=max(256, int(gen.get("total_story_target_tokens", 8192))),
                seed=seed,
                extra=dict(gen.get("extra", {})),
            ),
            writer=WriterConfig(
                input_mode=mode,
                system_prompt_file=prompt_path,
                story_filename=str(wr.get("story_filename", "story.txt")),
                save_request_packet=bool(wr.get("save_request_packet", True)),
                post_validate=bool(wr.get("post_validate", True)),
            ),
            context_budget=ContextBudgetConfig(
                safety_margin=int(cb.get("safety_margin", 1536)),
                minimum_writer_context_tokens=int(cb.get("minimum_writer_context_tokens", 2048)),
                system_prompt_token_estimate=int(cb.get("system_prompt_token_estimate", 1400)),
            ),
            reasoning_budget=ReasoningBudgetConfig(
                max_depth=int(rb.get("max_depth", 4)),
                max_nodes=int(rb.get("max_nodes", 500)),
                min_confidence=float(rb.get("min_confidence", 0.35)),
                min_relevance=float(rb.get("min_relevance", 0.25)),
            ),
            projection=ProjectionConfig(
                mode=projection_mode,
                min_confidence=float(proj.get("min_confidence", 0.5)),
                max_items=int(proj.get("max_items", 12)),
            ),
            reasoning_runtime=ReasoningRuntimeConfig(
                enforce_model_capabilities=bool(rr.get("enforce_model_capabilities", True)),
                guard_prompt_file=reasoning_guard_path,
                dominance_ratio_warn=float(rr.get("dominance_ratio_warn", 2.0)),
                reasoning_share_warn=float(rr.get("reasoning_share_warn", 0.65)),
                story_target_ratio_warn=float(rr.get("story_target_ratio_warn", 0.35)),
            ),
            artifacts=ArtifactConfig(
                output_root=cls.portable_path(str(art.get("output_root", "output"))),
                saved_root=cls.portable_path(str(art.get("saved_root", "output/saved"))),
            ),
            history=HistoryConfig(
                database_path=cls.portable_path(str(hist.get("database_path", "data/arline_history.db"))),
                dataset_root=cls.portable_path(str(hist.get("dataset_root", "data/datasets"))),
                recent_limit=int(hist.get("recent_limit", 100)),
                continuity_turns=int(hist.get("continuity_turns", 2)),
                continuity_chars=int(hist.get("continuity_chars", 12000)),
                smart_hybrid_continuity=bool(hist.get("smart_hybrid_continuity", True)),
            ),
            workspace=WorkspaceConfig(
                database_path=cls.portable_path(str(ws.get("database_path", hist.get("database_path", "data/arline_history.db")))),
                default_project_id=(str(ws.get("default_project_id", "")).strip() or None),
                context_enabled=bool(ws.get("context_enabled", True)),
                mention_limit=int(ws.get("mention_limit", 20)),
                pinned_context_limit=int(ws.get("pinned_context_limit", 24)),
                autosave_drafts=bool(ws.get("autosave_drafts", True)),
                language_mode=str(ws.get("language_mode", "follow_prompt")),
            ),
            ui=UIConfig(
                host=str(ui.get("host", "127.0.0.1")),
                port=int(ui.get("port", 7860)),
                show_reasoning=bool(ui.get("show_reasoning", True)),
            ),
        )

    @property
    def reasoning_enabled(self) -> bool:
        return self.generation.reasoning != "off"

    def save_runtime_values(self):
        try:
            import tomlkit
        except ImportError as exc:
            raise RuntimeError("Saving config requires tomlkit") from exc

        doc = tomlkit.parse(self.path.read_text(encoding="utf-8"))
        for section in (
            "lmstudio", "model_load", "generation", "writer",
            "context_budget", "reasoning_budget", "projection", "reasoning_runtime", "artifacts", "history", "workspace", "ui",
        ):
            doc.setdefault(section, tomlkit.table())

        # API keys are runtime secrets. They may come from the environment
        # or a transient UI request, but saving ordinary settings must never
        # copy them into the portable TOML file.
        doc["lmstudio"].update({
            "base_url": self.lmstudio.base_url,
            "model": self.lmstudio.model,
            "api_key": "",
            "timeout_seconds": self.lmstudio.timeout_seconds,
            "auto_load": self.lmstudio.auto_load,
        })
        doc["model_load"].update({
            "gpu_ratio": self.model_load.gpu_ratio,
            "context_length": self.model_load.context_length,
            "flash_attention": self.model_load.flash_attention,
        })
        gen = doc["generation"]
        # Remove the old ambiguous field when saving a v0.6 config.
        if "max_tokens" in gen:
            del gen["max_tokens"]
        gen.update({
            "temperature": self.generation.temperature,
            "top_p": self.generation.top_p,
            "top_k": self.generation.top_k,
            "min_p": self.generation.min_p,
            "repeat_penalty": self.generation.repeat_penalty,
            "reasoning": self.generation.reasoning,
            "visible_output_tokens": self.generation.visible_output_tokens,
            "reasoning_reserve_tokens": self.generation.reasoning_reserve_tokens,
            "generation_mode": self.generation.generation_mode,
            "beat_count": self.generation.beat_count,
            "beat_tokens": self.generation.beat_tokens,
            "total_story_target_tokens": self.generation.total_story_target_tokens,
            "seed": -1 if self.generation.seed is None else self.generation.seed,
        })
        doc["projection"].update({
            "mode": self.projection.mode,
            "min_confidence": self.projection.min_confidence,
            "max_items": self.projection.max_items,
        })
        doc["reasoning_runtime"].update({
            "enforce_model_capabilities": self.reasoning_runtime.enforce_model_capabilities,
            "guard_prompt_file": self.reasoning_runtime.guard_prompt_file.name,
            "dominance_ratio_warn": self.reasoning_runtime.dominance_ratio_warn,
            "reasoning_share_warn": self.reasoning_runtime.reasoning_share_warn,
            "story_target_ratio_warn": self.reasoning_runtime.story_target_ratio_warn,
        })
        doc["writer"].update({
            "input_mode": self.writer.input_mode,
            "story_filename": self.writer.story_filename,
            "save_request_packet": self.writer.save_request_packet,
            "post_validate": self.writer.post_validate,
        })
        doc["context_budget"].update({
            "safety_margin": self.context_budget.safety_margin,
            "minimum_writer_context_tokens": self.context_budget.minimum_writer_context_tokens,
            "system_prompt_token_estimate": self.context_budget.system_prompt_token_estimate,
        })
        doc["reasoning_budget"].update({
            "max_depth": self.reasoning_budget.max_depth,
            "max_nodes": self.reasoning_budget.max_nodes,
            "min_confidence": self.reasoning_budget.min_confidence,
            "min_relevance": self.reasoning_budget.min_relevance,
        })
        doc["artifacts"].update({
            "output_root": str(self.artifacts.output_root),
            "saved_root": str(self.artifacts.saved_root),
        })
        doc["history"].update({
            "database_path": str(self.history.database_path),
            "dataset_root": str(self.history.dataset_root),
            "recent_limit": self.history.recent_limit,
            "continuity_turns": self.history.continuity_turns,
            "continuity_chars": self.history.continuity_chars,
            "smart_hybrid_continuity": self.history.smart_hybrid_continuity,
        })
        doc["workspace"].update({
            "database_path": str(self.workspace.database_path),
            "default_project_id": self.workspace.default_project_id or "",
            "context_enabled": self.workspace.context_enabled,
            "mention_limit": self.workspace.mention_limit,
            "pinned_context_limit": self.workspace.pinned_context_limit,
            "autosave_drafts": self.workspace.autosave_drafts,
            "language_mode": self.workspace.language_mode,
        })
        doc["ui"].update({
            "host": self.ui.host,
            "port": self.ui.port,
            "show_reasoning": self.ui.show_reasoning,
        })
        self.path.write_text(tomlkit.dumps(doc), encoding="utf-8")
