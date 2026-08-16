from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from src.context import TraceResolver
from src.eval import AblationRunner
from src.history import HistoryStore, VALID_FEEDBACK
from src.inference import LMStudioError, LMStudioModelManager
from src.runtime_config import DEFAULT_CONFIG_PATH, RuntimeConfig, VALID_INPUT_MODES, VALID_REASONING, VALID_PROJECTION_MODES
from src.service import ArlineService, ArtifactStore, make_run_id
from src.workspace import (
    BRANCH_KINDS,
    CANON_STATUSES,
    DOCUMENT_TYPES,
    ENTITY_TYPES,
    WorkspaceContextResolver,
    WorkspaceStore,
)


MODE_LABELS = {
    "smart_hybrid": "Smart Hybrid",
    "wcf": "WCF only",
    "raw": "Raw only",
    "wcf_raw": "WCF + Raw",
    "aif_core": "AIF-Core",
}


class RuntimePayload(BaseModel):
    server_url: str = "http://127.0.0.1:1234"
    api_key: str = ""
    model: str = ""
    gpu_ratio: float = Field(1.0, ge=0.0, le=1.0)
    context_length: int = Field(32768, gt=0)
    input_mode: str = "smart_hybrid"
    reasoning: str = "off"
    projection_mode: str = "balanced"
    temperature: float = Field(0.8, ge=0.0, le=2.0)
    top_p: float = Field(0.95, ge=0.0, le=1.0)
    top_k: int = Field(40, ge=1)
    min_p: float = Field(0.0, ge=0.0, le=1.0)
    repeat_penalty: float = Field(1.05, gt=0.0)
    visible_output_tokens: int = Field(4096, gt=0)
    reasoning_reserve_tokens: int = Field(4096, ge=0)
    generation_mode: str = "single"
    beat_count: int = Field(4, ge=1, le=20)
    beat_tokens: int = Field(2048, ge=256)
    total_story_target_tokens: int = Field(8192, ge=256)


class ReferencePayload(BaseModel):
    type: str
    id: str
    label: str = ""


class PromptPayload(RuntimePayload):
    prompt: str
    timezone: str | None = None
    session_id: str | None = None
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    folder_id: str | None = None
    references: list[ReferencePayload] = Field(default_factory=list)


class SavePayload(BaseModel):
    run_id: str


class AblationPayload(PromptPayload):
    conditions: list[str] = Field(default_factory=list)


class ContractPayload(BaseModel):
    content: str


class SessionPatchPayload(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    archived: bool | None = None
    project: str | None = None
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    folder_id: str | None = None
    session_kind: str | None = None
    tags: list[str] | None = None
    workspace_refs: list[dict[str, Any]] | None = None


class FeedbackPayload(BaseModel):
    status: str
    issues: list[str] = Field(default_factory=list)
    note: str = ""
    edited_story: str = ""


class ProjectPayload(BaseModel):
    name: str
    description: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)


class ProjectPatchPayload(BaseModel):
    name: str | None = None
    description: str | None = None
    pinned: bool | None = None
    archived: bool | None = None
    default_world_id: str | None = None
    settings: dict[str, Any] | None = None


class WorldPayload(BaseModel):
    project_id: str
    name: str
    description: str = ""
    parent_world_id: str | None = None
    canon_status: str = "draft"
    inheritance_mode: str = "snapshot"
    clone_parent: bool = True


class WorldPatchPayload(BaseModel):
    name: str | None = None
    description: str | None = None
    canon_status: str | None = None
    inheritance_mode: str | None = None
    settings: dict[str, Any] | None = None


class BranchPayload(BaseModel):
    world_id: str
    name: str
    parent_branch_id: str | None = None
    kind: str = "sandbox"
    canon_status: str = "what_if"
    description: str = ""


class BranchPatchPayload(BaseModel):
    name: str | None = None
    kind: str | None = None
    canon_status: str | None = None
    description: str | None = None


class SessionForkPayload(BaseModel):
    through_turn_id: str | None = None
    title: str | None = None


class FolderPayload(BaseModel):
    project_id: str
    name: str
    world_id: str | None = None
    branch_id: str | None = None
    parent_id: str | None = None
    kind: str = "mixed"


class FolderPatchPayload(BaseModel):
    name: str | None = None
    parent_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    kind: str | None = None
    sort_order: int | None = None


class EntityFamilyPayload(BaseModel):
    project_id: str
    name: str
    folder_id: str | None = None
    entity_type: str = "character"
    description: str = ""
    shared_core: dict[str, Any] = Field(default_factory=dict)
    create_variant_in_world: str | None = None
    branch_id: str | None = None


class EntityFamilyPatchPayload(BaseModel):
    name: str | None = None
    folder_id: str | None = None
    description: str | None = None
    shared_core: dict[str, Any] | None = None
    note: str = "updated"


class EntityVariantPayload(BaseModel):
    family_id: str
    world_id: str
    branch_id: str | None = None
    display_name: str | None = None
    summary: str = ""
    canon_status: str = "draft"
    inherit_from_variant_id: str | None = None
    inherit_sections: list[str] = Field(default_factory=lambda: ["attributes", "voice"])
    attributes: dict[str, Any] = Field(default_factory=dict)
    voice: dict[str, Any] = Field(default_factory=dict)
    knowledge: dict[str, Any] = Field(default_factory=dict)
    beliefs: dict[str, Any] = Field(default_factory=dict)
    current_state: dict[str, Any] = Field(default_factory=dict)


class EntityVariantPatchPayload(BaseModel):
    display_name: str | None = None
    summary: str | None = None
    canon_status: str | None = None
    attributes: dict[str, Any] | None = None
    voice: dict[str, Any] | None = None
    knowledge: dict[str, Any] | None = None
    beliefs: dict[str, Any] | None = None
    current_state: dict[str, Any] | None = None
    note: str = "updated"


class RelationshipPayload(BaseModel):
    world_id: str
    subject_variant_id: str
    object_variant_id: str
    relation_type: str
    branch_id: str | None = None
    status: str = "current"
    canon_status: str = "draft"
    attributes: dict[str, Any] = Field(default_factory=dict)


class RelationshipPatchPayload(BaseModel):
    relation_type: str | None = None
    status: str | None = None
    canon_status: str | None = None
    attributes: dict[str, Any] | None = None
    note: str = "updated"


