from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RunState(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    LOADING_MODEL = "loading_model"
    PROCESSING_PROMPT = "processing_prompt"
    THINKING = "thinking"
    STREAMING = "streaming"
    POSTPROCESSING = "postprocessing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(slots=True)
class RunEvent:
    type: str
    state: RunState | None = None
    content: str = ""
    progress: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.type}
        if self.state is not None:
            payload["state"] = self.state.value
        if self.content:
            payload["content"] = self.content
        if self.progress is not None:
            payload["progress"] = max(0.0, min(1.0, float(self.progress)))
        if self.detail:
            payload.update(self.detail)
        return payload
