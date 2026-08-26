from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.inference import LMStudioClient
from src.runtime_config import RuntimeConfig


_UNSET = object()


@dataclass(slots=True)
class WriterResult:
    story: str
    reasoning: str
    model_input: str
    input_mode: str
    stats: dict[str, Any]
    raw_response: dict[str, Any]


class ArlineWriter:
    def __init__(self, config: RuntimeConfig, client: LMStudioClient | None = None):
        self.config = config
        self.client = client or LMStudioClient(
            base_url=config.lmstudio.base_url,
            api_key=config.lmstudio.api_key,
            timeout_seconds=config.lmstudio.timeout_seconds,
        )

    def generate(
        self,
        *,
        model_input: str,
        input_mode: str | None = None,
        reasoning_for_api: str | None | object = _UNSET,
        images: list[str] | None = None,
    ) -> WriterResult:
        system = self.config.writer.system_prompt_file.read_text(encoding="utf-8").strip()
        g = self.config.generation

        if g.reasoning != "off":
            guard_path = self.config.reasoning_runtime.guard_prompt_file
            if guard_path.exists():
                guard = guard_path.read_text(encoding="utf-8").strip()
                if guard:
                    system = f"{system}\n\n{guard}"

        api_reasoning = g.reasoning if reasoning_for_api is _UNSET else reasoning_for_api
        result = self.client.chat(
            model=self.config.lmstudio.model,
            input_text=model_input,
            system_prompt=system,
            temperature=g.temperature,
            top_p=g.top_p,
            top_k=g.top_k,
            min_p=g.min_p,
            max_tokens=g.api_max_output_tokens,
            repeat_penalty=g.repeat_penalty,
            reasoning=api_reasoning,
            context_length=self.config.model_load.context_length,
            seed=g.seed,
            extra_payload=g.extra,
            images=images,
        )

        stats = dict(result.stats)
        total = stats.get("total_output_tokens")
        reason = stats.get("reasoning_output_tokens", 0)
        story_tokens = None
        if isinstance(total, (int, float)) and isinstance(reason, (int, float)):
            story_tokens = max(0, int(total - reason))
            stats["story_output_tokens"] = story_tokens

        stats["visible_output_target_tokens"] = g.visible_output_tokens
        stats["reasoning_reserve_tokens"] = (
            g.reasoning_reserve_tokens if g.reasoning != "off" else 0
        )
        stats["api_max_output_tokens"] = g.api_max_output_tokens
        stats["requested_reasoning"] = g.reasoning
        stats["api_reasoning"] = api_reasoning if api_reasoning is not None else "omitted"

        if isinstance(total, (int, float)):
            stats["output_budget_usage_ratio"] = round(
                float(total) / max(1, g.api_max_output_tokens), 4
            )
            stats["likely_output_budget_cutoff"] = bool(
                total >= g.api_max_output_tokens * 0.985
            )

        if story_tokens is not None:
            target_ratio = story_tokens / max(1, g.visible_output_tokens)
            stats["story_target_ratio"] = round(target_ratio, 4)
            if isinstance(reason, (int, float)):
                reasoning_to_story = float(reason) / max(1, story_tokens)
                reasoning_share = float(reason) / max(1, float(total or 0))
                stats["reasoning_to_story_ratio"] = round(reasoning_to_story, 4)
                stats["reasoning_share"] = round(reasoning_share, 4)

                warnings: list[str] = []
                rr = self.config.reasoning_runtime
                if g.reasoning != "off" and reasoning_to_story >= rr.dominance_ratio_warn:
                    warnings.append("reasoning_dominated_visible_story")
                if g.reasoning != "off" and reasoning_share >= rr.reasoning_share_warn:
                    warnings.append("reasoning_share_high")
                if g.reasoning != "off" and target_ratio <= rr.story_target_ratio_warn:
                    warnings.append("visible_story_far_below_target")
                if warnings:
                    stats["reasoning_quality_warnings"] = warnings

        return WriterResult(
            result.text,
            result.reasoning,
            model_input,
            input_mode or self.config.writer.input_mode,
            stats,
            result.raw,
        )
