from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.memory.models import MemoryQueryContext

from .backfill import DiscoveryBackfillService
from .general import install_general_capture
from .memory import install_discovery_memory_bridge
from .provisional import install_provisional_discovery
from .service import DiscoveryService
from .spatial import install_spatial_capture
from .store import DiscoveryStore


class DiscoveryDecisionPayload(BaseModel):
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    session_id: str | None = None
    world_time: Any = None
    story_order: float | None = None
    note: str | None = None


class DiscoveryEditPayload(DiscoveryDecisionPayload):
    value: Any
    mode: str = "correction"


def _context(
    *,
    project_id: str | None,
    world_id: str | None,
    branch_id: str | None,
    session_id: str | None,
    world_time: Any = None,
    story_order: float | None = None,
) -> MemoryQueryContext:
    return MemoryQueryContext(
        project_id=project_id,
        world_id=world_id,
        branch_id=branch_id,
        session_id=session_id,
        world_time=world_time,
        story_order=story_order,
        context_lens="scene",
        retrieval_mode="discovery_review",
    )


def attach_discovery(
    router: APIRouter,
    *,
    memory_service,
    memory_store,
    workspace,
    history,
    foundation=None,
) -> None:
    if getattr(memory_service, "discovery", None) is not None:
        discovery = memory_service.discovery
    else:
        store = DiscoveryStore(memory_store.path)
        discovery = DiscoveryService(
            store=store,
            workspace=workspace,
            history=history,
            gate=memory_service.query_engine.gate,
        )
        memory_service.discovery = discovery
        memory_service.query_engine.discovery = discovery
        memory_service.query_engine.compiler.discovery = discovery
        install_discovery_memory_bridge()

    install_provisional_discovery(discovery)

    def persisted_turn_report(
        turn_id: str,
        source_kind: str = "user_prompt",
        *,
        materialize: bool = False,
    ) -> dict[str, Any]:
        """Report persisted evidence without re-running semantic extraction.

        Turn capture already performs turn-local incremental materialization. The
        previous implementation called materialize again here and the browser
        then called capture-turn again, multiplying work for every generation.
        A caller may request a cached/idempotent materialization check explicitly,
        but normal reporting is read-only.
        """
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
        history_store = memory_service.history
        foundation_store = foundation or getattr(memory_service, "foundation", None)

        original_add_turn = history_store.add_turn
        original_feedback = history_store.set_feedback
        original_delete_session = history_store.delete_session
        original_delete_scope = history_store.delete_sessions_by_scope
        original_trash = getattr(foundation_store, "trash", None) if foundation_store is not None else None
        original_restore = getattr(foundation_store, "restore", None) if foundation_store is not None else None

        def add_turn_with_discovery(*args, **kwargs):
            turn = original_add_turn(*args, **kwargs)
            try:
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
            result = original_delete_session(session_id)
            try:
                discovery.set_session_active(session_id, active=False, reason="source_deleted")
            except Exception as exc:
                report_failure(f"session:{session_id}", exc)
            return result

        def delete_scope_with_discovery(**kwargs):
            try:
                before = history_store.list_sessions(
                    project_id=kwargs.get("project_id"),
                    world_id=kwargs.get("world_id"),
                    branch_id=kwargs.get("branch_id"),
                    include_archived=True,
                )
            except Exception:
                before = []
            result = original_delete_scope(**kwargs)
            for session in before:
                try:
                    discovery.set_session_active(session["id"], active=False, reason="source_deleted")
                except Exception as exc:
                    report_failure(f"scope-session:{session.get('id')}", exc)
            return result

        history_store.add_turn = add_turn_with_discovery
        history_store.set_feedback = feedback_with_discovery
        history_store.delete_session = delete_session_with_discovery
        history_store.delete_sessions_by_scope = delete_scope_with_discovery

        if foundation_store is not None and callable(original_trash):
            def trash_with_discovery(resource_type: str, resource_id: str, *args, **kwargs):
                result = original_trash(resource_type, resource_id, *args, **kwargs)
                if resource_type == "chat_session":
                    try:
                        discovery.set_session_active(resource_id, active=False, reason="source_trashed")
                    except Exception as exc:
                        report_failure(f"trash:{resource_id}", exc)
                return result
            foundation_store.trash = trash_with_discovery

        if foundation_store is not None and callable(original_restore):
            def restore_with_discovery(resource_type: str, resource_id: str, *args, **kwargs):
                result = original_restore(resource_type, resource_id, *args, **kwargs)
                if resource_type == "chat_session":
                    try:
                        discovery.store.restore_source_reason(
                            session_id=resource_id, reason="source_trashed"
                        )
                    except Exception as exc:
                        report_failure(f"restore:{resource_id}", exc)
                return result
            foundation_store.restore = restore_with_discovery

        memory_service._v121_discovery_hooks_bound = True

    # The semantic type/grammar extensions wrap capture only after the lifecycle
    # hook has been bound to the final DiscoveryService method chain.
    install_general_capture(discovery)
    install_spatial_capture(discovery)

    backfill_service = DiscoveryBackfillService(
        discovery=discovery,
        history=history,
        foundation=foundation,
    )

    @router.get("/discoveries/status")
    def discovery_status():
        status = discovery.store.status()
        performance = getattr(discovery, "_performance_metrics", None)
        if performance:
            status["performance"] = performance
        return status

    @router.get("/discoveries")
    def list_discoveries(
        project_id: str | None = Query(None),
        world_id: str | None = Query(None),
        branch_id: str | None = Query(None),
        session_id: str | None = Query(None),
        include_dismissed: bool = Query(False),
        include_orphaned: bool = Query(False),
        limit: int = Query(250, ge=1, le=1000),
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
            state = item["knowledge_state"]
            counts[state] = counts.get(state, 0) + 1
        return {"items": items, "counts": counts, "limit": limit}

    @router.get("/discoveries/{proposition_id}")
    def get_discovery(
        proposition_id: str,
        project_id: str | None = Query(None),
        world_id: str | None = Query(None),
        branch_id: str | None = Query(None),
        session_id: str | None = Query(None),
    ):
        try:
            item = discovery.get(
                proposition_id,
                _context(
                    project_id=project_id,
                    world_id=world_id,
                    branch_id=branch_id,
                    session_id=session_id,
                ),
            )
            if item["knowledge_state"] != "canon" and item["support_count"] <= 0:
                raise KeyError(proposition_id)
            return item
        except KeyError as exc:
            raise HTTPException(404, "Discovery not found in this narrative lineage") from exc

    @router.post("/discoveries/{proposition_id}/canon")
    def canon_discovery(proposition_id: str, payload: DiscoveryDecisionPayload):
        context = _context(
            project_id=payload.project_id,
            world_id=payload.world_id,
            branch_id=payload.branch_id,
            session_id=payload.session_id,
            world_time=payload.world_time,
            story_order=payload.story_order,
        )
        try:
            return discovery.promote_canon(
                proposition_id,
                context,
                actor="user",
                note=payload.note or "Explicit user canon promotion",
            )
        except KeyError as exc:
            raise HTTPException(404, "Discovery not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/discoveries/{proposition_id}/dismiss")
    def dismiss_discovery(proposition_id: str, payload: DiscoveryDecisionPayload):
        context = _context(
            project_id=payload.project_id,
            world_id=payload.world_id,
            branch_id=payload.branch_id,
            session_id=payload.session_id,
            world_time=payload.world_time,
            story_order=payload.story_order,
        )
        try:
            return discovery.dismiss(
                proposition_id,
                context,
                actor="user",
                note=payload.note or "Explicit user dismissal",
            )
        except KeyError as exc:
            raise HTTPException(404, "Discovery not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/discoveries/{proposition_id}/reset")
    def reset_discovery(proposition_id: str, payload: DiscoveryDecisionPayload):
        context = _context(
            project_id=payload.project_id,
            world_id=payload.world_id,
            branch_id=payload.branch_id,
            session_id=payload.session_id,
            world_time=payload.world_time,
            story_order=payload.story_order,
        )
        try:
            return discovery.reset_detected(
                proposition_id,
                context,
                actor="user",
                note=payload.note or "Reset to detected lifecycle",
            )
        except KeyError as exc:
            raise HTTPException(404, "Discovery not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/discoveries/{proposition_id}/edit")
    def edit_discovery(proposition_id: str, payload: DiscoveryEditPayload):
        context = _context(
            project_id=payload.project_id,
            world_id=payload.world_id,
            branch_id=payload.branch_id,
            session_id=payload.session_id,
            world_time=payload.world_time,
            story_order=payload.story_order,
        )
        try:
            return discovery.record_explicit_edit(
                proposition_id,
                payload.value,
                context,
                mode=payload.mode,
            )
        except KeyError as exc:
            raise HTTPException(404, "Discovery not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/discoveries/resource/{resource_type}/{resource_id}")
    def discovery_resource_view(
        resource_type: str,
        resource_id: str,
        project_id: str | None = Query(None),
        world_id: str | None = Query(None),
        branch_id: str | None = Query(None),
        session_id: str | None = Query(None),
    ):
        if resource_type != "entity_family":
            raise HTTPException(400, "Only entity_family provisional views are supported")
        context = _context(
            project_id=project_id,
            world_id=world_id,
            branch_id=branch_id,
            session_id=session_id,
        )
        try:
            return discovery.resource_view(resource_id, context)
        except KeyError as exc:
            raise HTTPException(404, "Library sheet not found") from exc

    @router.get("/discoveries/turn/{turn_id}/report")
    def discovery_turn_report(
        turn_id: str,
        source_kind: str = Query("user_prompt"),
    ):
        try:
            history.get_turn(turn_id)
            return persisted_turn_report(turn_id, source_kind)
        except KeyError as exc:
            raise HTTPException(404, "Turn not found") from exc

    @router.post("/discoveries/backfill")
    def discovery_backfill(project_id: str | None = Query(None)):
        result = backfill_service.run(project_id=project_id)
        result["materialization"] = discovery.materialize_existing()
        return result

    @router.post("/discoveries/capture-turn/{turn_id}")
    def recapture_turn(
        turn_id: str,
        source_kind: str = Query("user_prompt"),
        force: bool = Query(False),
    ):
        """Compatibility endpoint: report by default, recapture only on demand.

        The browser historically called this after every generation even though
        the HistoryStore hook had already captured the turn. Keeping the route
        avoids frontend breakage while removing duplicate extraction from the hot
        path. Diagnostics/repair callers can pass ``force=true`` explicitly.
        """
        try:
            if force:
                discovery.capture_turn(turn_id, source_kind=source_kind)
            return persisted_turn_report(turn_id, source_kind)
        except KeyError as exc:
            raise HTTPException(404, "Turn not found") from exc
