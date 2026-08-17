from __future__ import annotations

from typing import Any

from .config import MemoryConfig
from .embedding import DisabledEmbeddingProvider, DisabledRerankerProvider, LMStudioEmbeddingProvider
from .index import MemoryIndexer
from .models import MemoryQueryContext, RetrievalResult
from .query import MemoryQueryEngine
from .store import MemoryStore


class MemoryService:
    def __init__(self, *, store: MemoryStore, workspace, history, foundation,
                 config: MemoryConfig, lmstudio_base_url: str, lmstudio_api_key: str | None = None):
        self.store = store
        self.workspace = workspace
        self.history = history
        self.foundation = foundation
        self.config = config
        if config.dense_enabled and config.embedding.enabled and config.embedding.provider == "lmstudio":
            embedding = LMStudioEmbeddingProvider(
                base_url=lmstudio_base_url,
                api_key=lmstudio_api_key,
                config=config.embedding,
            )
        else:
            embedding = DisabledEmbeddingProvider(config.embedding.model, config.embedding.dimension)
        self.embedding = embedding
        self.reranker = DisabledRerankerProvider(
            "LM Studio does not expose a native rerank endpoint; v1.2 uses RRF by default."
        )
        self.indexer = MemoryIndexer(
            store=store, workspace=workspace, history=history, foundation=foundation,
            config=config, embedding=embedding,
        )
        self.query_engine = MemoryQueryEngine(
            store=store, workspace=workspace, history=history, foundation=foundation,
            config=config, embedding=embedding, reranker=self.reranker,
        )

    def status(self) -> dict[str, Any]:
        embedding_available = False
        if self.config.dense_enabled:
            try:
                embedding_available = self.embedding.available()
            except Exception:
                embedding_available = False
        return {
            **self.store.status(),
            "enabled": self.config.enabled,
            "automatic_context": self.config.automatic_context,
            "config": self.config.to_dict(),
            "embedding_available": embedding_available,
            "fallback_active": not embedding_available,
            "fallback": "structured indexes + SQLite FTS5",
            "reranker_available": self.reranker.available(),
        }

    def backfill(self, project_id: str | None = None) -> dict[str, Any]:
        return self.indexer.backfill(project_id)

    def retrieve(self, query: str, context: MemoryQueryContext) -> RetrievalResult:
        if not self.config.enabled or not query.strip():
            from .models import QueryPlan, QueryRoute
            plan = QueryPlan(QueryRoute.TEXT_RECALL, context, normalized_query=query.strip())
            return RetrievalResult("disabled", plan, [], [], "", {}, True, "Memory retrieval is disabled.")
        return self.query_engine.execute(query, context)

    def augment_workspace_context(self, workspace_context, result: RetrievalResult):
        if not result.packed_text:
            workspace_context.scope["memory"] = {
                "run_id": result.run_id,
                "route": result.plan.route.value,
                "selected": 0,
                "excluded": len(result.excluded),
                "abstain": result.abstain,
                "reason": result.abstention_reason,
            }
            return workspace_context
        workspace_context.text = (
            workspace_context.text.rstrip() + "\n\n" + result.packed_text.rstrip() + "\n"
        )
        workspace_context.estimated_tokens += max(1, len(result.packed_text) // 4)
        workspace_context.scope["memory"] = {
            "run_id": result.run_id,
            "route": result.plan.route.value,
            "lens": result.plan.scope.context_lens.value,
            "selected": len(result.selected),
            "excluded": len(result.excluded),
            "lane_counts": result.lane_counts,
            "abstain": result.abstain,
            "diagnostics": result.diagnostics,
            "selected_sources": [
                {"id": item.id, "lane": item.lane.value, "source_type": item.source_type,
                 "source_id": item.source_id, "score": round(item.score, 6), "ranks": item.ranks}
                for item in result.selected
            ],
            "excluded_preview": result.excluded[:20],
        }
        return workspace_context
