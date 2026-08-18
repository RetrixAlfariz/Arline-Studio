from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Query
from pydantic import BaseModel

from src.memory.models import MemoryQueryContext

from .backfill import backfill_discoveries
from .general import install_general_discovery
from .memory import install_discovery_memory_bridge
from .performance_background import install_background_materialization
from .provisional import install_provisional_discovery
from .service import DiscoveryService
from .spatial import install_spatial_discovery
from .store import DiscoveryStore


class DiscoveryDecisionPayload(BaseModel):
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    session_id: str | None = None
    story_order: float | None = None
    world_time: Any = None
    note: str = ""


class DiscoveryEditPayload(DiscoveryDecisionPayload):
    value: Any
    mode: str = "correction"


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

    # Install from general to specialized. The spatial layer wraps the generic
    # capture path, then provisional materialization wraps turn capture itself.
    install_general_discovery()
    install_spatial_discovery()

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

    # The provisional installer is performance-wrapped by provisional_autopatch:
    # startup projection is bounded and revision-aware. Any residue is drained
    # later by a daemon worker; installing that worker performs no DB scan.
    install_provisional_discovery(discovery)
    install_background_materialization(discovery)

    def persisted_turn_report(
        turn_id: str,
        source_kind: str = "user_prompt",
        *,
        materialize: bool = False,
    ) -> dict[str, Any]:
        """Report persisted evidence without re-running extraction/materialization."""
        with discovery.store.connection() as con:
            rows = con.execute(
                "SELECT id,proposition_id FROM discovery_instances "
                "WHERE source_turn_id=? AND source_kind=? AND active=1",
                (turn_id, source_kind),
            ).fetchall()
        proposition_ids = {str(row["proposition_id"]) for row in rows}
        report = {
            "turn_id": turn_id,
            "source_kind": source_kind,
            "propositions": len(proposition_ids),
            "instances": len(rows),
            "persisted": True,
        }
        if materialize:
            report["materialization"] = discovery.materialize_turn(turn_id)
        return report

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
                # capture_turn already performs the turn-local incremental
                # projection exactly once. Reporting below is read-only.
                discovery.capture_turn(turn["id"], source_kind="user_prompt")
                turn["_discovery_report"] = persisted_turn_report(turn["id"], "user_prompt")
            except Exception as exc:
                turn["_discovery_report"] = {
                    "turn_id": turn.get("id"), "source_kind": "user_prompt",
                    "propositions": 0, "instances": 0, "error": str(exc),
                }
                report_failure(f"turn:{turn.get('id')}", exc)
            return turn

        def feedback_with_discovery(turn_id: str, **kwargs):
            turn = original_feedback(turn_id, **kwargs)
            try:
                source_kind = None
                status = turn.get("feedback_status") or kwargs.get("status")
                if status == "accepted":
                    discovery.store.set_source_kind_active(
                        turn_id, "user_edited_prose", active=False, reason="feedback_replaced"
                    )
                    source_kind = "accepted_generation"
                    discovery.capture_turn(turn_id, source_kind=source_kind)
                elif status == "edited_accept":
                    discovery.store.set_source_kind_active(
                        turn_id, "accepted_generation", active=False, reason="feedback_replaced"
                    )
                    source_kind = "user_edited_prose"
                    discovery.capture_turn(turn_id, source_kind=source_kind)
                elif status == "rejected":
                    discovery.store.set_source_kind_active(
                        turn_id, "accepted_generation", active=False, reason="feedback_rejected"
                    )
                    discovery.store.set_source_kind_active(
                        turn_id, "user_edited_prose", active=False, reason="feedback_rejected"
                    )
                if source_kind:
                    turn["_discovery_report"] = persisted_turn_report(turn_id, source_kind)
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
                    limit=500, include_archived=True,
                    project_id=project_id, world_id=world_id, branch_id=branch_id,
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
                        discovery.set_session_active(resource_id, active=False, reason="source_trashed")
                    except Exception as exc:
                        report_failure(f"trash:{resource_id}", exc)
                return result
            foundation_store.trash = trash_with_discovery

        if callable(original_restore):
            def restore_with_discovery(resource_type: str, resource_id: str, **kwargs):
                result = original_restore(resource_type, resource_id, **kwargs)
                if resource_type == "session":
                    try:
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
        limit: int = Query(250, ge=1, le=2000),
    ):
        context = _context(
            project_id=project_id, world_id=world_id,
            branch_id=branch_id, session_id=session_id,
        )
        items = discovery.list(
            context, include_dismissed=include_dismissed,
            include_orphaned=include_orphaned, limit=limit,
        )
        counts: dict[str, int] = {}
        for item in items:
            key = item["knowledge_state"]
            counts[key] = counts.get(key, 0) + 1
        return {"items": items, "counts": counts, "store": discovery.store.status()}

    @router.get("/discoveries/turn/{turn_id}/report")
    def discovery_turn_report(
        turn_id: str,
        source_kind: str = Query("user_prompt"),
    ):
        try:
            discovery.history.get_turn(turn_id)
            return persisted_turn_report(turn_id, source_kind)
        except KeyError as exc:
            raise HTTPException(404, "Turn not found") from exc

    @router.post("/discoveries/backfill")
    def backfill_discovery_history(
        project_id: str | None = Query(None),
        limit_sessions: int = Query(500, ge=1, le=500),
    ):
        report = backfill_discoveries(
            discovery, project_id=project_id, limit_sessions=limit_sessions
        ).to_dict()
        report["materialization"] = discovery.materialize_existing()
        return report

    @router.get("/discoveries/resource/{resource_type}/{resource_id}")
    def discovery_resource_view(
        resource_type: str,
        resource_id: str,
        project_id: str | None = Query(None), world_id: str | None = Query(None),
        branch_id: str | None = Query(None), session_id: str | None = Query(None),
        story_order: float | None = Query(None),
    ):
        if resource_type == "entity_variant":
            try:
                resource_id = discovery.workspace.get_variant(resource_id)["family_id"]
                resource_type = "entity_family"
            except KeyError as exc:
                raise HTTPException(404, "Entity variant not found") from exc
        if resource_type != "entity_family":
            raise HTTPException(400, "Provisional Discovery resource view currently supports entity sheets")
        try:
            return discovery.resource_view(
                resource_id,
                _context(
                    project_id=project_id, world_id=world_id, branch_id=branch_id,
                    session_id=session_id, story_order=story_order,
                ),
            )
        except KeyError as exc:
            raise HTTPException(404, "Entity sheet not found") from exc

    @router.get("/discoveries/{proposition_id}")
    def get_discovery(
        proposition_id: str,
        project_id: str | None = Query(None), world_id: str | None = Query(None),
        branch_id: str | None = Query(None), session_id: str | None = Query(None),
    ):
        try:
            return discovery.get(
                proposition_id,
                _context(
                    project_id=project_id, world_id=world_id,
                    branch_id=branch_id, session_id=session_id,
                ),
            )
        except KeyError as exc:
            raise HTTPException(404, "Discovery proposition not found") from exc

    @router.post("/discoveries/{proposition_id}/edit")
    def edit_discovery(proposition_id: str, payload: DiscoveryEditPayload):
        try:
            return discovery.record_explicit_edit(
                proposition_id,
                payload.value,
                _context(
                    project_id=payload.project_id, world_id=payload.world_id,
                    branch_id=payload.branch_id, session_id=payload.session_id,
                    story_order=payload.story_order, world_time=payload.world_time,
                ),
                mode=payload.mode,
            )
        except KeyError as exc:
            raise HTTPException(404, "Discovery proposition not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/discoveries/{proposition_id}/canon")
    def promote_discovery(proposition_id: str, payload: DiscoveryDecisionPayload):
        try:
            return discovery.promote_canon(
                proposition_id,
                _context(
                    project_id=payload.project_id, world_id=payload.world_id,
                    branch_id=payload.branch_id, session_id=payload.session_id,
                    story_order=payload.story_order, world_time=payload.world_time,
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
                    project_id=payload.project_id, world_id=payload.world_id,
                    branch_id=payload.branch_id, session_id=payload.session_id,
                ), note=payload.note,
            )
        except KeyError as exc:
            raise HTTPException(404, "Discovery proposition not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/discoveries/{proposition_id}/reset")
    def reset_discovery(proposition_id: str, payload: DiscoveryDecisionPayload):
        try:
            return discovery.reset_decision(
                proposition_id,
                _context(
                    project_id=payload.project_id, world_id=payload.world_id,
                    branch_id=payload.branch_id, session_id=payload.session_id,
                ), note=payload.note,
            )
        except KeyError as exc:
            raise HTTPException(404, "Discovery proposition not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/discoveries/capture-turn/{turn_id}")
    def recapture_turn(
        turn_id: str,
        source_kind: str = Query("user_prompt"),
        force: bool = Query(False),
    ):
        """Compatibility endpoint: persisted report by default, repair on demand."""
        try:
            if force:
                discovery.capture_turn(turn_id, source_kind=source_kind)
            else:
                discovery.history.get_turn(turn_id)
            return persisted_turn_report(turn_id, source_kind)
        except KeyError as exc:
            raise HTTPException(404, "Turn not found") from exc

    return discovery
