from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Query
from pydantic import BaseModel

from src.memory.models import MemoryQueryContext
from src.domain_events import get_domain_event_bus

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


class ContinuityConflictResolutionPayload(DiscoveryDecisionPayload):
    action: str
    from_proposition_id: str | None = None
    to_proposition_id: str | None = None


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
        discovery_store = DiscoveryStore(
            memory_service.store.path,
            backup_before_migration=not bool(
                getattr(memory_service, "_combined_migration_backup_complete", False)
            ),
        )
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

    def turn_created(event):
        turn = event.payload.get("turn") or {}
        turn_id = turn.get("id")
        if not turn_id:
            return
        try:
            discovery.capture_turn(turn_id, source_kind="user_prompt")
            turn["_discovery_report"] = persisted_turn_report(turn_id, "user_prompt")
        except Exception as exc:
            turn["_discovery_report"] = {
                "turn_id": turn_id,
                "source_kind": "user_prompt",
                "propositions": 0,
                "instances": 0,
                "error": str(exc),
            }
            report_failure(f"turn:{turn_id}", exc)

    def feedback_changed(event):
        turn = event.payload.get("turn") or {}
        turn_id = turn.get("id")
        status = turn.get("feedback_status")
        source_kind = None
        if not turn_id:
            return
        try:
            if status == "accepted":
                discovery.store.set_source_kind_active(
                    turn_id, "user_edited_prose", active=False, reason="feedback_replaced"
                )
                source_kind = "accepted_generation"
            elif status == "edited_accept":
                discovery.store.set_source_kind_active(
                    turn_id, "accepted_generation", active=False, reason="feedback_replaced"
                )
                source_kind = "user_edited_prose"
            elif status == "rejected":
                discovery.store.set_source_kind_active(
                    turn_id, "accepted_generation", active=False, reason="feedback_rejected"
                )
                discovery.store.set_source_kind_active(
                    turn_id, "user_edited_prose", active=False, reason="feedback_rejected"
                )
            if source_kind:
                discovery.capture_turn(turn_id, source_kind=source_kind)
                turn["_discovery_report"] = persisted_turn_report(turn_id, source_kind)
        except Exception as exc:
            report_failure(f"feedback:{turn_id}", exc)

    def session_deleted(event):
        session_id = event.payload.get("session_id")
        if not session_id:
            return
        try:
            discovery.set_session_active(session_id, active=False, reason="source_deleted")
        except Exception as exc:
            report_failure(f"session:{session_id}", exc)

    def scope_deleted(event):
        for session_id in event.payload.get("session_ids") or []:
            try:
                discovery.set_session_active(session_id, active=False, reason="scope_deleted")
            except Exception as exc:
                report_failure(f"scope:{session_id}", exc)

    def resource_trashed(event):
        payload = event.payload
        session_id = payload.get("resource_id")
        if payload.get("resource_type") != "session" or not session_id:
            return
        try:
            discovery.set_session_active(session_id, active=False, reason="source_trashed")
        except Exception as exc:
            report_failure(f"trash:{session_id}", exc)

    def resource_restored(event):
        payload = event.payload
        session_id = payload.get("resource_id")
        if payload.get("resource_type") != "session" or not session_id:
            return
        try:
            with discovery.store._lock, discovery.store.connection() as con:
                con.execute(
                    "UPDATE discovery_instances SET active=1,invalidation_reason=NULL,"
                    "updated_at=datetime('now') WHERE source_session_id=? "
                    "AND invalidation_reason='source_trashed'",
                    (session_id,),
                )
        except Exception as exc:
            report_failure(f"restore:{session_id}", exc)

    # History and Workspace may intentionally live in different SQLite files.
    # Subscribe to the bus that owns each authoritative source instead of
    # assuming the default single-database layout.
    history_bus = get_domain_event_bus(memory_service.history.path)
    workspace_bus = get_domain_event_bus(discovery.store.path)
    for name, handler, key in (
        ("history.turn_created", turn_created, "discovery.turn"),
        ("history.feedback_changed", feedback_changed, "discovery.feedback"),
        ("history.session_deleted", session_deleted, "discovery.delete"),
        ("history.scope_deleted", scope_deleted, "discovery.scope"),
    ):
        history_bus.subscribe(name, handler, key=key)
    for name, handler, key in (
        ("foundation.resource_trashed", resource_trashed, "discovery.trash"),
        ("foundation.resource_restored", resource_restored, "discovery.restore"),
    ):
        workspace_bus.subscribe(name, handler, key=key)

    # Compatibility/status markers only. No authoritative method is replaced.
    memory_service._v121_discovery_events_bound = True
    memory_service._v121_discovery_hooks_bound = True

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

    @router.get("/discoveries/continuity/status")
    def continuity_status():
        return discovery.continuity.status()

    @router.get("/discoveries/continuity/conflicts")
    def continuity_conflicts(
        project_id: str | None = Query(None), world_id: str | None = Query(None),
        branch_id: str | None = Query(None), session_id: str | None = Query(None),
        include_resolved: bool = Query(False),
    ):
        return {"items": discovery.continuity.list_conflicts(
            _context(project_id=project_id, world_id=world_id, branch_id=branch_id, session_id=session_id),
            include_resolved=include_resolved,
        )}

    @router.post("/discoveries/continuity/conflicts/{conflict_id}/resolve")
    def resolve_continuity_conflict(conflict_id: str, payload: ContinuityConflictResolutionPayload):
        try:
            return discovery.continuity.resolve_conflict(
                conflict_id, action=payload.action,
                from_proposition_id=payload.from_proposition_id,
                to_proposition_id=payload.to_proposition_id, note=payload.note,
            )
        except KeyError as exc:
            raise HTTPException(404, "Continuity conflict not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

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
