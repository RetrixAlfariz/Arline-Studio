from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from src.discovery.web import attach_discovery
from src.domain_events import get_domain_event_bus
from .contracts import SCHEMA_MODELS, schema_document
from .models import MemoryQueryContext
from .profiles import TASK_PROFILES


class MemoryQueryPayload(BaseModel):
    query: str
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    session_id: str | None = None
    current_turn_id: str | None = None
    world_time: Any = None
    story_order: float | None = None
    pov_variant_id: str | None = None
    context_lens: str = "scene"
    retrieval_mode: str = "debug"
    explicit_references: list[dict[str, Any]] = Field(default_factory=list)
    explicit_cross_scope_sources: list[dict[str, str]] = Field(default_factory=list)
    allow_scratch: bool = False
    allow_future_author_knowledge: bool = False


class MemoryBackfillPayload(BaseModel):
    project_id: str | None = None
    background: bool = True


class MemoryRefreshPayload(BaseModel):
    document_id: str | None = None
    turn_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None


def create_memory_router(*, service, store, foundation=None) -> APIRouter:
    """Expose the v1.2 evidence/retrieval system without owning canon.

    The router intentionally exposes read/debug/index operations only. Accepted
    World Bible truth remains owned by WorkspaceStore and its explicit review
    workflows; timeline refresh only rebuilds derived temporal projections.
    """

    router = APIRouter(prefix="/api/memory", tags=["memory"])

    def _timeline_changed(domain_event):
        event = domain_event.payload.get("event") or {}
        world_id = event.get("world_id")
        refresh = getattr(service, "refresh_timeline_state", None)
        if not world_id or not callable(refresh):
            return
        try:
            refresh(world_id, event.get("branch_id"))
        except Exception as exc:
            reporter = getattr(service, "_report_refresh_failure", None)
            if callable(reporter):
                reporter(f"timeline:{world_id}", exc)

    workspace = getattr(service, "workspace", None)
    workspace_path = getattr(workspace, "path", getattr(store, "path", "arline-memory.db"))
    get_domain_event_bus(workspace_path).subscribe(
        "workspace.timeline_event_created",
        _timeline_changed,
        key="memory.timeline_refresh",
    )
    # Compatibility/status marker only. WorkspaceStore is not monkey-patched.
    service._v121_timeline_refresh_hook_bound = True
    attach_discovery(router, memory_service=service, foundation=foundation)

    @router.get("/status")
    def status():
        result = service.status()
        discovery = getattr(service, "discovery", None)
        if discovery is not None:
            try:
                result["discovery"] = discovery.store.status()
            except Exception:
                result["discovery"] = {"unavailable": True}
        return result

    @router.post("/query")
    def query(payload: MemoryQueryPayload):
        if not payload.query.strip():
            raise HTTPException(400, "Memory query is empty")
        try:
            context = MemoryQueryContext(
                project_id=payload.project_id,
                world_id=payload.world_id,
                branch_id=payload.branch_id,
                session_id=payload.session_id,
                current_turn_id=payload.current_turn_id,
                world_time=payload.world_time,
                story_order=payload.story_order,
                pov_variant_id=payload.pov_variant_id,
                context_lens=payload.context_lens,
                retrieval_mode=payload.retrieval_mode,
                explicit_references=payload.explicit_references,
                explicit_cross_scope_sources=payload.explicit_cross_scope_sources,
                allow_scratch=payload.allow_scratch,
                allow_future_author_knowledge=payload.allow_future_author_knowledge,
            )
            return service.retrieve(payload.query, context).to_dict()
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/retrieval/{run_id}")
    def retrieval_trace(run_id: str):
        try:
            return store.get_retrieval_run(run_id)
        except KeyError as exc:
            raise HTTPException(404, "Retrieval run not found") from exc

    @router.get("/index-generations")
    def index_generations(limit: int = Query(50, ge=1, le=200)):
        return {"items": store.list_generations(limit=limit), "active": store.active_generation()}

    @router.get("/chunks")
    def chunks(
        resource_type: str | None = Query(None),
        resource_id: str | None = Query(None),
        source_type: str | None = Query(None),
        source_id: str | None = Query(None),
        limit: int = Query(100, ge=1, le=1000),
    ):
        if resource_type and resource_id:
            items = store.list_linked_chunks(resource_type, resource_id, limit=limit)
        else:
            items = store.list_chunks(source_type=source_type, source_id=source_id, limit=limit)
        return {"items": items}

    @router.get("/spatial/neighborhood")
    def spatial_neighborhood(
        world_id: str = Query(...),
        resource_type: str = Query(...),
        resource_id: str = Query(...),
        branch_id: str | None = Query(None),
        depth: int = Query(2, ge=0, le=8),
    ):
        return store.spatial_neighborhood(
            world_id=world_id,
            branch_id=branch_id,
            resource_type=resource_type,
            resource_id=resource_id,
            depth=depth,
        )

    @router.get("/threads")
    def threads(
        world_id: str = Query(...),
        branch_id: str | None = Query(None),
        status: str | None = Query(None),
        resource_type: str | None = Query(None),
        resource_id: str | None = Query(None),
    ):
        return {"items": store.list_threads(
            world_id=world_id,
            branch_id=branch_id,
            status=status,
            resource_type=resource_type,
            resource_id=resource_id,
        )}

    @router.get("/profiles")
    def profiles():
        return {"profiles": {key: profile.to_dict() for key, profile in TASK_PROFILES.items()}}

    @router.get("/schemas")
    def schemas():
        return {"schemas": sorted(SCHEMA_MODELS)}

    @router.get("/schemas/{schema_id}")
    def schema(schema_id: str):
        try:
            return {"id": schema_id, "schema": schema_document(schema_id)}
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    def _run_backfill(job_id: str | None, project_id: str | None) -> None:
        try:
            if job_id and foundation is not None:
                foundation.update_job(job_id, status="running", progress=0.05, message="Indexing evidence")
            result = service.backfill(project_id)
            if job_id and foundation is not None:
                foundation.update_job(job_id, status="done", progress=1.0, message="Memory index ready", result=result)
        except Exception as exc:
            if job_id and foundation is not None:
                foundation.update_job(job_id, status="failed", message=str(exc))
            else:
                raise

    @router.post("/backfill")
    def backfill(payload: MemoryBackfillPayload, background_tasks: BackgroundTasks):
        if not payload.background or foundation is None:
            return service.backfill(payload.project_id)
        job = foundation.create_job(
            "memory_backfill",
            project_id=payload.project_id,
            payload={"project_id": payload.project_id},
            message="Queued memory indexing",
        )
        background_tasks.add_task(_run_backfill, job["id"], payload.project_id)
        return {"job": job, "queued": True}

    @router.get("/jobs/{job_id}")
    def memory_job(job_id: str):
        if foundation is None:
            raise HTTPException(404, "Job service unavailable")
        try:
            return foundation.get_job(job_id)
        except KeyError as exc:
            raise HTTPException(404, "Memory job not found") from exc

    @router.post("/refresh")
    def refresh(payload: MemoryRefreshPayload):
        if payload.document_id:
            return {"document": service.refresh_document(payload.document_id)}
        if payload.turn_id:
            return {"turn": service.refresh_turn(payload.turn_id)}
        if payload.world_id:
            refresh_timeline = getattr(service, "refresh_timeline_state", None)
            if not callable(refresh_timeline):
                raise HTTPException(409, "Timeline temporal projection is unavailable")
            return {"timeline_state": refresh_timeline(payload.world_id, payload.branch_id)}
        raise HTTPException(400, "Provide document_id, turn_id, or world_id")

    return router