class DocumentPayload(BaseModel):
    project_id: str
    title: str
    document_type: str = "draft"
    content: str = ""
    world_id: str | None = None
    branch_id: str | None = None
    folder_id: str | None = None
    status: str = "draft"


class DocumentPatchPayload(BaseModel):
    title: str | None = None
    content: str | None = None
    status: str | None = None
    folder_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    sort_order: int | None = None
    note: str = "updated"


class TagPayload(BaseModel):
    project_id: str
    name: str
    color: str = "#6b7280"
    kind: str = "organizational"


class TagLinkPayload(BaseModel):
    resource_type: str
    resource_id: str


class FactPayload(BaseModel):
    project_id: str
    owner_type: str
    owner_id: str
    path: str
    value: Any
    world_id: str | None = None
    branch_id: str | None = None
    status: str = "draft"
    authority: str = "user_explicit"
    source_type: str = "manual"
    source_id: str | None = None


class RetconPayload(BaseModel):
    project_id: str
    world_id: str
    branch_id: str | None = None
    owner_type: str
    owner_id: str
    path: str
    new_value: Any
    note: str = ""


class SnapshotPayload(BaseModel):
    project_id: str
    world_id: str
    branch_id: str | None = None
    name: str = "Snapshot"
    description: str = ""


class RestoreSnapshotPayload(BaseModel):
    branch_name: str | None = None


class RevisionRestorePayload(BaseModel):
    note: str = "restored in Arline Studio"


class ContextPinPayload(BaseModel):
    project_id: str
    resource_type: str
    resource_id: str
    world_id: str | None = None
    branch_id: str | None = None
    scope: str = "world"
    priority: int = 1


class TemplatePayload(BaseModel):
    name: str
    entity_type: str
    template: dict[str, Any] = Field(default_factory=dict)
    project_id: str | None = None
    description: str = ""


class SceneDependencyPayload(BaseModel):
    project_id: str
    scene_document_id: str
    requirement_type: str
    target_type: str
    target_id: str
    world_id: str | None = None
    branch_id: str | None = None
    condition: dict[str, Any] = Field(default_factory=dict)


class ConflictPayload(BaseModel):
    project_id: str
    owner_type: str
    owner_id: str
    path: str
    left: Any
    right: Any
    world_id: str | None = None
    branch_id: str | None = None
    conflict_class: str = "hard_contradiction"


class ConflictResolutionPayload(BaseModel):
    resolution_type: str
    chosen_value: Any = None
    note: str = ""


@dataclass(slots=True)
class CachedRun:
    config: RuntimeConfig
    bundle: Any
    run_id: str


class RunCache:
    def __init__(self, max_items: int = 20):
        self.max_items = max_items
        self._items: OrderedDict[str, CachedRun] = OrderedDict()
        self._lock = RLock()

    def put(self, item: CachedRun) -> None:
        with self._lock:
            self._items[item.run_id] = item
            self._items.move_to_end(item.run_id)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)

    def get(self, run_id: str) -> CachedRun | None:
        with self._lock:
            item = self._items.get(run_id)
            if item:
                self._items.move_to_end(run_id)
            return item


class AnalysisCache:
    def __init__(self, max_items: int = 20):
        self.max_items = max_items
        self._items: OrderedDict[str, Any] = OrderedDict()
        self._lock = RLock()

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)

    def get(self, key: str):
        with self._lock:
            value = self._items.get(key)
            if value:
                self._items.move_to_end(key)
            return value


def _apply_payload(cfg: RuntimeConfig, payload: RuntimePayload) -> RuntimeConfig:
    if payload.input_mode not in VALID_INPUT_MODES:
        raise ValueError(f"Unsupported input mode: {payload.input_mode}")
    if payload.reasoning not in VALID_REASONING:
        raise ValueError(f"Unsupported reasoning mode: {payload.reasoning}")
    if payload.projection_mode not in VALID_PROJECTION_MODES:
        raise ValueError(f"Unsupported projection mode: {payload.projection_mode}")

    cfg.lmstudio.base_url = RuntimeConfig.normalize_server_url(payload.server_url)
    cfg.lmstudio.api_key = payload.api_key or ""
    cfg.lmstudio.model = payload.model or ""
    cfg.model_load.gpu_ratio = float(payload.gpu_ratio)
    cfg.model_load.context_length = int(payload.context_length)
    cfg.writer.input_mode = payload.input_mode
    cfg.generation.reasoning = payload.reasoning
    cfg.projection.mode = payload.projection_mode
    cfg.generation.temperature = float(payload.temperature)
    cfg.generation.top_p = float(payload.top_p)
    cfg.generation.top_k = int(payload.top_k)
    cfg.generation.min_p = float(payload.min_p)
    cfg.generation.repeat_penalty = float(payload.repeat_penalty)
    cfg.generation.visible_output_tokens = int(payload.visible_output_tokens)
    cfg.generation.reasoning_reserve_tokens = int(payload.reasoning_reserve_tokens)
    cfg.generation.generation_mode = payload.generation_mode
    cfg.generation.beat_count = int(payload.beat_count)
    cfg.generation.beat_tokens = int(payload.beat_tokens)
    cfg.generation.total_story_target_tokens = int(payload.total_story_target_tokens)
    return cfg


def _analysis_summary(bundle) -> dict[str, Any]:
    coverage = bundle.pipeline_result.extracted_state.get("coverage", {}) or {}
    return {
        "semantic_coverage": coverage.get("semantic_coverage_score"),
        "entities": len(bundle.pipeline_result.extracted_state.get("entities", []) or []),
        "relations": len(bundle.pipeline_result.extracted_state.get("relations", []) or []),
        "runtime_events": len(bundle.pipeline_result.events.get("events", []) or []),
        "scenario_events": len(bundle.pipeline_result.events.get("scenario_events", []) or []),
        "facts": len(bundle.semantic_core.facts),
        "transitions": len(bundle.semantic_core.transitions),
        "unknowns": len(bundle.writer_context.unknown),
        "projections": len(bundle.writer_context.projections),
        "wcf_tokens": bundle.rendered_context.metadata.get("estimated_tokens"),
        "wcf_budget": bundle.rendered_context.metadata.get("budget_tokens"),
        "token_counter": bundle.rendered_context.metadata.get("token_counter"),
    }


