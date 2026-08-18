from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Query
from pydantic import BaseModel

from src.memory.models import MemoryQueryContext

from .memory import install_discovery_memory_bridge
from .service import DiscoveryService
from .store import DiscoveryStore


class DiscoveryDecisionPayload(BaseModel):
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    session_id: str | None = None
    story_order: float | None = None
    world_time: Any = None
    note: str = ""


def _context(*, project_id=None, world_id=None, branch_id=None, session_id=None,
             story_order=None, world_time=None) -> MemoryQueryContext:
    return MemoryQueryContext(
        project_id=project_id, world_id=world_id, branch_id=branch_id,
        session_id=session_id, story_order=story_order, world_time=world_time,
        context_lens="scene",
    )


def attach_discovery(router, *, memory_service, foundation=None) -> DiscoveryService | None:
    """Attach Narrative Discovery to a real MemoryService application instance.

    `create_memory_router()` is also exercised with tiny fake services in unit
    tests. Discovery is an optional extension there, so missing Memory ownership
    dependencies must be a clean no-op rather than changing the router contract.
    """
    required = ("store", "workspace", "history", "query_engine")
    if not all(hasattr(memory_service, name) for name in required):
        return None

    existing = getattr(memory_service, "discovery", None)
    if isinstance(existing, DiscoveryService):
        discovery = existing
    else:
        discovery_store = DiscoveryStore(memory_service.store.path)
        discovery = DiscoveryService(
            store=discovery_store,
            workspace=memory_service.workspace,
            history=memory_service.history,
            foundation=foundation or getattr(memory_service, "foundation", None),
        )
        memory_service.discovery = discovery
        memory_service.query_engine.discovery = discovery
        memory_service.query_engine.compiler.discovery = discovery
        install_discovery_memory_bridge()

    def report_failure(key: str, exc: Exception) -> None:
        reporter = getattr(memory_service, "_report_refresh_failure", None)
        if callable(reporter):
            reporter(f"discovery:{key}", exc)

    if not getattr(memory_service, "_v121_discovery_hooks_bound", False):
        history = memory_service.history
        foundation_store = foundation or getattr(memory_service, "foundation", None)

        original_add_turn = history.add_turn
        original_feedback = history.set_feedback
        original_delete_session = history.delete_session
        original_delete_scope = history.delete_sessions_by_scope
        original_trash = getattr(foundation_store, "trash", None) if foundation_store is not None else None
        original_restore = getattr(foundation_store, "restore", None) if foundation_store is not None else None

        def add_turn_with_discovery(*args, **kwargs):
            turn = original_add_turn(*args, **kwargs)
            try:
                discovery.capture_turn(turn["id"], source_kind="user_prompt")
            except Exception as exc:
                report_failure(f"turn:{turn.get('id')}", exc)
            return turn

        def feedback_with_discovery(turn_id: str, **kwargs):
            turn = original_feedback(turn_id, **kwargs)
            try:
                status = turn.get("feedback_status") or kwargs.get("status")
                if status == "accepted":
                    discovery.store.set_source_kind_active(
                        turn_id, "user_edited_prose", active=False, reason="feedback_replaced"
                    )
                    discovery.capture_turn(turn_id, source_kind="accepted_generation")
                elif status == "edited_accept":
                    discovery.store.set_source_kind_active(
                        turn_id, "accepted_generation", active=False, reason="feedback_replaced"
                    )
                    discovery.capture_turn(turn_id, source_kind="user_edited_prose")
                elif status == "rejected":
                    discovery.store.set_source_kind_active(
                        turn_id, "accepted_generation", active=False, reason="feedback_rejected"
                    )
                    discovery.store.set_source_kind_active(
                        turn_id, "user_edited_prose", active=False, reason="feedback_rejected"
                    )
            except Exception as exc:
                report_failure(f"feedback:{turn_id}", exc)
            return turn

        def delete_session_with_discovery(session_id: str):
            try:
                discovery.set_session_active(session_id, active=False, reason="source_deleted")
            except Exception as exc:
                report_failure(f"session:{session_id}", exc)
            return original_delete_session(session_id)

        def delete_scope_with_discovery(*, project_id=None, world_id=None, branch_id=None):
            try:
                sessions = history.list_sessions(
                    limit=500,
                    include_archived=True,
                    project_id=project_id,
                    world_id=world_id,
                    branch_id=branch_id,
                )
                for session in sessions:
                    discovery.set_session_active(session["id"], active=False, reason="scope_deleted")
            except Exception as exc:
                report_failure("scope", exc)
            return original_delete_scope(
                project_id=project_id, world_id=world_id, branch_id=branch_id
            )

        history.add_turn = add_turn_with_discovery
        history.set_feedback = feedback_with_discovery
        history.delete_session = delete_session_with_discovery
        history.delete_sessions_by_scope = delete_scope_with_discovery

        if callable(original_trash):
            def trash_with_discovery(resource_type: str, resource_id: str, **kwargs):
                result = original_trash(resource_type, resource_id, **kwargs)
                if resource_type == "session":
                    try:
                        discovery.set_session_active(
                            resource_id, active=False, reason="source_trashed"
                        )
                    except Exception as exc:
                        report_failure(f"trash:{resource_id}", exc)
                return result

            foundation_store.trash = trash_with_discovery

        if callable(original_restore):
            def restore_with_discovery(resource_type: str, resource_id: str, **kwargs):
                result = original_restore(resource_type, resource_id, **kwargs)
                if resource_type == "session":
                    try:
                        # Restore only lifecycle-invalidated evidence; rejected,
                        # revised, and deleted-source instances stay invalid.
                        with discovery.store._lock, discovery.store.connection() as con:
                            con.execute(
                                "UPDATE discovery_instances SET active=1,invalidation_reason=NULL,updated_at=datetime('now') "
                                "WHERE source_session_id=? AND invalidation_reason='source_trashed'",
                                (resource_id,),
                            )
                    except Exception as exc:
                        report_failure(f"restore:{resource_id}", exc)
                return result

            foundation_store.restore = restore_with_discovery

        memory_service._v121_discovery_hooks_bound = True
        memory_service._v121_original_add_turn = original_add_turn
        memory_service._v121_original_feedback = original_feedback

    @router.get("/discoveries")
    def list_discoveries(
        project_id: str | None = Query(None),
        world_id: str | None = Query(None),
        branch_id: str | None = Query(None),
        session_id: str | None = Query(None),
        include_dismissed: bool = Query(False),
        include_orphaned: bool = Query(False),
        limit: int = Query(500, ge=1, le=2000),
    ):
        context = _context(
            project_id=project_id,
            world_id=world_id,
            branch_id=branch_id,
            session_id=session_id,
        )
        items = discovery.list(
            context,
            include_dismissed=include_dismissed,
            include_orphaned=include_orphaned,
            limit=limit,
        )
        counts: dict[str, int] = {}
        for item in items:
            key = item["knowledge_state"]
            counts[key] = counts.get(key, 0) + 1
        return {"items": items, "counts": counts, "store": discovery.store.status()}

    @router.get("/discoveries/{proposition_id}")
    def get_discovery(
        proposition_id: str,
        project_id: str | None = Query(None),
        world_id: str | None = Query(None),
        branch_id: str | None = Query(None),
        session_id: str | None = Query(None),
    ):
        try:
            return discovery.get(
                proposition_id,
                _context(
                    project_id=project_id,
                    world_id=world_id,
                    branch_id=branch_id,
                    session_id=session_id,
                ),
            )
        except KeyError as exc:
            raise HTTPException(404, "Discovery proposition not found") from exc

    @router.post("/discoveries/{proposition_id}/canon")
    def promote_discovery(proposition_id: str, payload: DiscoveryDecisionPayload):
        try:
            return discovery.promote_canon(
                proposition_id,
                _context(
                    project_id=payload.project_id,
                    world_id=payload.world_id,
                    branch_id=payload.branch_id,
                    session_id=payload.session_id,
                    story_order=payload.story_order,
                    world_time=payload.world_time,
                ),
                note=payload.note,
            )
        except KeyError as exc:
            raise HTTPException(404, "Discovery proposition not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/discoveries/{proposition_id}/dismiss")
    def dismiss_discovery(proposition_id: str, payload: DiscoveryDecisionPayload):
        try:
            return discovery.dismiss(
                proposition_id,
                _context(
                    project_id=payload.project_id,
                    world_id=payload.world_id,
                    branch_id=payload.branch_id,
                    session_id=payload.session_id,
                ),
                note=payload.note,
            )
        except KeyError as exc:
            raise HTTPException(404, "Discovery proposition not found") from exc

    @router.post("/discoveries/{proposition_id}/reset")
    def reset_discovery(proposition_id: str, payload: DiscoveryDecisionPayload):
        try:
            return discovery.reset_decision(
                proposition_id,
                _context(
                    project_id=payload.project_id,
                    world_id=payload.world_id,
                    branch_id=payload.branch_id,
                    session_id=payload.session_id,
                ),
                note=payload.note,
            )
        except KeyError as exc:
            raise HTTPException(404, "Discovery proposition not found") from exc

    @router.post("/discoveries/capture-turn/{turn_id}")
    def recapture_turn(turn_id: str):
        try:
            return discovery.capture_turn(turn_id, source_kind="user_prompt").to_dict()
        except KeyError as exc:
            raise HTTPException(404, "Turn not found") from exc

    return discovery
