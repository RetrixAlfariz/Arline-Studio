
from __future__ import annotations

from typing import Any
from threading import RLock, Timer

from .config import MemoryConfig
from .embedding import DisabledEmbeddingProvider, DisabledRerankerProvider, LMStudioEmbeddingProvider
from .index import MemoryIndexer
from .models import MemoryQueryContext, RetrievalResult
from .query import MemoryQueryEngine
from .store import MemoryStore
from src.context.intelligence import NarrativeContextPlanner


class MemoryService:
    def __init__(self, *, store: MemoryStore, workspace, history, foundation,
                 config: MemoryConfig, lmstudio_base_url: str, lmstudio_api_key: str | None = None):
        self.store = store
        self.workspace = workspace
        self.history = history
        self.foundation = foundation
        self.config = config
        if config.dense_enabled and config.embedding.enabled and config.embedding.provider == "lmstudio":
            embedding = LMStudioEmbeddingProvider(base_url=lmstudio_base_url, api_key=lmstudio_api_key, config=config.embedding)
        else:
            embedding = DisabledEmbeddingProvider(config.embedding.model, config.embedding.dimension)
        self.embedding = embedding
        reason = "Reranking disabled by configuration." if not config.reranker.enabled else (
            f"Reranker provider {config.reranker.provider!r} is not available in v1.2.0; RRF remains active."
        )
        self.reranker = DisabledRerankerProvider(reason)
        self.indexer = MemoryIndexer(store=store, workspace=workspace, history=history, foundation=foundation,
                                     config=config, embedding=embedding)
        self.query_engine = MemoryQueryEngine(store=store, workspace=workspace, history=history, foundation=foundation,
                                              config=config, embedding=embedding, reranker=self.reranker)
        self.context_planner = NarrativeContextPlanner()
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
        if not self.config.enabled:
            return []
        document = self.workspace.get_document(document_id)
        return self.indexer.index_document(document, generation_id=self._incremental_generation_id())

    def refresh_turn(self, turn_id: str) -> list[dict[str, Any]]:
        if not self.config.enabled:
            return []
        turn = self.history.get_turn(turn_id)
        session = self.history.get_session_meta(turn["session_id"])
        scoped = {**turn, "project_id": session.get("project_id"), "world_id": session.get("world_id"),
                  "branch_id": session.get("branch_id"), "scratch_mode": session.get("scratch_mode"),
                  "parent_session_id": session.get("parent_session_id"), "forked_from_turn_id": session.get("forked_from_turn_id")}
        return self.indexer.index_turn(scoped, generation_id=self._incremental_generation_id())

    def _report_refresh_failure(self, key: str, exc: Exception) -> None:
        if isinstance(exc, KeyError):
            return  # deleted/cancelled source; lifecycle cleanup is expected.
        resource_type, _, resource_id = key.partition(":")
        try:
            self.foundation.create_issue(
                issue_type="memory_index_refresh_failed", title="Memory index refresh failed",
                severity="warning", description=str(exc), resource_type=resource_type or "memory",
                resource_id=resource_id or None, payload={"refresh_key": key, "error": repr(exc)},
            )
        except Exception:
            pass
        try:
            self.foundation.log_activity(None, "memory_index_refresh_failed", resource_type or "memory", resource_id or None,
                                         label="Memory refresh failed", detail={"error": str(exc)})
        except Exception:
            pass

    def _schedule(self, key: str, callback, delay: float) -> None:
        if not self.config.enabled:
            return
        def run() -> None:
            try:
                callback()
            except Exception as exc:
                self._report_refresh_failure(key, exc)
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

    def _cancel(self, key: str) -> None:
        with self._refresh_lock:
            timer = self._refresh_timers.pop(key, None)
            if timer is not None:
                timer.cancel()

    def schedule_document_refresh(self, document_id: str, delay: float = 0.75) -> None:
        self._schedule(f"document:{document_id}", lambda: self.refresh_document(document_id), delay)

    def schedule_turn_refresh(self, turn_id: str, delay: float = 0.1) -> None:
        self._schedule(f"turn:{turn_id}", lambda: self.refresh_turn(turn_id), delay)

    def cancel_document_refresh(self, document_id: str) -> None:
        self._cancel(f"document:{document_id}")

    def cancel_session_refreshes(self, session_id: str) -> None:
        try:
            turns = self.history.get_session(session_id).get("turns", [])
        except Exception:
            turns = []
        for turn in turns:
            self._cancel(f"turn:{turn['id']}")

    def forget_document(self, document_id: str) -> int:
        self.cancel_document_refresh(document_id)
        return self.store.mark_source_status("document", document_id, "deleted")

    def forget_session(self, session_id: str) -> int:
        self.cancel_session_refreshes(session_id)
        return self.store.mark_session_status(session_id, "deleted")

    def forget_turn(self, turn_id: str) -> int:
        self._cancel(f"turn:{turn_id}")
        return self.store.mark_source_status("chat_window", turn_id, "deleted")

    def _enrich_context(self, context: MemoryQueryContext) -> MemoryQueryContext:
        if not context.project_id:
            return context
        try:
            active = self.workspace.get_active_scene(context.project_id) or {}
        except Exception:
            active = {}
        scene_card = None
        if active.get("document_id"):
            try:
                scene_card = self.workspace.get_scene_card(active["document_id"])
            except Exception:
                scene_card = None
        scene_card = scene_card or {}
        active_document = {}
        if active.get("document_id"):
            try:
                active_document = self.workspace.get_document(active["document_id"]) or {}
            except Exception:
                active_document = {}
        if context.story_order is None:
            order = scene_card.get("sort_order")
            if order is None:
                order = active_document.get("sort_order")
            if order is not None:
                context.story_order = float(order)
        if context.world_time is None:
            context.world_time = active.get("narrative_time") or scene_card.get("narrative_time") or None
        if context.pov_variant_id is None:
            context.pov_variant_id = active.get("pov_variant_id") or scene_card.get("pov_variant_id")
        return context

    def status(self) -> dict[str, Any]:
        embedding_available = False
        if self.config.dense_enabled:
            try:
                embedding_available = self.embedding.available()
            except Exception:
                embedding_available = False
        return {**self.store.status(), "enabled": self.config.enabled, "automatic_context": self.config.automatic_context,
                "config": self.config.to_dict(), "embedding_available": embedding_available,
                "fallback_active": bool(self.config.dense_enabled and not embedding_available),
                "fallback": "structured indexes + SQLite FTS5" if self.config.fts_enabled else "structured indexes",
                "reranker_requested": self.config.reranker.enabled, "reranker_available": self.reranker.available(),
                "context_intelligence_version": self.context_planner.VERSION}

    def backfill(self, project_id: str | None = None) -> dict[str, Any]:
        if not self.config.enabled:
            return {"disabled": True, "documents": 0, "turns": 0, "chunks": 0}
        return self.indexer.backfill(project_id)

    def retrieve(self, query: str, context: MemoryQueryContext, *, workspace_context=None) -> RetrievalResult:
        if not self.config.enabled or not query.strip():
            from .models import QueryPlan, QueryRoute
            plan = QueryPlan(QueryRoute.TEXT_RECALL, context, normalized_query=query.strip())
            return RetrievalResult("disabled", plan, [], [], "", {}, True, "Memory retrieval is disabled.")
        enriched = self._enrich_context(context)
        route = self.query_engine.compiler.route(query)
        intelligence = self.context_planner.plan(
            query, enriched, workspace_context=workspace_context, route=route
        )
        return self.query_engine.execute(query, enriched, context_plan=intelligence.to_dict())

    def augment_workspace_context(self, workspace_context, result: RetrievalResult):
        intelligence = result.plan.context_plan or {}
        memory_meta = {
            "run_id": result.run_id, "route": result.plan.route.value, "selected": len(result.selected),
            "excluded": len(result.excluded), "abstain": result.abstain, "reason": result.abstention_reason,
            "token_budget": result.plan.scope.token_budget,
            "context_intelligence_version": intelligence.get("version"),
            "intent": intelligence.get("intent"),
        }
        if intelligence:
            workspace_context.scope["context_intelligence"] = intelligence
        if not result.packed_text:
            workspace_context.scope["memory"] = memory_meta
            return workspace_context
        workspace_context.text = workspace_context.text.rstrip() + "\n\n" + result.packed_text.rstrip() + "\n"
        packed_tokens = max(1, len(result.packed_text) // 4)
        workspace_context.estimated_tokens += packed_tokens
        workspace_context.scope["memory"] = {
            **memory_meta, "lens": result.plan.scope.context_lens.value, "lane_counts": result.lane_counts,
            "packed_tokens": packed_tokens, "diagnostics": result.diagnostics,
            "dimensions": intelligence.get("dimensions") or {},
            "preserve_lanes": intelligence.get("preserve_lanes") or [],
            "focus_resources": intelligence.get("focus_resources") or [],
            "selected_sources": [{"id": item.id, "lane": item.lane.value, "source_type": item.source_type,
                                  "source_id": item.source_id, "score": round(item.score, 6), "ranks": item.ranks}
                                 for item in result.selected],
            "excluded_preview": result.excluded[:20],
        }
        return workspace_context
