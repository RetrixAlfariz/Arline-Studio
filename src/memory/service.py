from __future__ import annotations

from typing import Any
from threading import RLock, Timer

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
        self._refresh_lock = RLock()
        self._refresh_timers: dict[str, Timer] = {}


    def _incremental_generation_id(self) -> int | None:
        if not self.config.dense_enabled:
            return None
        generation = self.store.active_generation()
        if generation is None:
            return None
        try:
            return int(generation["generation_id"]) if self.embedding.available() else None
        except Exception:
            return None

    def refresh_document(self, document_id: str) -> list[dict[str, Any]]:
        document = self.workspace.get_document(document_id)
        return self.indexer.index_document(
            document,
            generation_id=self._incremental_generation_id(),
        )

    def refresh_turn(self, turn_id: str) -> list[dict[str, Any]]:
        turn = self.history.get_turn(turn_id)
        session = self.history.get_session_meta(turn["session_id"])
        scoped = {
            **turn,
            "project_id": session.get("project_id"),
            "world_id": session.get("world_id"),
            "branch_id": session.get("branch_id"),
            "scratch_mode": session.get("scratch_mode"),
            "parent_session_id": session.get("parent_session_id"),
            "forked_from_turn_id": session.get("forked_from_turn_id"),
        }
        return self.indexer.index_turn(
            scoped,
            generation_id=self._incremental_generation_id(),
        )

    def _schedule(self, key: str, callback, delay: float) -> None:
        def run() -> None:
            try:
                callback()
            except Exception:
                pass
            finally:
                with self._refresh_lock:
                    self._refresh_timers.pop(key, None)
        with self._refresh_lock:
            previous = self._refresh_timers.pop(key, None)
            if previous is not None:
                previous.cancel()
            timer = Timer(max(0.05, float(delay)), run)
            timer.daemon = True
            self._refresh_timers[key] = timer
            timer.start()

    def schedule_document_refresh(self, document_id: str, delay: float = 0.75) -> None:
        self._schedule(f"document:{document_id}", lambda: self.refresh_document(document_id), delay)

    def schedule_turn_refresh(self, turn_id: str, delay: float = 0.1) -> None:
        self._schedule(f"turn:{turn_id}", lambda: self.refresh_turn(turn_id), delay)

    def forget_document(self, document_id: str) -> int:
        return self.store.mark_source_status("document", document_id, "deleted")

    def forget_session(self, session_id: str) -> int:
        return self.store.mark_session_status(session_id, "deleted")

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
            "fallback_active": bool(self.config.dense_enabled and not embedding_available),
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
