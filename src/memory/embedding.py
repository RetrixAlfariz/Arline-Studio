from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from .config import EmbeddingConfig


class EmbeddingProvider(Protocol):
    @property
    def model_id(self) -> str: ...
    @property
    def dimension(self) -> int: ...
    def available(self) -> bool: ...
    def embed_query(self, text: str) -> list[float]: ...
    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(slots=True)
class DisabledEmbeddingProvider:
    configured_model: str = ""
    configured_dimension: int = 0

    @property
    def model_id(self) -> str:
        return self.configured_model

    @property
    def dimension(self) -> int:
        return self.configured_dimension

    def available(self) -> bool:
        return False

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("Dense retrieval is disabled")

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("Dense retrieval is disabled")


class LMStudioEmbeddingProvider:
    """OpenAI-compatible embedding provider served by LM Studio.

    Arline never owns model weights. The README tells users which model to
    install; LM Studio owns loading/inference and Arline only consumes vectors.
    """

    def __init__(self, *, base_url: str, api_key: str | None, config: EmbeddingConfig):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.config = config

    @property
    def model_id(self) -> str:
        return self.config.model

    @property
    def dimension(self) -> int:
        return self.config.dimension

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _endpoint(self) -> str:
        base = self.base_url
        if base.endswith("/v1"):
            return f"{base}/embeddings"
        return f"{base}/v1/embeddings"

    def available(self) -> bool:
        if not self.config.enabled or not self.config.model:
            return False
        try:
            with httpx.Client(timeout=min(10.0, self.config.timeout_seconds)) as client:
                response = client.post(
                    self._endpoint(),
                    headers=self._headers(),
                    json={"model": self.config.model, "input": [self.config.query_prefix + "health check"]},
                )
                return response.status_code < 400
        except httpx.HTTPError:
            return False

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.post(
                self._endpoint(),
                headers=self._headers(),
                json={"model": self.config.model, "input": texts},
            )
            response.raise_for_status()
            payload = response.json()
        rows = sorted(payload.get("data") or [], key=lambda item: item.get("index", 0))
        vectors = [[float(value) for value in row.get("embedding") or []] for row in rows]
        if len(vectors) != len(texts):
            raise RuntimeError("LM Studio returned an unexpected number of embeddings")
        for vector in vectors:
            if self.config.dimension and len(vector) != self.config.dimension:
                raise RuntimeError(
                    f"Embedding dimension mismatch: expected {self.config.dimension}, received {len(vector)}"
                )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self.config.query_prefix + text.strip()])[0]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        prefixed = [self.config.passage_prefix + text.strip() for text in texts]
        output: list[list[float]] = []
        batch = max(1, self.config.batch_size)
        for start in range(0, len(prefixed), batch):
            output.extend(self._embed(prefixed[start:start + batch]))
        return output


class RerankerProvider(Protocol):
    def available(self) -> bool: ...
    def rerank(self, query: str, candidates: list[dict], limit: int) -> list[dict]: ...


@dataclass(slots=True)
class DisabledRerankerProvider:
    reason: str = "Reranking is experimental and disabled by default"

    def available(self) -> bool:
        return False

    def rerank(self, query: str, candidates: list[dict], limit: int) -> list[dict]:
        return candidates[:limit]
