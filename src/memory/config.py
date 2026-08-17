from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib
from typing import Any


@dataclass(slots=True)
class EmbeddingConfig:
    enabled: bool = False
    provider: str = "lmstudio"
    model: str = "intfloat/multilingual-e5-base"
    dimension: int = 768
    query_prefix: str = "query: "
    passage_prefix: str = "passage: "
    batch_size: int = 32
    timeout_seconds: float = 120.0


@dataclass(slots=True)
class RerankerConfig:
    enabled: bool = False
    provider: str = "disabled"
    model: str = "Qwen/Qwen3-Reranker-0.6B"
    top_k_input: int = 20
    top_k_output: int = 8


@dataclass(slots=True)
class MemoryConfig:
    enabled: bool = True
    fts_enabled: bool = True
    dense_enabled: bool = False
    automatic_context: bool = True
    default_lens: str = "scene"
    chunk_chars: int = 1800
    chunk_overlap_chars: int = 180
    max_candidates: int = 60
    final_k: int = 12
    max_per_source: int = 2
    rrf_k: int = 60
    trace_enabled: bool = True
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    reranker: RerankerConfig = field(default_factory=RerankerConfig)

    @classmethod
    def load(cls, config_path: Path | str) -> "MemoryConfig":
        path = Path(config_path)
        raw: dict[str, Any] = {}
        if path.exists():
            with path.open("rb") as handle:
                raw = tomllib.load(handle)
        memory = raw.get("memory") or {}
        embedding = memory.get("embedding") or raw.get("memory_embedding") or {}
        reranker = memory.get("reranker") or raw.get("memory_reranker") or {}
        dense_enabled = bool(memory.get("dense_enabled", embedding.get("enabled", False)))
        return cls(
            enabled=bool(memory.get("enabled", True)),
            fts_enabled=bool(memory.get("fts_enabled", True)),
            dense_enabled=dense_enabled,
            automatic_context=bool(memory.get("automatic_context", True)),
            default_lens=str(memory.get("default_lens", "scene")),
            chunk_chars=max(400, int(memory.get("chunk_chars", 1800))),
            chunk_overlap_chars=max(0, int(memory.get("chunk_overlap_chars", 180))),
            max_candidates=max(8, int(memory.get("max_candidates", 60))),
            final_k=max(1, int(memory.get("final_k", 12))),
            max_per_source=max(1, int(memory.get("max_per_source", 2))),
            rrf_k=max(1, int(memory.get("rrf_k", 60))),
            trace_enabled=bool(memory.get("trace_enabled", True)),
            embedding=EmbeddingConfig(
                enabled=bool(embedding.get("enabled", dense_enabled)),
                provider=str(embedding.get("provider", "lmstudio")),
                model=str(embedding.get("model", "intfloat/multilingual-e5-base")),
                dimension=max(1, int(embedding.get("dimension", 768))),
                query_prefix=str(embedding.get("query_prefix", "query: ")),
                passage_prefix=str(embedding.get("passage_prefix", "passage: ")),
                batch_size=max(1, int(embedding.get("batch_size", 32))),
                timeout_seconds=max(1.0, float(embedding.get("timeout_seconds", 120.0))),
            ),
            reranker=RerankerConfig(
                enabled=bool(reranker.get("enabled", False)),
                provider=str(reranker.get("provider", "disabled")),
                model=str(reranker.get("model", "Qwen/Qwen3-Reranker-0.6B")),
                top_k_input=max(1, int(reranker.get("top_k_input", 20))),
                top_k_output=max(1, int(reranker.get("top_k_output", 8))),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "fts_enabled": self.fts_enabled,
            "dense_enabled": self.dense_enabled,
            "automatic_context": self.automatic_context,
            "default_lens": self.default_lens,
            "chunk_chars": self.chunk_chars,
            "chunk_overlap_chars": self.chunk_overlap_chars,
            "max_candidates": self.max_candidates,
            "final_k": self.final_k,
            "max_per_source": self.max_per_source,
            "rrf_k": self.rrf_k,
            "trace_enabled": self.trace_enabled,
            "embedding": {
                "enabled": self.embedding.enabled,
                "provider": self.embedding.provider,
                "model": self.embedding.model,
                "dimension": self.embedding.dimension,
                "query_prefix": self.embedding.query_prefix,
                "passage_prefix": self.embedding.passage_prefix,
                "batch_size": self.embedding.batch_size,
                "timeout_seconds": self.embedding.timeout_seconds,
            },
            "reranker": {
                "enabled": self.reranker.enabled,
                "provider": self.reranker.provider,
                "model": self.reranker.model,
                "top_k_input": self.reranker.top_k_input,
                "top_k_output": self.reranker.top_k_output,
            },
        }
