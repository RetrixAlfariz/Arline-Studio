from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Any, AsyncIterator

import httpx

from src.context import ContextBudget, ContextBudgeter, TokenCounter
from src.inference import LMStudioError, LMStudioModelManager
from src.runtime.run_state import RunEvent, RunState
from src.runtime_config import RuntimeConfig
from src.service.arline_service import AnalysisBundle, ArlineService, GenerationBundle
from src.deliberation import NarrativeDeliberation
from src.writer import ArlineWriter
from src.writer.quality import ProseQualityAnalyzer


@dataclass(slots=True)
class PreparedStreamingGeneration:
    analysis: AnalysisBundle
    model_input: str
    mode: str
    effective_reasoning: str | None
    load_status: dict[str, Any]
    system_prompt: str
    deliberation: NarrativeDeliberation


class StreamingArlineService:
    """Normalized streaming boundary for chat UIs.

    Arline owns context preparation and persistence semantics; LM Studio owns token
    generation. The browser only sees stable Arline events instead of provider-specific
    SSE event names.
    """

    def __init__(self, config: RuntimeConfig):
        self.config = config
        self.base = ArlineService(config)
        self.quality = ProseQualityAnalyzer()

    def _system_prompt(self) -> str:
        system = self.config.writer.system_prompt_file.read_text(encoding="utf-8").strip()
        if self.config.generation.reasoning != "off":
            guard_path = self.config.reasoning_runtime.guard_prompt_file
            if guard_path.exists():
                guard = guard_path.read_text(encoding="utf-8").strip()
                if guard:
                    system = f"{system}\n\n{guard}"
        return system

    async def prepare(
        self,
        prompt: str,
        *,
        mode: str | None = None,
        surface_history: Any = None,
        session_context: str | None = None,
        workspace_context: Any = None,
        beat_context: str | None = None,
    ) -> PreparedStreamingGeneration:
        mode = mode or self.config.writer.input_mode
        analysis = await asyncio.to_thread(
            self.base.analyze,
            prompt,
            surface_history=surface_history,
            workspace_context=workspace_context,
        )
        client = self.base.client()
        manager = LMStudioModelManager(self.config, rest_client=client)
        load = await asyncio.to_thread(manager.ensure_loaded)
        effective_reasoning = await asyncio.to_thread(self.base.resolve_reasoning_mode)

        system_text = self._system_prompt()
        exact_counter = await asyncio.to_thread(
            TokenCounter.from_lmstudio, self.config.lmstudio.model
        )
        budget = ContextBudget(
            model_context_length=self.config.model_load.context_length,
            max_output_tokens=self.config.generation.api_max_output_tokens,
            system_prompt_tokens=exact_counter.count(system_text) + (self.config.deliberation.max_tokens if self.config.deliberation.enabled else 0),
            safety_margin=self.config.context_budget.safety_margin,
            minimum_writer_context=self.config.context_budget.minimum_writer_context_tokens,
        )
        analysis.writer_context, analysis.rendered_context = ContextBudgeter(
            exact_counter
        ).fit(analysis.writer_context, budget)
        analysis.wcf_validation = self.base.wcf_validator.validate(
            analysis.writer_context, analysis.rendered_context.text
        )
        if mode not in {"raw", "aif_core"} and not analysis.wcf_validation.valid:
            raise ValueError(
                "Writer context validation failed: "
                + json.dumps(analysis.wcf_validation.to_dict(), ensure_ascii=False)
            )
        deliberation = await asyncio.to_thread(self.base._build_deliberation, prompt, analysis, client)
        model_input = self.base.compose_model_input(
            prompt,
            analysis,
            mode,
            session_context=session_context,
            beat_context=beat_context,
            deliberation=deliberation,
        )
        return PreparedStreamingGeneration(
            analysis=analysis,
            model_input=model_input,
            mode=mode,
            effective_reasoning=effective_reasoning,
            load_status=load,
            system_prompt=system_text,
            deliberation=deliberation,
        )

    def _payload(self, prepared: PreparedStreamingGeneration) -> dict[str, Any]:
        g = self.config.generation
        payload: dict[str, Any] = {
            "model": self.config.lmstudio.model,
            "input": prepared.model_input,
            "system_prompt": prepared.system_prompt,
            "stream": True,
            "temperature": g.temperature,
            "top_p": g.top_p,
            "max_output_tokens": g.api_max_output_tokens,
        }
        if prepared.effective_reasoning is not None:
            payload["reasoning"] = prepared.effective_reasoning
        for key, value in (
            ("top_k", g.top_k),
            ("min_p", g.min_p),
            ("repeat_penalty", g.repeat_penalty),
            ("context_length", self.config.model_load.context_length),
            ("seed", g.seed),
        ):
            if value is not None:
                payload[key] = value
        for key, value in (g.extra or {}).items():
            payload.setdefault(key, value)
        return payload

    @staticmethod
    def _writer_result_from_raw(
        raw: dict[str, Any], prepared: PreparedStreamingGeneration, config: RuntimeConfig
    ) -> Any:
        messages: list[str] = []
        thoughts: list[str] = []
        for item in raw.get("output", []) or []:
            if not isinstance(item, dict) or not isinstance(item.get("content"), str):
                continue
            if item.get("type") == "reasoning":
                thoughts.append(item["content"])
            elif item.get("type") == "message":
                messages.append(item["content"])
        if not messages:
            raise LMStudioError("LM Studio streaming response had no message output")

        stats = dict(raw.get("stats") or {})
        total = stats.get("total_output_tokens")
        reason = stats.get("reasoning_output_tokens", 0)
        story_tokens = None
        if isinstance(total, (int, float)) and isinstance(reason, (int, float)):
            story_tokens = max(0, int(total - reason))
            stats["story_output_tokens"] = story_tokens
        g = config.generation
        stats["visible_output_target_tokens"] = g.visible_output_tokens
        stats["reasoning_reserve_tokens"] = g.reasoning_reserve_tokens if g.reasoning != "off" else 0
        stats["api_max_output_tokens"] = g.api_max_output_tokens
        stats["requested_reasoning"] = g.reasoning
        stats["api_reasoning"] = prepared.effective_reasoning if prepared.effective_reasoning is not None else "omitted"
        stats["run_status"] = "completed"
        if isinstance(total, (int, float)):
            stats["output_budget_usage_ratio"] = round(float(total) / max(1, g.api_max_output_tokens), 4)
            stats["likely_output_budget_cutoff"] = bool(total >= g.api_max_output_tokens * 0.985)
        if story_tokens is not None:
            stats["story_target_ratio"] = round(story_tokens / max(1, g.visible_output_tokens), 4)

        from src.writer.adapter import WriterResult
        return WriterResult(
            "\n".join(messages).strip(),
            "\n".join(thoughts).strip(),
            prepared.model_input,
            prepared.mode,
            stats,
            raw,
        )

    async def stream(
        self,
        prompt: str,
        *,
        mode: str | None = None,
        session_context: str | None = None,
        workspace_context: Any = None,
    ) -> AsyncIterator[dict[str, Any]]:
        yield RunEvent("stage", RunState.PREPARING, "Preparing story context").to_dict()
        prepared = await self.prepare(
            prompt,
            mode=mode,
            session_context=session_context,
            workspace_context=workspace_context,
        )
        yield {"type": "_prepared", "prepared": prepared}
        yield RunEvent("stage", RunState.LOADING_MODEL, "Model ready").to_dict()

        client = self.base.client()
        url = client.base_url + "/api/v1/chat"
        raw_final: dict[str, Any] | None = None
        current_event = "message"
        data_lines: list[str] = []

        async def dispatch() -> list[dict[str, Any]]:
            nonlocal raw_final, data_lines, current_event
            if not data_lines:
                return []
            raw_data = "\n".join(data_lines)
            data_lines = []
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                data = {"content": raw_data}
            event_type = current_event
            current_event = "message"
            out: list[dict[str, Any]] = []
            if event_type.startswith("model_load"):
                progress = data.get("progress") if isinstance(data, dict) else None
                out.append(RunEvent("stage", RunState.LOADING_MODEL, "Loading model", progress).to_dict())
            elif event_type.startswith("prompt_processing"):
                progress = data.get("progress") if isinstance(data, dict) else None
                out.append(RunEvent("stage", RunState.PROCESSING_PROMPT, "Processing prompt", progress).to_dict())
            elif event_type == "reasoning.start":
                out.append(RunEvent("stage", RunState.THINKING, "Thinking").to_dict())
            elif event_type == "reasoning.delta":
                out.append({"type": "reasoning.delta", "content": str(data.get("content", ""))})
            elif event_type == "message.start":
                out.append(RunEvent("stage", RunState.STREAMING, "Writing").to_dict())
            elif event_type == "message.delta":
                out.append({"type": "answer.delta", "content": str(data.get("content", ""))})
            elif event_type == "error":
                raise LMStudioError(str(data.get("message") or data.get("error") or data))
            elif event_type == "chat.end":
                raw_final = dict(data.get("result") or {})
            return out

        timeout = httpx.Timeout(self.config.lmstudio.timeout_seconds, connect=30.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=client.headers) as http:
                async with http.stream("POST", url, json=self._payload(prepared)) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line == "":
                            for item in await dispatch():
                                yield item
                            continue
                        if line.startswith("event:"):
                            current_event = line[6:].strip() or "message"
                        elif line.startswith("data:"):
                            data_lines.append(line[5:].lstrip())
                    for item in await dispatch():
                        yield item
        except httpx.HTTPStatusError as exc:
            raise LMStudioError(
                f"LM Studio HTTP {exc.response.status_code}: {exc.response.text[:1000]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LMStudioError(f"LM Studio streaming request failed at {url}: {exc}") from exc

        if raw_final is None:
            raise LMStudioError("LM Studio stream ended without chat.end")
        writer_result = self._writer_result_from_raw(raw_final, prepared, self.config)
        yield RunEvent("stage", RunState.POSTPROCESSING, "Checking prose quality").to_dict()
        post = (
            await asyncio.to_thread(
                self.base.post_validator.validate,
                writer_result.story,
                prepared.analysis.writer_context,
            )
            if self.config.writer.post_validate
            else None
        )
        generation = GenerationBundle(
            prepared.analysis,
            writer_result.story,
            writer_result.reasoning,
            writer_result.stats,
            writer_result.raw_response,
            post,
            prepared.model_input,
            prepared.load_status,
            prepared.deliberation,
        )
        quality = self.quality.analyze(generation.story)
        yield {"type": "_complete", "bundle": generation, "quality": quality, "prepared": prepared}