def _context_breakdown(cfg: RuntimeConfig, bundle, *, session_context: str = "") -> dict[str, Any]:
    def estimate(text: str) -> int:
        return max(0, len(text or "") // 4)

    workspace_tokens = (
        bundle.workspace_context.estimated_tokens
        if bundle.workspace_context is not None
        else 0
    )
    items = {
        "system_contract": cfg.context_budget.system_prompt_token_estimate,
        "workspace": workspace_tokens,
        "narrative_brief": estimate(bundle.narrative_brief.text),
        "wcf": int(bundle.rendered_context.metadata.get("estimated_tokens") or estimate(bundle.rendered_context.text)),
        "session_continuity": estimate(session_context),
        "output_ceiling": cfg.generation.api_max_output_tokens,
        "safety_margin": cfg.context_budget.safety_margin,
    }
    input_total = sum(
        value for key, value in items.items()
        if key not in {"output_ceiling", "safety_margin"}
    )
    reserved_total = input_total + items["output_ceiling"] + items["safety_margin"]
    return {
        "items": items,
        "estimated_input_tokens": input_total,
        "estimated_total_reserved": reserved_total,
        "model_context_length": cfg.model_load.context_length,
        "usage_ratio": round(reserved_total / max(1, cfg.model_load.context_length), 4),
        "remaining_tokens": max(0, cfg.model_load.context_length - reserved_total),
    }


def _trace_choices(bundle) -> list[dict[str, str]]:
    choices: list[dict[str, str]] = []
    seen: set[str] = set()
    for trace_id, trace in (bundle.writer_context.trace_index or {}).items():
        if trace_id in seen:
            continue
        seen.add(trace_id)
        label = trace.get("writer_fact") or trace.get("key") or trace_id
        choices.append({"id": trace_id, "label": str(label)})
    return choices[:300]


def _public_config(cfg: RuntimeConfig) -> dict[str, Any]:
    return {
        "server_url": cfg.lmstudio.base_url,
        "api_key": cfg.lmstudio.api_key,
        "model": cfg.lmstudio.model,
        "gpu_ratio": cfg.model_load.gpu_ratio,
        "context_length": cfg.model_load.context_length,
        "input_mode": cfg.writer.input_mode,
        "reasoning": cfg.generation.reasoning,
        "projection_mode": cfg.projection.mode,
        "temperature": cfg.generation.temperature,
        "top_p": cfg.generation.top_p,
        "top_k": cfg.generation.top_k,
        "min_p": cfg.generation.min_p,
        "repeat_penalty": cfg.generation.repeat_penalty,
        "visible_output_tokens": cfg.generation.visible_output_tokens,
        "reasoning_reserve_tokens": cfg.generation.reasoning_reserve_tokens,
        "generation_mode": cfg.generation.generation_mode,
        "beat_count": cfg.generation.beat_count,
        "beat_tokens": cfg.generation.beat_tokens,
        "total_story_target_tokens": cfg.generation.total_story_target_tokens,
        "api_max_output_tokens": cfg.generation.api_max_output_tokens,
        "modes": MODE_LABELS,
        "reasoning_modes": ["off", "on", "low", "medium", "high"],
        "projection_modes": ["off", "conservative", "balanced", "vivid"],
        "generation_modes": ["single", "beats"],
        "workspace": {
            "database_path": str(cfg.workspace.database_path),
            "default_project_id": cfg.workspace.default_project_id,
            "context_enabled": cfg.workspace.context_enabled,
            "mention_limit": cfg.workspace.mention_limit,
            "autosave_drafts": cfg.workspace.autosave_drafts,
            "language_mode": cfg.workspace.language_mode,
        },
        "history": {
            "database_path": str(cfg.history.database_path),
            "dataset_root": str(cfg.history.dataset_root),
            "recent_limit": cfg.history.recent_limit,
        },
        "reasoning_guard": {
            "enforce_model_capabilities": cfg.reasoning_runtime.enforce_model_capabilities,
            "dominance_ratio_warn": cfg.reasoning_runtime.dominance_ratio_warn,
            "reasoning_share_warn": cfg.reasoning_runtime.reasoning_share_warn,
            "story_target_ratio_warn": cfg.reasoning_runtime.story_target_ratio_warn,
        },
    }


def create_app(config_path: Path | str = DEFAULT_CONFIG_PATH) -> FastAPI:
    config_path = Path(config_path)
    base_dir = Path(__file__).resolve().parent
    static_dir = base_dir / "static"
    saved_cache = RunCache(max_items=20)
    analysis_cache = AnalysisCache(max_items=20)
    initial_cfg = RuntimeConfig.load(config_path)
    history = HistoryStore(initial_cfg.history.database_path)
    workspace = WorkspaceStore(initial_cfg.workspace.database_path)
    workspace_context = WorkspaceContextResolver(
        workspace, max_items=initial_cfg.workspace.pinned_context_limit
    )

    app = FastAPI(title="Arline Studio", version="0.6.4")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def index():
        return FileResponse(static_dir / "index.html")

    @app.get("/api/config")
    def get_config():
        return _public_config(RuntimeConfig.load(config_path))

    @app.get("/api/models")
    def get_models(
        server_url: str = Query("http://127.0.0.1:1234"),
        api_key: str = Query(""),
    ):
        cfg = RuntimeConfig.load(config_path)
        cfg.lmstudio.base_url = RuntimeConfig.normalize_server_url(server_url)
        cfg.lmstudio.api_key = api_key
        service = ArlineService(cfg)
        try:
            models = service.list_models()
        except Exception as exc:
            raise HTTPException(503, str(exc)) from exc
        return {
            "models": [
                {
                    "key": item.get("key"),
                    "display_name": item.get("display_name") or item.get("key"),
                    "loaded": bool(item.get("loaded_instances")),
                    "max_context_length": item.get("max_context_length"),
                    "reasoning": (item.get("capabilities") or {}).get("reasoning") or item.get("reasoning") or {},
                    "format": item.get("format"),
                }
                for item in models
            ]
        }

    @app.post("/api/settings")
    def save_settings(payload: RuntimePayload):
        cfg = _apply_payload(RuntimeConfig.load(config_path), payload)
        cfg.save_runtime_values()
        return {"ok": True, "config": _public_config(cfg)}

    @app.post("/api/model/reload")
    def reload_model(payload: RuntimePayload):
        cfg = _apply_payload(RuntimeConfig.load(config_path), payload)
        try:
            result = ArlineService(cfg).reload_model()
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc
        return result

    # ------------------------------------------------------------------
    # Project / world / library workspace API
    # ------------------------------------------------------------------

    @app.get("/api/workspace/bootstrap")
    def workspace_bootstrap(create_default: bool = Query(True)):
        projects = workspace.list_projects()
        if not projects and create_default:
            workspace.create_project(
                "My Stories",
                description="Default Arline workspace",
                settings={
                    "preferred_model": initial_cfg.lmstudio.model,
                    "reasoning": initial_cfg.generation.reasoning,
                    "projection_mode": initial_cfg.projection.mode,
                    "language": "follow_prompt",
                },
            )
            projects = workspace.list_projects()
        active_project = None
        active_world = None
        active_branch = None
        if projects:
            preferred = initial_cfg.workspace.default_project_id
            active_project = next((x for x in projects if x["id"] == preferred), projects[0])
            details = workspace.get_project(active_project["id"])
            worlds = details.get("worlds", [])
            if worlds:
                active_world = next(
                    (x for x in worlds if x["id"] == active_project.get("default_world_id")),
                    worlds[0],
                )
                branches = workspace.list_branches(active_world["id"])
                active_branch = next((x for x in branches if x["kind"] == "main"), branches[0] if branches else None)
        return {
            "projects": projects,
            "active": {
                "project": active_project,
                "world": active_world,
                "branch": active_branch,
            },
            "canon_statuses": sorted(CANON_STATUSES),
            "entity_types": sorted(ENTITY_TYPES),
            "document_types": sorted(DOCUMENT_TYPES),
            "branch_kinds": sorted(BRANCH_KINDS),
        }

    @app.get("/api/projects")
    def list_projects(search: str = Query(""), include_archived: bool = Query(False)):
        return {"projects": workspace.list_projects(search=search, include_archived=include_archived)}

    @app.post("/api/projects")
    def create_project(payload: ProjectPayload):
        try:
            return workspace.create_project(payload.name, description=payload.description, settings=payload.settings)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str):
        try:
            result = workspace.get_project(project_id)
            result["folders"] = workspace.folder_tree(project_id)
            result["tags"] = workspace.list_tags(project_id)
            return result
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc

    @app.patch("/api/projects/{project_id}")
    def patch_project(project_id: str, payload: ProjectPatchPayload):
        try:
            return workspace.update_project(project_id, **payload.model_dump(exclude_none=True))
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: str):
        try:
            workspace.delete_project(project_id)
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc
        return {"ok": True}

    @app.get("/api/projects/{project_id}/tree")
    def project_tree(project_id: str, world_id: str | None = Query(None), branch_id: str | None = Query(None)):
        try:
            return {
                "project": workspace.get_project(project_id),
                "worlds": workspace.list_worlds(project_id),
                "folders": workspace.folder_tree(project_id, world_id=world_id, branch_id=branch_id),
                "documents": workspace.list_documents(project_id, world_id=world_id, branch_id=branch_id),
                "families": workspace.list_entity_families(project_id),
                "tags": workspace.list_tags(project_id),
                "templates": workspace.list_templates(project_id=project_id),
                "conflicts": workspace.list_conflicts(
                    project_id=project_id, world_id=world_id, branch_id=branch_id, status="open"
                ),
            }
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc

    @app.post("/api/worlds")
    def create_world(payload: WorldPayload):
        try:
            return workspace.create_world(**payload.model_dump())
        except KeyError as exc:
            raise HTTPException(404, "Project or parent world not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/worlds/{world_id}")
    def get_world(world_id: str):
        try:
            result = workspace.get_world(world_id)
            result["snapshots"] = workspace.list_snapshots(world_id)
            return result
        except KeyError as exc:
            raise HTTPException(404, "World not found") from exc

    @app.patch("/api/worlds/{world_id}")
    def patch_world(world_id: str, payload: WorldPatchPayload):
        try:
            return workspace.update_world(world_id, **payload.model_dump(exclude_none=True))
        except KeyError as exc:
            raise HTTPException(404, "World not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/worlds/{world_id}/fork")
    def fork_world(world_id: str, payload: WorldPayload):
        try:
            return workspace.fork_world(
                world_id, payload.name, description=payload.description,
                canon_status=payload.canon_status or "what_if",
            )
        except KeyError as exc:
            raise HTTPException(404, "World not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/worlds/compare/{left_world_id}/{right_world_id}")
    def compare_worlds(left_world_id: str, right_world_id: str):
        try:
            return workspace.compare_worlds(left_world_id, right_world_id)
        except KeyError as exc:
            raise HTTPException(404, "World not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/branches")
    def create_branch(payload: BranchPayload):
        try:
            return workspace.create_branch(**payload.model_dump())
        except KeyError as exc:
            raise HTTPException(404, "World not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/worlds/{world_id}/sandbox")
    def create_sandbox(world_id: str, name: str = Query("Sandbox")):
        try:
            return workspace.create_sandbox(world_id, name=name)
        except KeyError as exc:
            raise HTTPException(404, "World not found") from exc

    @app.patch("/api/branches/{branch_id}")
    def patch_branch(branch_id: str, payload: BranchPatchPayload):
        data = payload.model_dump(exclude_none=True)
        try:
            return workspace.update_branch(branch_id, **data)
        except KeyError as exc:
            raise HTTPException(404, "Branch not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/folders")
    def create_folder(payload: FolderPayload):
        try:
            return workspace.create_folder(**payload.model_dump())
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.patch("/api/folders/{folder_id}")
    def patch_folder(folder_id: str, payload: FolderPatchPayload):
        try:
            return workspace.update_folder(folder_id, **payload.model_dump(exclude_none=True))
        except KeyError as exc:
            raise HTTPException(404, "Folder not found") from exc

    @app.delete("/api/folders/{folder_id}")
    def delete_folder(folder_id: str):
        try:
            workspace.delete_folder(folder_id)
        except KeyError as exc:
            raise HTTPException(404, "Folder not found") from exc
        return {"ok": True}

    @app.post("/api/documents")
    def create_document(payload: DocumentPayload):
        try:
            return workspace.create_document(**payload.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/documents")
    def list_documents(
        project_id: str = Query(...), world_id: str | None = Query(None),
        branch_id: str | None = Query(None), folder_id: str | None = Query(None),
        document_type: str | None = Query(None),
    ):
        return {"documents": workspace.list_documents(
            project_id, world_id=world_id, branch_id=branch_id,
            folder_id=folder_id, document_type=document_type,
        )}

    @app.get("/api/documents/{document_id}")
    def get_document(document_id: str):
        try:
            result = workspace.get_document(document_id)
            result["revisions"] = workspace.list_revisions("document", document_id)
            return result
        except KeyError as exc:
            raise HTTPException(404, "Document not found") from exc

    @app.patch("/api/documents/{document_id}")
    def patch_document(document_id: str, payload: DocumentPatchPayload):
        data = payload.model_dump(exclude_none=True)
        note = data.pop("note", "updated")
        try:
            return workspace.update_document(document_id, note=note, **data)
        except KeyError as exc:
            raise HTTPException(404, "Document not found") from exc

    @app.delete("/api/documents/{document_id}")
    def delete_document(document_id: str):
        try:
            workspace.delete_document(document_id)
        except KeyError as exc:
            raise HTTPException(404, "Document not found") from exc
        return {"ok": True}

    @app.post("/api/entities/families")
    def create_entity_family(payload: EntityFamilyPayload):
        try:
            return workspace.create_entity_family(**payload.model_dump())
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/entities/families")
    def list_entity_families(
        project_id: str = Query(...), entity_type: str | None = Query(None), search: str = Query("")
    ):
        return {"families": workspace.list_entity_families(project_id, entity_type=entity_type, search=search)}

    @app.get("/api/entities/families/{family_id}")
    def get_entity_family(family_id: str):
        try:
            return workspace.get_entity_family(family_id)
        except KeyError as exc:
            raise HTTPException(404, "Entity family not found") from exc

    @app.patch("/api/entities/families/{family_id}")
    def patch_entity_family(family_id: str, payload: EntityFamilyPatchPayload):
        data = payload.model_dump(exclude_none=True)
        note = data.pop("note", "updated")
        try:
            return workspace.update_entity_family(family_id, note=note, **data)
        except KeyError as exc:
            raise HTTPException(404, "Entity family not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/entities/variants")
    def create_entity_variant(payload: EntityVariantPayload):
        try:
            return workspace.create_variant(**payload.model_dump())
        except (KeyError, ValueError, sqlite3.IntegrityError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/entities/variants")
    def list_entity_variants(
        project_id: str | None = Query(None), family_id: str | None = Query(None),
        world_id: str | None = Query(None), branch_id: str | None = Query(None),
        entity_type: str | None = Query(None),
    ):
        return {"variants": workspace.list_variants(
            project_id=project_id, family_id=family_id, world_id=world_id,
            branch_id=branch_id, entity_type=entity_type,
        )}

    @app.get("/api/entities/variants/{variant_id}")
    def get_entity_variant(variant_id: str):
        try:
            return workspace.get_variant(variant_id)
        except KeyError as exc:
            raise HTTPException(404, "Variant not found") from exc

    @app.patch("/api/entities/variants/{variant_id}")
    def patch_entity_variant(variant_id: str, payload: EntityVariantPatchPayload):
        data = payload.model_dump(exclude_none=True)
        note = data.pop("note", "updated")
        try:
            return workspace.update_variant(variant_id, note=note, **data)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/entities/variants/compare/{left_variant_id}/{right_variant_id}")
    def compare_entity_variants(left_variant_id: str, right_variant_id: str):
        try:
            return workspace.compare_variants(left_variant_id, right_variant_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/relationships")
    def create_relationship(payload: RelationshipPayload):
        try:
            return workspace.create_relationship(**payload.model_dump())
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/relationships")
    def list_relationships(
        world_id: str = Query(...), branch_id: str | None = Query(None), variant_id: str | None = Query(None)
    ):
        return {"relationships": workspace.list_relationships(
            world_id=world_id, branch_id=branch_id, variant_id=variant_id
        )}

    @app.get("/api/relationships/{relationship_id}")
    def get_relationship(relationship_id: str):
        try:
            return workspace.get_relationship(relationship_id)
        except KeyError as exc:
            raise HTTPException(404, "Relationship not found") from exc

    @app.patch("/api/relationships/{relationship_id}")
    def patch_relationship(relationship_id: str, payload: RelationshipPatchPayload):
        data = payload.model_dump(exclude_none=True)
        note = data.pop("note", "updated")
        try:
            return workspace.update_relationship(relationship_id, note=note, **data)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/templates")
    def list_templates(project_id: str | None = Query(None), entity_type: str | None = Query(None)):
        return {"templates": workspace.list_templates(project_id=project_id, entity_type=entity_type)}

    @app.post("/api/templates")
    def create_template(payload: TemplatePayload):
        try:
            return workspace.create_template(**payload.model_dump())
        except (KeyError, ValueError, sqlite3.IntegrityError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/scenes/{scene_document_id}/dependencies")
    def list_scene_dependencies(scene_document_id: str):
        return workspace.validate_scene_dependencies(scene_document_id)

    @app.post("/api/scenes/dependencies")
    def create_scene_dependency(payload: SceneDependencyPayload):
        try:
            return workspace.create_scene_dependency(**payload.model_dump())
        except (KeyError, ValueError, sqlite3.IntegrityError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/scenes/dependencies/{dependency_id}")
    def delete_scene_dependency(dependency_id: str):
        try:
            workspace.delete_scene_dependency(dependency_id)
        except KeyError as exc:
            raise HTTPException(404, "Dependency not found") from exc
        return {"ok": True}

    @app.get("/api/conflicts")
    def list_conflicts(
        project_id: str = Query(...), world_id: str | None = Query(None),
        branch_id: str | None = Query(None), status: str | None = Query("open"),
    ):
        return {"conflicts": workspace.list_conflicts(
            project_id=project_id, world_id=world_id, branch_id=branch_id, status=status,
        )}

    @app.post("/api/conflicts")
    def create_conflict(payload: ConflictPayload):
        try:
            return workspace.create_conflict(**payload.model_dump())
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/conflicts/{conflict_id}/resolve")
    def resolve_conflict(conflict_id: str, payload: ConflictResolutionPayload):
        try:
            return workspace.resolve_conflict(conflict_id, **payload.model_dump())
        except KeyError as exc:
            raise HTTPException(404, "Conflict not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/tags")
    def create_tag(payload: TagPayload):
        try:
            return workspace.create_tag(**payload.model_dump())
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/tags")
    def list_tags(project_id: str = Query(...)):
        return {"tags": workspace.list_tags(project_id)}

    @app.post("/api/tags/{tag_id}/link")
    def link_tag(tag_id: str, payload: TagLinkPayload):
        workspace.tag_resource(tag_id, payload.resource_type, payload.resource_id)
        return {"ok": True}

    @app.delete("/api/tags/{tag_id}/link")
    def unlink_tag(tag_id: str, resource_type: str = Query(...), resource_id: str = Query(...)):
        workspace.untag_resource(tag_id, resource_type, resource_id)
        return {"ok": True}

    @app.post("/api/facts")
    def create_fact(payload: FactPayload):
        try:
            return workspace.add_fact(**payload.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/facts")
    def list_facts(
        project_id: str | None = Query(None), world_id: str | None = Query(None),
        branch_id: str | None = Query(None), owner_type: str | None = Query(None),
        owner_id: str | None = Query(None),
    ):
        return {"facts": workspace.list_facts(
            project_id=project_id, world_id=world_id, branch_id=branch_id,
            owner_type=owner_type, owner_id=owner_id,
        )}

    @app.post("/api/canon/promote")
    def promote_to_canon(payload: FactPayload):
        """Promote a generated discovery through an explicit canon workflow.

        `canon` receives the stronger user_promoted authority. Draft,
        provisional, and what-if discoveries remain reviewable facts instead of
        being silently upgraded to canon.
        """
        try:
            if payload.status == "canon":
                return workspace.promote_to_canon(
                    project_id=payload.project_id,
                    world_id=payload.world_id or "",
                    branch_id=payload.branch_id,
                    owner_type=payload.owner_type,
                    owner_id=payload.owner_id,
                    path=payload.path,
                    value=payload.value,
                    source_turn_id=payload.source_id,
                )
            return workspace.add_fact(
                project_id=payload.project_id,
                world_id=payload.world_id,
                branch_id=payload.branch_id,
                owner_type=payload.owner_type,
                owner_id=payload.owner_id,
                path=payload.path,
                value=payload.value,
                status=payload.status,
                authority=payload.authority or "user_explicit",
                source_type=payload.source_type or "accepted_generated_prose",
                source_id=payload.source_id,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/retcon/preview")
    def retcon_preview(payload: RetconPayload):
        try:
            return workspace.retcon_preview(
                project_id=payload.project_id, world_id=payload.world_id,
                owner_type=payload.owner_type, owner_id=payload.owner_id,
                path=payload.path, new_value=payload.new_value,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/retcon/apply")
    def retcon_apply(payload: RetconPayload):
        try:
            return workspace.apply_retcon(**payload.model_dump())
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/revisions/{resource_type}/{resource_id}")
    def list_revisions(resource_type: str, resource_id: str):
        return {"revisions": workspace.list_revisions(resource_type, resource_id)}

    @app.post("/api/revisions/{revision_id}/restore")
    def restore_revision(revision_id: str, payload: RevisionRestorePayload):
        try:
            return workspace.restore_revision(revision_id, note=payload.note)
        except KeyError as exc:
            raise HTTPException(404, "Revision not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/snapshots")
    def create_snapshot(payload: SnapshotPayload):
        try:
            return workspace.create_snapshot(**payload.model_dump())
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/snapshots")
    def list_snapshots(world_id: str = Query(...)):
        return {"snapshots": workspace.list_snapshots(world_id)}

    @app.post("/api/snapshots/{snapshot_id}/restore")
    def restore_snapshot(snapshot_id: str, payload: RestoreSnapshotPayload):
        try:
            result = workspace.restore_snapshot(snapshot_id, branch_name=payload.branch_name)
            return {"snapshot_id": result.snapshot_id, "branch_id": result.branch_id, "mode": result.mode}
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/context/pins")
    def pin_context(payload: ContextPinPayload):
        return workspace.pin_context(**payload.model_dump())

    @app.delete("/api/context/pins/{pin_id}")
    def unpin_context(pin_id: str):
        workspace.unpin_context(pin_id)
        return {"ok": True}

    @app.get("/api/mentions")
    def mentions(
        q: str = Query(""), project_id: str = Query(...),
        world_id: str | None = Query(None), branch_id: str | None = Query(None),
        limit: int = Query(20, ge=1, le=50),
    ):
        return {"results": workspace.search_mentions(
            q, project_id=project_id, world_id=world_id,
            branch_id=branch_id, limit=limit,
        )}

    @app.get("/api/commands")
    def commands(q: str = Query(""), project_id: str | None = Query(None)):
        return {"results": workspace.command_search(q, project_id=project_id)}

    @app.get("/api/sessions")
    def list_sessions(
        search: str = Query(""),
        limit: int = Query(100, ge=1, le=500),
        project_id: str | None = Query(None),
        world_id: str | None = Query(None),
        branch_id: str | None = Query(None),
        folder_id: str | None = Query(None),
        tag: str | None = Query(None),
        session_kind: str | None = Query(None),
    ):
        return {"sessions": history.list_sessions(
            search=search, limit=limit, project_id=project_id,
            world_id=world_id, branch_id=branch_id, folder_id=folder_id,
            tag=tag, session_kind=session_kind,
        )}

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str):
        try:
            return history.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(404, "Session not found") from exc

    @app.post("/api/sessions/{session_id}/fork")
    def fork_session(session_id: str, payload: SessionForkPayload):
        try:
            return history.fork_session(
                session_id,
                through_turn_id=payload.through_turn_id,
                title=payload.title,
            )
        except KeyError as exc:
            raise HTTPException(404, "Session or turn not found") from exc

    @app.patch("/api/sessions/{session_id}")
    def update_session(session_id: str, payload: SessionPatchPayload):
        try:
            return history.update_session(
                session_id,
                title=payload.title,
                pinned=payload.pinned,
                archived=payload.archived,
                project=payload.project,
                project_id=payload.project_id,
                world_id=payload.world_id,
                branch_id=payload.branch_id,
                folder_id=payload.folder_id,
                session_kind=payload.session_kind,
                tags=payload.tags,
                workspace_refs=payload.workspace_refs,
            )
        except KeyError as exc:
            raise HTTPException(404, "Session not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/sessions/{session_id}")
    def delete_session(session_id: str):
        try:
            history.delete_session(session_id)
        except KeyError as exc:
            raise HTTPException(404, "Session not found") from exc
        return {"ok": True}

    @app.get("/api/turns/{turn_id}")
    def get_turn(turn_id: str):
        try:
            return history.get_turn(turn_id)
        except KeyError as exc:
            raise HTTPException(404, "Turn not found") from exc

    @app.post("/api/turns/{turn_id}/feedback")
    def set_turn_feedback(turn_id: str, payload: FeedbackPayload):
        if payload.status not in VALID_FEEDBACK:
            raise HTTPException(400, f"Unsupported feedback status: {payload.status}")
        try:
            turn = history.set_feedback(
                turn_id,
                status=payload.status,
                issues=payload.issues,
                note=payload.note,
                edited_story=payload.edited_story,
            )
        except KeyError as exc:
            raise HTTPException(404, "Turn not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "turn": turn, "dataset": history.dataset_stats()}

    @app.get("/api/dataset/stats")
    def dataset_stats():
        return history.dataset_stats()

    @app.post("/api/dataset/export/{kind}")
    def export_dataset(kind: str):
        cfg = RuntimeConfig.load(config_path)
        try:
            exported = history.export_dataset(kind, cfg.history.dataset_root)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            "ok": True,
            "kind": exported.kind,
            "rows": exported.rows,
            "filename": exported.path.name,
            "download_url": f"/dataset-downloads/{exported.path.name}",
        }

    @app.get("/dataset-downloads/{filename}")
    def download_dataset(filename: str):
        if Path(filename).name != filename:
            raise HTTPException(400, "Invalid filename")
        cfg = RuntimeConfig.load(config_path)
        path = cfg.history.dataset_root / filename
        if not path.exists() or not path.is_file():
            raise HTTPException(404, "Dataset export not found")
        return FileResponse(path, filename=path.name, media_type="application/x-ndjson")

    @app.get("/api/contract")
    def get_contract():
        cfg = RuntimeConfig.load(config_path)
        return {"content": cfg.writer.system_prompt_file.read_text(encoding="utf-8")}

    @app.post("/api/contract")
    def save_contract(payload: ContractPayload):
        cfg = RuntimeConfig.load(config_path)
        cfg.writer.system_prompt_file.write_text(payload.content.rstrip() + "\n", encoding="utf-8")
        return {"ok": True}

    @app.post("/api/analyze")
    def analyze(payload: PromptPayload):
        if not payload.prompt.strip():
            raise HTTPException(400, "Prompt is empty")
        cfg = _apply_payload(RuntimeConfig.load(config_path), payload)
        refs = [item.model_dump() for item in payload.references]
        try:
            ws_context = (
                workspace_context.resolve(
                    project_id=payload.project_id,
                    world_id=payload.world_id,
                    branch_id=payload.branch_id,
                    references=refs,
                )
                if cfg.workspace.context_enabled and payload.project_id
                else None
            )
            bundle = ArlineService(cfg).analyze(
                payload.prompt, workspace_context=ws_context
            )
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc
        analysis_id = "AN-" + make_run_id(payload.input_mode, payload.reasoning, payload.timezone)
        analysis_cache.put(analysis_id, bundle)
        return {
            "analysis_id": analysis_id,
            "summary": _analysis_summary(bundle),
            "wcf": bundle.rendered_context.text,
            "aif_core": bundle.aif_core,
            "narrative_brief": bundle.narrative_brief.to_dict(),
            "workspace_context": ws_context.to_dict() if ws_context else {},
            "context_breakdown": _context_breakdown(cfg, bundle),
            "projections": [x.to_dict() for x in bundle.writer_context.projections],
            "wcf_validation": bundle.wcf_validation.to_dict(),
            "trace_choices": _trace_choices(bundle),
        }

    @app.get("/api/trace/{cache_id}/{trace_id}")
    def trace(cache_id: str, trace_id: str):
        generated = saved_cache.get(cache_id)
        bundle = generated.bundle.analysis if generated else analysis_cache.get(cache_id)
        if bundle is None:
            raise HTTPException(404, "Analysis/run is no longer in the in-memory cache")
        result = TraceResolver.resolve(bundle.writer_context, trace_id)
        if not result:
            raise HTTPException(404, "Trace entry not found")
        return result

    @app.post("/api/generate")
    def generate(payload: PromptPayload):
        if not payload.prompt.strip():
            raise HTTPException(400, "Prompt is empty")
        existing_session = None
        if payload.session_id:
            try:
                existing_session = history.get_session_meta(payload.session_id)
            except KeyError as exc:
                raise HTTPException(404, "Session not found") from exc

        cfg = _apply_payload(RuntimeConfig.load(config_path), payload)
        project_id = payload.project_id or (existing_session or {}).get("project_id")
        world_id = payload.world_id or (existing_session or {}).get("world_id")
        branch_id = payload.branch_id or (existing_session or {}).get("branch_id")
        folder_id = payload.folder_id or (existing_session or {}).get("folder_id")
        refs = [item.model_dump() for item in payload.references]
        if not refs and existing_session:
            refs = existing_session.get("workspace_refs") or []

        ws_context = None
        if cfg.workspace.context_enabled and project_id:
            try:
                ws_context = workspace_context.resolve(
                    project_id=project_id,
                    world_id=world_id,
                    branch_id=branch_id,
                    references=refs,
                )
            except (KeyError, ValueError) as exc:
                raise HTTPException(400, f"Workspace context error: {exc}") from exc

        session_context = ""
        if (
            existing_session is not None
            and cfg.history.smart_hybrid_continuity
            and payload.input_mode == "smart_hybrid"
        ):
            session_context = history.build_continuity_context(
                existing_session["id"],
                max_turns=cfg.history.continuity_turns,
                max_chars=cfg.history.continuity_chars,
            )

        try:
            service = ArlineService(cfg)
            if payload.generation_mode == "beats":
                bundle = service.generate_beats(
                    payload.prompt,
                    mode=payload.input_mode,
                    session_context=session_context or None,
                    workspace_context=ws_context,
                    beat_count=payload.beat_count,
                    beat_tokens=payload.beat_tokens,
                )
            else:
                bundle = service.generate(
                    payload.prompt,
                    mode=payload.input_mode,
                    session_context=session_context or None,
                    workspace_context=ws_context,
                )
        except LMStudioError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc

        run_id = make_run_id(payload.input_mode, payload.reasoning, payload.timezone)
        base = run_id
        index = 2
        while saved_cache.get(run_id) is not None:
            run_id = f"{base}-{index:02d}"
            index += 1
        saved_cache.put(CachedRun(config=cfg, bundle=bundle, run_id=run_id))

        post = bundle.post_validation.to_dict() if bundle.post_validation else {}
        if existing_session is not None:
            session = existing_session
            history.update_session(
                session["id"],
                project_id=project_id,
                world_id=world_id,
                branch_id=branch_id,
                folder_id=folder_id,
                workspace_refs=refs,
            )
        else:
            session = history.create_session(
                prompt=payload.prompt,
                project_id=project_id,
                world_id=world_id,
                branch_id=branch_id,
                folder_id=folder_id,
                session_kind="chat",
                workspace_refs=refs,
            )

        lineage = {
            "application_version": "0.6.4",
            "wcf_version": bundle.analysis.writer_context.version,
            "aif_core_profile": "teacher",
            "projection_mode": cfg.projection.mode,
            "narrative_runtime_version": bundle.analysis.narrative_runtime.version,
            "narrative_brief_version": bundle.analysis.narrative_brief.version,
            "workspace_context_version": ws_context.version if ws_context else None,
            "validator_version": post.get("metrics", {}).get("validator_version") if post else None,
            "model": cfg.lmstudio.model,
        }
        turn = history.add_turn(
            session["id"],
            run_id=run_id,
            user_prompt=payload.prompt,
            story=bundle.story,
            model=cfg.lmstudio.model,
            mode=cfg.writer.input_mode,
            reasoning=cfg.generation.reasoning,
            projection_mode=cfg.projection.mode,
            reasoning_text=bundle.reasoning or "",
            stats=bundle.stats,
            wcf=bundle.analysis.rendered_context.text,
            aif_core=bundle.analysis.aif_core,
            session_context=session_context,
            workspace_context=ws_context.text if ws_context else "",
            workspace_scope=ws_context.scope if ws_context else {},
            workspace_refs=refs,
            lineage=lineage,
            projections=[x.to_dict() for x in bundle.analysis.writer_context.projections],
            post_validation=post,
            wcf_validation=bundle.analysis.wcf_validation.to_dict(),
        )
        session = history.get_session_meta(session["id"])

        return {
            "run_id": run_id,
            "session_id": session["id"],
            "session_title": session["title"],
            "turn_id": turn["id"],
            "continuity_context_used": bool(session_context),
            "story": bundle.story,
            "wcf": bundle.analysis.rendered_context.text,
            "aif_core": bundle.analysis.aif_core,
            "narrative_brief": bundle.analysis.narrative_brief.to_dict(),
            "workspace_context": ws_context.to_dict() if ws_context else {},
            "context_breakdown": _context_breakdown(
                cfg, bundle.analysis, session_context=session_context
            ),
            "projections": [x.to_dict() for x in bundle.analysis.writer_context.projections],
            "reasoning": bundle.reasoning if cfg.ui.show_reasoning else "",
            "stats": bundle.stats,
            "post_validation": post,
            "wcf_validation": bundle.analysis.wcf_validation.to_dict(),
            "summary": _analysis_summary(bundle.analysis),
            "trace_choices": _trace_choices(bundle.analysis),
            "budget": {
                "visible_target": cfg.generation.visible_output_tokens,
                "reasoning_reserve": cfg.generation.reasoning_reserve_tokens if cfg.generation.reasoning != "off" else 0,
                "api_max_output_tokens": cfg.generation.api_max_output_tokens,
                "generation_mode": payload.generation_mode,
                "beat_count": payload.beat_count if payload.generation_mode == "beats" else 1,
                "beat_tokens": payload.beat_tokens if payload.generation_mode == "beats" else None,
            },
        }


    @app.post("/api/ablation")
    def ablation(payload: AblationPayload):
        if not payload.prompt.strip():
            raise HTTPException(400, "Prompt is empty")
        cfg = _apply_payload(RuntimeConfig.load(config_path), payload)
        conditions = []
        for raw in payload.conditions:
            if ":" not in raw:
                continue
            mode, reasoning = raw.split(":", 1)
            if mode in VALID_INPUT_MODES and reasoning in VALID_REASONING:
                conditions.append((mode, reasoning))
        if not conditions:
            conditions = list(AblationRunner.DEFAULT_CONDITIONS)
        try:
            results = AblationRunner(cfg).run(payload.prompt, conditions=conditions)
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc
        return {"results": [item.to_dict() for item in results]}

    @app.post("/api/save")
    def save_run(payload: SavePayload):
        cached = saved_cache.get(payload.run_id)
        if cached is None:
            raise HTTPException(404, "Run is no longer in memory. Generate it again before saving.")
        store = ArtifactStore(cached.config.artifacts.saved_root)
        try:
            saved = store.save_generation(
                payload.run_id,
                cached.bundle,
                model=cached.config.lmstudio.model,
                mode=cached.config.writer.input_mode,
                reasoning=cached.config.generation.reasoning,
                projection_mode=cached.config.projection.mode,
            )
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc
        return {
            "ok": True,
            "run_id": saved.run_id,
            "directory": str(saved.directory),
            "archive_name": saved.archive.name,
            "download_url": f"/downloads/{saved.archive.name}",
            "files": {k: v.name for k, v in saved.files.items()},
        }

    @app.get("/downloads/{filename}")
    def download(filename: str):
        if Path(filename).name != filename:
            raise HTTPException(400, "Invalid filename")
        cfg = RuntimeConfig.load(config_path)
        path = cfg.artifacts.saved_root / filename
        if not path.exists() or not path.is_file():
            raise HTTPException(404, "Saved artifact not found")
        return FileResponse(path, filename=path.name, media_type="application/zip")

    return app


def launch_ui(config_path: Path | str = DEFAULT_CONFIG_PATH) -> None:
    cfg = RuntimeConfig.load(config_path)
    uvicorn.run(
        create_app(config_path),
        host=cfg.ui.host,
        port=cfg.ui.port,
        log_level="info",
    )


# Standard ASGI target: uvicorn src.interface.web.app:app
app = create_app()
