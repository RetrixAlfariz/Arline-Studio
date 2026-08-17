from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator, Protocol


@dataclass(slots=True)
class ModelCapabilities:
    provider: str
    context_window: int | None = None
    streaming: bool = False
    separate_reasoning_stream: bool = False
    reasoning_modes: list[str] = field(default_factory=list)
    structured_output: bool = False
    tool_support: bool = False
    sampling_controls: list[str] = field(default_factory=lambda: [
        "temperature", "top_p", "top_k", "min_p", "repeat_penalty"
    ])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InferenceProvider(Protocol):
    def list_models(self) -> list[dict[str, Any]]: ...
    def model_info(self, key: str) -> dict[str, Any] | None: ...
    def capabilities(self, key: str) -> ModelCapabilities: ...
    async def stream_chat(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]: ...
