from __future__ import annotations

from collections import OrderedDict
from contextlib import ExitStack
import asyncio
import base64
import binascii
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as package_version
from difflib import SequenceMatcher
import json
import os
import re
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from src.context import TraceResolver
from src.eval import AblationRunner
from src.history import HistoryStore, VALID_FEEDBACK
from src.history.store import SCHEMA_VERSION as HISTORY_SCHEMA_VERSION
from src.inference import LMStudioClient, LMStudioError, LMStudioModelManager
from src.pipeline import ArlineAnalyticalPipeline
from src.runtime_config import DEFAULT_CONFIG_PATH, RuntimeConfig, VALID_INPUT_MODES, VALID_REASONING, VALID_PROJECTION_MODES
from src.service import ArlineService, ArtifactStore, make_run_id
from src.service.streaming import StreamingArlineService
from src.writer.quality import ProseQualityAnalyzer
from src.storage_backup import backup_sqlite_before_migrations
from src.storage_reset import reset_storage
from src.memory import MemoryConfig, MemoryQueryContext, MemoryService, MemoryStore
from src.discovery.store import DiscoveryStore
from src.version import __version__
from src.directives import COMMAND_REGISTRY_VERSION, DYNAMIC_REFERENCES, REFERENCE_SELECTORS, DirectiveEngine
from src.memory.web import create_memory_router
from src.workspace.store import WORKSPACE_SCHEMA_VERSION
from src.workspace import (
    BRANCH_KINDS,
    CANON_STATUSES,
    DOCUMENT_TYPES,
    ENTITY_TYPES,
    WORLD_BIBLE_PROJECT_ID,
    WORLD_BIBLE_WORLD_ID,
    WORLD_BIBLE_BRANCH_ID,
    WorkspaceContextResolver,
    WorkspaceStore,
    FoundationStore,
    parse_quick_create,
)


try:
    STUDIO_VERSION = package_version("arline-studio")
except PackageNotFoundError:
    STUDIO_VERSION = __version__

MODE_LABELS = {
    "smart_hybrid": "Smart Hybrid",
    "wcf": "WCF only",
    "raw": "Raw only",
    "wcf_raw": "WCF + Raw",
    "aif_core": "AIF-Core",
}

MEDIA_MIME_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MEDIA_RESOURCE_TYPES = {"entity_family", "entity_variant", "world", "document"}
MAX_MEDIA_BYTES = 20 * 1024 * 1024


class RuntimePayload(BaseModel):
    server_url: str = "http://127.0.0.1:1234"
    api_key: str | None = None
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
    mode: str = "context"
    selector: str | None = None


class PromptPayload(RuntimePayload):
    prompt: str
    timezone: str | None = None
    session_id: str | None = None
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    folder_id: str | None = None
    references: list[ReferencePayload] = Field(default_factory=list)
    context_recipe_id: str | None = None
    context_lens: str | None = None
    world_time: Any = None
    story_order: float | None = None
    pov_variant_id: str | None = None
    scratch_mode: bool = False


class ModelsPayload(BaseModel):
    server_url: str | None = None
    api_key: str | None = None


class SavePayload(BaseModel):
    run_id: str


class AblationPayload(PromptPayload):
    conditions: list[str] = Field(default_factory=list)


class ContractPayload(BaseModel):
    content: str


class StorageResetPayload(BaseModel):
    mode: str
    confirmation: str


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
    scratch_mode: bool | None = None
    world_fork_id: str | None = None


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
    project_id: str | None = None
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


class EntityFamilyMergePayload(BaseModel):
    source_family_id: str
    target_family_id: str


class EntityFamilyPayload(BaseModel):
    project_id: str | None = None
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
    document_type: str = "scene"
    content: str = ""
    world_id: str | None = None
    branch_id: str | None = None
    folder_id: str | None = None
    status: str = "planned"


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


class QuickCreatePayload(BaseModel):
    text: str
    forced_kind: str | None = None
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    entity_type: str | None = None
    name: str | None = None
    attributes: dict[str, Any] | None = None
    shared_core: dict[str, Any] | None = None
    description: str | None = None
    document_type: str | None = None
    folder_id: str | None = None


class LifecyclePayload(BaseModel):
    resource_type: str
    resource_id: str
    previous_state: dict[str, Any] = Field(default_factory=dict)


class AliasPayload(BaseModel):
    resource_type: str
    resource_id: str
    alias: str


class CollectionPayload(BaseModel):
    name: str
    description: str = ""
    icon: str = "◇"
    scope_type: str = "world_bible"
    scope_id: str | None = None


class CollectionLinkPayload(BaseModel):
    resource_type: str
    resource_id: str
    sort_order: int = 0


class SavedViewPayload(BaseModel):
    name: str
    scope_type: str = "world_bible"
    scope_id: str | None = None
    resource_type: str = "all"
    query: dict[str, Any] = Field(default_factory=dict)


class RunProfilePayload(BaseModel):
    name: str
    description: str = ""
    project_id: str | None = None
    profile: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None


class FavoritePayload(BaseModel):
    project_id: str | None = None
    resource_type: str
    resource_id: str
    label: str = ""


class IssuePayload(BaseModel):
    issue_type: str
    title: str
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    severity: str = "warning"
    description: str = ""
    resource_type: str | None = None
    resource_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ContextStackPayload(BaseModel):
    stack_id: str = "default"
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    scene_document_id: str | None = None
    session_id: str | None = None
    recipe_id: str | None = None
    run_profile_id: str | None = None
    references: list[dict[str, Any]] = Field(default_factory=list)
    overrides: dict[str, Any] = Field(default_factory=dict)

class ManuscriptImportPayload(BaseModel):
    project_id: str
    title: str = "Imported manuscript"
    text: str
    folder_id: str | None = None
    split_headings: bool = True
    default_type: str = "scene"




class MediaCreatePayload(BaseModel):
    resource_type: str
    resource_id: str
    filename: str = "image"
    data_url: str
    kind: str = "reference"
    caption: str = ""
    is_cover: bool = False
    sort_order: int = 0


class MediaPatchPayload(BaseModel):
    kind: str | None = None
    caption: str | None = None
    description: str | None = None
    description_source: str | None = None
    is_cover: bool | None = None
    sort_order: int | None = None


class MediaDescribePayload(BaseModel):
    model: str = ""
    server_url: str | None = None
    api_key: str | None = None
    prompt: str = ""


class PreferencePayload(BaseModel):
    scope_type: str = "app"
    scope_id: str = "default"
    key: str
    value: Any


class ProjectWorldLinkPayload(BaseModel):
    project_id: str
    world_id: str
    role: str = "reference"


class ManifestRefPayload(BaseModel):
    resource_type: str
    resource_id: str
    label: str = ""
    priority: int = 1


class ProjectOverlayPayload(BaseModel):
    owner_type: str
    owner_id: str
    path: str
    value: Any
    world_id: str | None = None
    branch_id: str | None = None


class ActiveScenePayload(BaseModel):
    document_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    pov_variant_id: str | None = None
    location_variant_id: str | None = None
    participants: list[str] = Field(default_factory=list)
    narrative_time: str = ""
    notes: str = ""


class SceneCardPayload(BaseModel):
    world_id: str | None = None
    branch_id: str | None = None
    pov_variant_id: str | None = None
    location_variant_id: str | None = None
    participants: list[str] = Field(default_factory=list)
    narrative_time: str = ""
    target_outcome: str = ""
    notes: str = ""
    status: str = "planned"
    sort_order: float = 0.0


class StagedChangePayload(BaseModel):
    owner_type: str
    owner_id: str
    path: str
    proposed_value: Any
    old_value: Any = None
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    world_id: str | None = None
    branch_id: str | None = None
    session_id: str | None = None
    turn_id: str | None = None
    source_text: str = ""


class StagedResolvePayload(BaseModel):
    accept: bool


class TimelineEventPayload(BaseModel):
    world_id: str
    summary: str
    branch_id: str | None = None
    owner_type: str | None = None
    owner_id: str | None = None
    time_label: str = ""
    order_key: float = 0.0
    event_type: str = "event"
    state_patch: dict[str, Any] = Field(default_factory=dict)
    source_type: str = "manual"
    source_id: str | None = None
    status: str = "canon"


class ContextRecipePayload(BaseModel):
    name: str
    description: str = ""
    recipe: dict[str, Any] = Field(default_factory=dict)


class BranchMergePayload(BaseModel):
    target_branch_id: str
    changes: list[dict[str, Any]] = Field(default_factory=list)
    note: str = "selective branch merge"


class StateProposalPayload(BaseModel):
    text: str
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    session_id: str | None = None
    turn_id: str | None = None


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

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


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

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


def _apply_payload(cfg: RuntimeConfig, payload: RuntimePayload) -> RuntimeConfig:
    if payload.input_mode not in VALID_INPUT_MODES:
        raise ValueError(f"Unsupported input mode: {payload.input_mode}")
    if payload.reasoning not in VALID_REASONING:
        raise ValueError(f"Unsupported reasoning mode: {payload.reasoning}")
    if payload.projection_mode not in VALID_PROJECTION_MODES:
        raise ValueError(f"Unsupported projection mode: {payload.projection_mode}")

    cfg.lmstudio.base_url = RuntimeConfig.normalize_server_url(payload.server_url)
    if payload.api_key is not None:
        cfg.lmstudio.api_key = payload.api_key
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
        "studio_version": STUDIO_VERSION,
        "server_url": cfg.lmstudio.base_url,
        "api_key_configured": bool(cfg.lmstudio.api_key),
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
        "memory": MemoryConfig.load(cfg.path).to_dict(),
        "reasoning_guard": {
            "enforce_model_capabilities": cfg.reasoning_runtime.enforce_model_capabilities,
            "dominance_ratio_warn": cfg.reasoning_runtime.dominance_ratio_warn,
            "reasoning_share_warn": cfg.reasoning_runtime.reasoning_share_warn,
            "story_target_ratio_warn": cfg.reasoning_runtime.story_target_ratio_warn,
        },
    }


def _folder_tree_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for raw in rows:
        row = dict(raw)
        by_parent.setdefault(row.get("parent_id"), []).append(row)
    for values in by_parent.values():
        values.sort(key=lambda item: (item.get("sort_order", 0), str(item.get("name", "")).casefold()))
    def build(parent_id: str | None) -> list[dict[str, Any]]:
        return [{**item, "children": build(item.get("id"))} for item in by_parent.get(parent_id, [])]
    return build(None)


def create_app(config_path: Path | str = DEFAULT_CONFIG_PATH) -> FastAPI:
    config_path = Path(config_path)
    base_dir = Path(__file__).resolve().parent
    static_dir = base_dir / "static"
    saved_cache = RunCache(max_items=20)
    analysis_cache = AnalysisCache(max_items=20)
    storage_reset_lock = RLock()
    initial_cfg = RuntimeConfig.load(config_path)
    migration_targets: dict[Path, dict[str, int]] = {}
    history_path = Path(initial_cfg.history.database_path).resolve()
    workspace_path = Path(initial_cfg.workspace.database_path).resolve()
    migration_targets.setdefault(history_path, {})["meta"] = HISTORY_SCHEMA_VERSION
    migration_targets.setdefault(workspace_path, {})["workspace_meta"] = max(WORKSPACE_SCHEMA_VERSION, FoundationStore.SCHEMA_VERSION)
    migration_targets.setdefault(workspace_path, {})["memory_meta"] = MemoryStore.SCHEMA_VERSION
    migration_targets.setdefault(workspace_path, {})["discovery_meta"] = DiscoveryStore.SCHEMA_VERSION
    migration_backups = []
    for database_path, targets in migration_targets.items():
        backup = backup_sqlite_before_migrations(database_path, targets)
        if backup is not None:
            migration_backups.append(backup)

    history = HistoryStore(initial_cfg.history.database_path, backup_before_migration=False)
    workspace = WorkspaceStore(initial_cfg.workspace.database_path, backup_before_migration=False)
    foundation = FoundationStore(initial_cfg.workspace.database_path)
    memory_config = MemoryConfig.load(config_path)
    memory_store = MemoryStore(initial_cfg.workspace.database_path, backup_before_migration=False)
    memory_service = MemoryService(
        store=memory_store,
        workspace=workspace,
        history=history,
        foundation=foundation,
        config=memory_config,
        lmstudio_base_url=initial_cfg.lmstudio.base_url,
        lmstudio_api_key=initial_cfg.lmstudio.api_key,
    )
    memory_service._combined_migration_backup_complete = True
    media_root = workspace_path.parent / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    for backup in migration_backups:
        foundation.log_activity(
            None, "schema_backup", "database", None,
            label="Backup before database migration",
            detail={"path": str(backup), "workspace_schema_version": WORKSPACE_SCHEMA_VERSION, "history_schema_version": HISTORY_SCHEMA_VERSION},
        )
    workspace_context = WorkspaceContextResolver(
        workspace, max_items=initial_cfg.workspace.pinned_context_limit
    )

    def effective_folders(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Hide archived/trashed folders *and* descendants of hidden folders.

        Lifecycle belongs to the folder, not every child object. Treating the
        whole subtree as hidden keeps Trash reversible without rewriting every
        document/entity row or producing orphaned children in search/results.
        """
        by_id = {row["id"]: row for row in rows}
        memo: dict[str, bool] = {}

        def visible(folder_id: str) -> bool:
            if folder_id in memo:
                return memo[folder_id]
            row = by_id.get(folder_id)
            if row is None or foundation.is_hidden("folder", folder_id):
                memo[folder_id] = False
                return False
            parent_id = row.get("parent_id")
            result = True if not parent_id else visible(parent_id)
            memo[folder_id] = result
            return result

        return [row for row in rows if visible(row["id"])]

    def resource_folder_visible(resource: dict[str, Any], visible_folder_ids: set[str]) -> bool:
        folder_id = resource.get("folder_id")
        return not folder_id or folder_id in visible_folder_ids

    def visible_folder_ids(project_id: str | None) -> set[str]:
        if not project_id:
            return set()
        return {row["id"] for row in effective_folders(workspace.list_folders(project_id))}


    def _augment_memory_context(
        prompt: str,
        payload: PromptPayload,
        ws_context,
        *,
        project_id: str | None,
        world_id: str | None,
        branch_id: str | None,
        session_id: str | None,
        refs: list[dict[str, Any]],
    ):
        if ws_context is None or not memory_config.enabled or not memory_config.automatic_context:
            return ws_context
        active_scene = (ws_context.scope.get("active_scene") or {}) if ws_context else {}
        directive = DirectiveEngine.parse(
            prompt, explicit_references=refs, active_scene=active_scene,
            project_id=project_id, world_id=world_id, branch_id=branch_id,
        )
        ws_context.scope["directive"] = directive.to_dict()
        memory_refs = directive.resolved_references or refs
        memory_query = directive.semantic_prompt or prompt
        lens = str(payload.context_lens or memory_config.default_lens or "scene").lower()
        directive_pov = str(directive.options.get("pov_variant_id") or "").strip() or None
        if (directive.command or {}).get("id") == "pov" and directive_pov:
            lens = "pov"
        if lens not in {"author", "scene", "pov"}:
            lens = memory_config.default_lens if memory_config.default_lens in {"author", "scene", "pov"} else "scene"
        output_reserve = int(payload.visible_output_tokens) + (int(payload.reasoning_reserve_tokens) if payload.reasoning != "off" else 0)
        fixed_reserve = (
            initial_cfg.context_budget.safety_margin
            + initial_cfg.context_budget.system_prompt_token_estimate
            + initial_cfg.context_budget.minimum_writer_context_tokens
            + int(ws_context.estimated_tokens or 0)
        )
        remaining = max(0, int(payload.context_length) - output_reserve - fixed_reserve)
        memory_budget = min(memory_config.max_pack_tokens, remaining)
        memory_scope = MemoryQueryContext(
            project_id=project_id,
            world_id=world_id,
            branch_id=branch_id,
            session_id=session_id,
            world_time=payload.world_time if payload.world_time is not None else (active_scene.get("narrative_time") or None),
            story_order=payload.story_order,
            pov_variant_id=directive_pov or payload.pov_variant_id or active_scene.get("pov_variant_id"),
            context_lens=lens,
            retrieval_mode="generation",
            explicit_references=memory_refs,
            allow_scratch=bool(payload.scratch_mode),
            allow_future_author_knowledge=(lens == "author"),
            token_budget=memory_budget,
        )
        try:
            result = memory_service.retrieve(memory_query, memory_scope, workspace_context=ws_context)
            return memory_service.augment_workspace_context(ws_context, result)
        except Exception as exc:
            ws_context.scope["memory"] = {
                "fallback": True,
                "error": str(exc),
                "reason": "Memory retrieval failed; v1.1 workspace context remained active.",
            }
            return ws_context

    app = FastAPI(title="Arline Studio", version=STUDIO_VERSION)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(create_memory_router(
        service=memory_service,
        store=memory_store,
        foundation=foundation,
    ))

    @app.get("/")
    def index():
        return FileResponse(static_dir / "index.html")

    @app.get("/api/config")
    def get_config():
        return _public_config(RuntimeConfig.load(config_path))

    @app.post("/api/directives/parse")
    def parse_directive(payload: PromptPayload):
        refs = [item.model_dump() for item in payload.references]
        active_scene = workspace.get_active_scene(payload.project_id) if payload.project_id else {}
        return DirectiveEngine.parse(
            payload.prompt, explicit_references=refs, active_scene=active_scene or {},
            project_id=payload.project_id, world_id=payload.world_id, branch_id=payload.branch_id,
        ).to_dict()

    @app.get("/api/backups")
    def list_backups():
        cfg = RuntimeConfig.load(config_path)
        database_path = Path(cfg.workspace.database_path)
        backup_dir = database_path.parent / "backups"
        rows = []
        if backup_dir.exists():
            for path in sorted(backup_dir.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True):
                if not path.is_file():
                    continue
                stat = path.stat()
                rows.append({"name": path.name, "bytes": stat.st_size, "modified_at": __import__("datetime").datetime.fromtimestamp(stat.st_mtime, __import__("datetime").timezone.utc).isoformat()})
        return {
            "database_name": database_path.name,
            "database_bytes": database_path.stat().st_size if database_path.exists() else 0,
            "backups": rows,
        }

    @app.post("/api/storage/reset")
    def reset_local_storage(payload: StorageResetPayload):
        expected = {
            "database": "RESET DATABASE",
            "complete": "DELETE EVERYTHING",
        }
        if payload.mode not in expected:
            raise HTTPException(400, "Reset mode must be 'database' or 'complete'")
        if payload.confirmation.strip() != expected[payload.mode]:
            raise HTTPException(400, f"Type {expected[payload.mode]} exactly to confirm")

        with memory_service._refresh_lock:
            for timer in memory_service._refresh_timers.values():
                timer.cancel()
            memory_service._refresh_timers.clear()

        discovery = getattr(memory_service, "discovery", None)
        materialization_lock = getattr(discovery, "_provisional_materialization_lock", None)
        stores = [history, workspace, foundation, memory_store]
        if discovery is not None:
            stores.append(discovery.store)

        try:
            with storage_reset_lock, ExitStack() as stack:
                if materialization_lock is not None:
                    stack.enter_context(materialization_lock)
                locks = {id(store._lock): store._lock for store in stores if hasattr(store, "_lock")}
                for lock in sorted(locks.values(), key=id):
                    stack.enter_context(lock)
                report = reset_storage(
                    RuntimeConfig.load(config_path),
                    complete=payload.mode == "complete",
                )
                saved_cache.clear()
                analysis_cache.clear()
        except (OSError, ValueError) as exc:
            raise HTTPException(409, f"Storage reset failed: {exc}") from exc
        return report.to_dict()

    @app.get("/api/models")
    def get_models(server_url: str = Query("http://127.0.0.1:1234")):
        # URL credentials are forbidden; transient keys use POST /api/models/query.
        cfg=RuntimeConfig.load(config_path);cfg.lmstudio.base_url=RuntimeConfig.normalize_server_url(server_url)
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
                    "capabilities": {
                        "provider": "lmstudio",
                        "context_window": item.get("max_context_length"),
                        "streaming": True,
                        "separate_reasoning_stream": bool(((item.get("capabilities") or {}).get("reasoning") or item.get("reasoning") or {}).get("allowed_options")),
                        "reasoning_modes": list((((item.get("capabilities") or {}).get("reasoning") or item.get("reasoning") or {}).get("allowed_options") or [])),
                        "vision": bool((item.get("capabilities") or {}).get("vision")),
                        "sampling_controls": ["temperature", "top_p", "top_k", "min_p", "repeat_penalty"],
                    },
                }
                for item in models
            ]
        }

    @app.post("/api/models/query")
    def query_models(payload: ModelsPayload):
        cfg = RuntimeConfig.load(config_path)
        if payload.server_url:
            cfg.lmstudio.base_url = RuntimeConfig.normalize_server_url(payload.server_url)
        if payload.api_key is not None:
            cfg.lmstudio.api_key = payload.api_key
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
                    "capabilities": {
                        "provider": "lmstudio",
                        "context_window": item.get("max_context_length"),
                        "streaming": True,
                        "separate_reasoning_stream": bool(((item.get("capabilities") or {}).get("reasoning") or item.get("reasoning") or {}).get("allowed_options")),
                        "reasoning_modes": list((((item.get("capabilities") or {}).get("reasoning") or item.get("reasoning") or {}).get("allowed_options") or [])),
                        "vision": bool((item.get("capabilities") or {}).get("vision")),
                        "sampling_controls": ["temperature", "top_p", "top_k", "min_p", "repeat_penalty"],
                    },
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
    # Portable import/export foundation
    # ------------------------------------------------------------------

    def _split_manuscript_text(text: str, title: str) -> list[dict[str, str]]:
        text = text.replace("\r\n", "\n").strip()
        if not text:
            return []
        heading = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)
        matches = list(heading.finditer(text))
        if not matches:
            return [{"title": title.strip() or "Imported manuscript", "content": text, "document_type": "scene"}]
        sections: list[dict[str, str]] = []
        prefix = text[: matches[0].start()].strip()
        if prefix:
            sections.append({"title": title.strip() or "Imported notes", "content": prefix, "document_type": "note"})
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            level = len(match.group(1))
            sections.append({
                "title": match.group(2).strip(),
                "content": text[start:end].strip(),
                "document_type": "chapter" if level == 1 else "scene",
            })
        return sections

    @app.post("/api/import/manuscript/preview")
    def preview_manuscript_import(payload: ManuscriptImportPayload):
        sections = _split_manuscript_text(payload.text, payload.title) if payload.split_headings else [{"title": payload.title, "content": payload.text.strip(), "document_type": payload.default_type}]
        return {
            "destination": "project_manuscript",
            "sections": [{"title": x["title"], "document_type": x["document_type"], "chars": len(x["content"]), "words": len(x["content"].split())} for x in sections],
            "count": len(sections),
        }

    @app.post("/api/import/manuscript")
    def import_manuscript(payload: ManuscriptImportPayload):
        try:
            workspace.get_project(payload.project_id)
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc
        sections = _split_manuscript_text(payload.text, payload.title) if payload.split_headings else [{"title": payload.title, "content": payload.text.strip(), "document_type": payload.default_type}]
        if not sections:
            raise HTTPException(400, "Import text is empty")
        job = foundation.create_job("manuscript_import", project_id=payload.project_id, payload={"count": len(sections)}, message="Importing manuscript")
        created = []
        try:
            for index, section in enumerate(sections):
                doc_type = section.get("document_type") or payload.default_type
                if doc_type not in DOCUMENT_TYPES:
                    doc_type = "scene"
                created.append(workspace.create_document(
                    payload.project_id, section["title"], document_type=doc_type,
                    content=section["content"], folder_id=payload.folder_id, status="writing",
                ))
                foundation.update_job(job["id"], status="running", progress=(index + 1) / max(1, len(sections)), message=f"Imported {index + 1}/{len(sections)}")
            foundation.update_job(job["id"], status="done", progress=1, message="Import complete", result={"document_ids": [x["id"] for x in created]})
            for document in created:
                memory_service.schedule_document_refresh(document["id"])
            foundation.log_activity(payload.project_id, "manuscript_import", "project", payload.project_id, label=f"Imported {len(created)} manuscript items")
            return {"job": foundation.get_job(job["id"]), "documents": created}
        except Exception as exc:
            foundation.update_job(job["id"], status="failed", message=str(exc))
            raise

    @app.get("/api/export/project/{project_id}")
    def export_project_bundle(project_id: str):
        try:
            project = workspace.get_project(project_id)
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc
        return {
            "format": "arline-project-bundle",
            "version": 1,
            "schema_version": FoundationStore.SCHEMA_VERSION,
            "boundary": "Project files and project-local context only; Library sheets remain references.",
            "project": project,
            "folders": workspace.list_folders(project_id),
            "documents": workspace.list_documents(project_id),
            "tags": workspace.list_tags(project_id),
            "manifest_refs": workspace.list_project_manifest_refs(project_id),
            "overlays": workspace.list_project_overlays(project_id),
            "active_scene": workspace.get_active_scene(project_id),
            "scene_cards": workspace.list_scene_cards(project_id),
            "run_profiles": foundation.list_run_profiles(project_id),
        }

    @app.get("/api/export/world-bible")
    def export_world_bible_bundle(world_id: str | None = Query(None), branch_id: str | None = Query(None)):
        families = foundation.filter_visible("entity_family", workspace.list_entity_families(None))
        return {
            "format": "arline-world-bible-bundle",
            "version": 1,
            "schema_version": FoundationStore.SCHEMA_VERSION,
            "worlds": foundation.filter_visible("world", [workspace.get_world(world_id)] if world_id else workspace.list_worlds()),
            "families": families,
            "variants": foundation.filter_visible("entity_variant", workspace.list_variants(world_id=world_id, branch_id=branch_id)),
            "relationships": foundation.filter_visible("relationship", workspace.list_relationships(world_id=world_id, branch_id=branch_id)) if world_id else [],
            "facts": foundation.filter_visible("fact", workspace.list_facts(world_id=world_id, branch_id=branch_id)) if world_id else [],
            "timeline": foundation.filter_visible("timeline", workspace.list_timeline_events(world_id, branch_id=branch_id)) if world_id else [],
            "folders": foundation.filter_visible("folder", workspace.list_folders(WORLD_BIBLE_PROJECT_ID)),
            "collections": foundation.list_collections(scope_type="world_bible"),
            "saved_views": foundation.list_saved_views(scope_type="world_bible"),
        }

    # ------------------------------------------------------------------
    # Project / world / library workspace API
    # ------------------------------------------------------------------

    @app.get("/api/workspace/bootstrap")
    def workspace_bootstrap(create_default: bool = Query(True), stack_id: str = Query("default")):
        projects = foundation.filter_visible("project", workspace.list_projects())
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
            projects = foundation.filter_visible("project", workspace.list_projects())
        active_project = None
        active_world = None
        active_branch = None
        if projects:
            preferred = initial_cfg.workspace.default_project_id
            active_project = next((x for x in projects if x["id"] == preferred), projects[0])
            details = workspace.get_project(active_project["id"])
            worlds = foundation.filter_visible("world", details.get("worlds", []))
            if worlds:
                active_world = next(
                    (x for x in worlds if x["id"] == active_project.get("default_world_id")),
                    worlds[0],
                )
                branches = foundation.filter_visible("branch", workspace.list_branches(active_world["id"]))
                active_branch = next((x for x in branches if x["kind"] == "main"), branches[0] if branches else None)
        stack = foundation.get_context_stack(stack_id)
        return {
            "projects": projects,
            "worlds": foundation.filter_visible("world", workspace.list_worlds()),
            "active": {
                "project": active_project,
                "world": active_world,
                "branch": active_branch,
            },
            "context_stack": stack,
            "run_profiles": foundation.list_run_profiles(active_project["id"] if active_project else None),
            "favorites": foundation.list_favorites(active_project["id"] if active_project else None),
            "canon_statuses": sorted(CANON_STATUSES),
            "entity_types": sorted(ENTITY_TYPES),
            # `draft` remains accepted by the backend for v1.0 clients, but it
            # is no longer a user-facing Manuscript object type in v1.1.
            "document_types": sorted(item for item in DOCUMENT_TYPES if item != "draft"),
            "branch_kinds": sorted(BRANCH_KINDS),
            "world_bible": {
                "backing_project_id": WORLD_BIBLE_PROJECT_ID,
                "default_world_id": WORLD_BIBLE_WORLD_ID,
                "default_branch_id": WORLD_BIBLE_BRANCH_ID,
            },
        }

    @app.get("/api/projects")
    def list_projects(search: str = Query(""), include_archived: bool = Query(False)):
        projects = workspace.list_projects(search=search, include_archived=include_archived)
        return {"projects": foundation.filter_visible("project", projects, include_archived=include_archived)}

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
            result["worlds"] = foundation.filter_visible("world", result.get("worlds", []))
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
            _permanent_delete("project", project_id)
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc
        return {"ok": True}

    @app.get("/api/projects/{project_id}/tree")
    def project_tree(project_id: str, world_id: str | None = Query(None), branch_id: str | None = Query(None)):
        try:
            raw_folders = workspace.list_folders(project_id)
            folders = effective_folders(raw_folders)
            visible_folder_ids = {folder["id"] for folder in folders}
            documents = [
                doc for doc in foundation.filter_visible("document", workspace.list_documents(project_id))
                if resource_folder_visible(doc, visible_folder_ids)
            ]
            return {
                "project": workspace.get_project(project_id),
                "worlds": workspace.list_worlds(project_id),
                # Project filesystem is independent from the selected World
                # Bible scope. Documents may *reference* a world/branch as
                # metadata, but switching canon must not hide project files.
                "folders": folders,
                "folder_tree": _folder_tree_from_rows(folders),
                "documents": documents,
                "tags": workspace.list_tags(project_id),
                "templates": workspace.list_templates(project_id=project_id),
                "manifest_refs": workspace.list_project_manifest_refs(project_id),
                "active_scene": workspace.get_active_scene(project_id),
                "scene_cards": workspace.list_scene_cards(project_id),
                "overlays": workspace.list_project_overlays(project_id, world_id=world_id, branch_id=branch_id),
                "conflicts": workspace.list_conflicts(
                    project_id=project_id, world_id=world_id, branch_id=branch_id, status="open"
                ),
                "issues": foundation.list_issues(project_id=project_id, world_id=world_id, branch_id=branch_id),
                "activity": foundation.list_activity(project_id, limit=30),
                "favorites": foundation.list_favorites(project_id),
                "run_profiles": foundation.list_run_profiles(project_id),
            }
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc

    @app.get("/api/world-bible")
    def world_bible(
        world_id: str | None = Query(None), branch_id: str | None = Query(None),
        search: str = Query(""), project_id: str | None = Query(None),
    ):
        raw_bible_folders = workspace.list_folders(WORLD_BIBLE_PROJECT_ID)
        bible_folders = effective_folders(raw_bible_folders)
        visible_bible_folder_ids = {folder["id"] for folder in bible_folders}
        families = [
            family for family in foundation.filter_visible("entity_family", workspace.list_entity_families(None, search=search))
            if resource_folder_visible(family, visible_bible_folder_ids)
        ]
        visible_family_ids = {family["id"] for family in families}
        variants = [
            variant for variant in foundation.filter_visible("entity_variant", workspace.list_variants(world_id=world_id, branch_id=branch_id))
            if variant.get("family_id") in visible_family_ids
        ]
        relationships = foundation.filter_visible("relationship", workspace.list_relationships(world_id=world_id, branch_id=branch_id)) if world_id else []
        return {
            "worlds": foundation.filter_visible("world", workspace.list_worlds()),
            "families": families,
            "variants": variants,
            "relationships": relationships,
            "timeline": foundation.filter_visible("timeline", workspace.list_timeline_events(world_id, branch_id=branch_id)) if world_id else [],
            "recipes": workspace.list_context_recipes(project_id),
            "folders": bible_folders,
            "folder_tree": _folder_tree_from_rows(bible_folders),
            "collections": foundation.list_collections(scope_type="world_bible"),
            "saved_views": foundation.list_saved_views(scope_type="world_bible"),
        }

    # ------------------------------------------------------------------
    # v1.1 application foundation: lifecycle, identity, views, context stack
    # ------------------------------------------------------------------

    def _resource_payload(resource_type: str, resource_id: str) -> dict[str, Any]:
        getters = {
            "project": workspace.get_project,
            "world": workspace.get_world,
            "branch": workspace.get_branch,
            "folder": workspace.get_folder,
            "document": workspace.get_document,
            "entity_family": workspace.get_entity_family,
            "entity_variant": workspace.get_variant,
            "relationship": workspace.get_relationship,
            "fact": workspace.get_fact,
            "tag": workspace.get_tag,
            "snapshot": workspace.get_snapshot,
            "timeline": workspace.get_timeline_event,
        }
        if resource_type == "session":
            return history.get_session_meta(resource_id)
        getter = getters.get(resource_type)
        if not getter:
            raise KeyError(resource_id)
        return getter(resource_id)

    def _permanent_delete(resource_type: str, resource_id: str) -> None:
        if resource_type == "session":
            history.delete_session(resource_id)
            foundation.forget_resource(resource_type, resource_id)
            return
        if resource_type == "project":
            history.delete_sessions_by_scope(project_id=resource_id)
            workspace.delete_project(resource_id)
        elif resource_type == "world":
            history.delete_sessions_by_scope(world_id=resource_id)
            workspace.delete_world(resource_id)
        elif resource_type == "branch":
            history.delete_sessions_by_scope(branch_id=resource_id)
            workspace.delete_branch(resource_id)
        else:
            deleters = {
                "folder": workspace.delete_folder,
                "document": workspace.delete_document,
                "entity_family": workspace.delete_entity_family,
                "entity_variant": workspace.delete_variant,
                "relationship": workspace.delete_relationship,
                "fact": workspace.delete_fact,
                "tag": workspace.delete_tag,
                "snapshot": workspace.delete_snapshot,
            }
            delete = deleters.get(resource_type)
            if not delete:
                raise ValueError(f"Permanent delete is not supported for {resource_type}")
            delete(resource_id)
        foundation.forget_resource(resource_type, resource_id)

    @app.post("/api/lifecycle/trash")
    def trash_resource(payload: LifecyclePayload):
        try:
            resource = _resource_payload(payload.resource_type, payload.resource_id)
            project_id = resource.get("project_id") if isinstance(resource, dict) else None
            result = foundation.trash(payload.resource_type, payload.resource_id, previous_state=payload.previous_state or resource)
            foundation.log_activity(project_id, "trash", payload.resource_type, payload.resource_id, label=resource.get("name") or resource.get("title") or resource.get("display_name") or "")
            return result
        except KeyError as exc:
            raise HTTPException(404, "Resource not found") from exc

    @app.post("/api/lifecycle/archive")
    def archive_resource(payload: LifecyclePayload, archived: bool = Query(True)):
        try:
            _resource_payload(payload.resource_type, payload.resource_id)
            return foundation.archive(payload.resource_type, payload.resource_id, archived=archived)
        except KeyError as exc:
            raise HTTPException(404, "Resource not found") from exc

    @app.post("/api/lifecycle/restore")
    def restore_resource(payload: LifecyclePayload):
        try:
            _resource_payload(payload.resource_type, payload.resource_id)
            return foundation.restore(payload.resource_type, payload.resource_id)
        except KeyError as exc:
            raise HTTPException(404, "Resource not found") from exc

    @app.get("/api/trash")
    def list_trash():
        items = []
        for item in foundation.list_trash():
            try:
                resource = _resource_payload(item["resource_type"], item["resource_id"])
            except KeyError:
                continue
            items.append({**item, "resource": resource})
        return {"items": items}

    @app.delete("/api/trash/{resource_type}/{resource_id}")
    def permanent_delete(resource_type: str, resource_id: str):
        try:
            lifecycle = foundation.lifecycle(resource_type, resource_id)
            if not lifecycle.get("trashed_at"):
                raise HTTPException(409, "Move the resource to Trash before deleting permanently")
            _permanent_delete(resource_type, resource_id)
            return {"ok": True}
        except KeyError as exc:
            raise HTTPException(404, "Resource not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/resources/{resource_type}/{resource_id}")
    def inspect_resource(resource_type: str, resource_id: str):
        try:
            resource = _resource_payload(resource_type, resource_id)
        except KeyError as exc:
            raise HTTPException(404, "Resource not found") from exc
        tags = []
        backlinks = {}
        try:
            tags = workspace.tags_for(resource_type, resource_id)
        except Exception:
            pass
        try:
            backlinks = workspace.backlinks(resource_type, resource_id)
        except Exception:
            pass
        collections = [
            {"id": coll["id"], "name": coll["name"]}
            for coll in foundation.list_collections(scope_type="world_bible")
            if any(link["resource_type"] == resource_type and link["resource_id"] == resource_id for link in coll.get("links", []))
        ]
        return {
            "resource": resource,
            "resource_type": resource_type,
            "aliases": foundation.list_aliases(resource_type, resource_id),
            "tags": tags,
            "collections": collections,
            "backlinks": backlinks,
            "lifecycle": foundation.lifecycle(resource_type, resource_id),
        }

    @app.post("/api/aliases")
    def add_alias(payload: AliasPayload):
        try:
            _resource_payload(payload.resource_type, payload.resource_id)
            return foundation.add_alias(payload.resource_type, payload.resource_id, payload.alias)
        except KeyError as exc:
            raise HTTPException(404, "Resource not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/aliases")
    def list_aliases(resource_type: str = Query(...), resource_id: str = Query(...)):
        return {"aliases": foundation.list_aliases(resource_type, resource_id)}

    @app.delete("/api/aliases/{alias_id}")
    def delete_alias(alias_id: str):
        try:
            foundation.delete_alias(alias_id)
            return {"ok": True}
        except KeyError as exc:
            raise HTTPException(404, "Alias not found") from exc

    @app.get("/api/collections")
    def list_collections(scope_type: str = Query("world_bible"), scope_id: str | None = Query(None)):
        return {"collections": foundation.list_collections(scope_type=scope_type, scope_id=scope_id)}

    @app.post("/api/collections")
    def create_collection(payload: CollectionPayload):
        return foundation.create_collection(payload.name, scope_type=payload.scope_type, scope_id=payload.scope_id, description=payload.description, icon=payload.icon)

    @app.post("/api/collections/{collection_id}/links")
    def collection_add(collection_id: str, payload: CollectionLinkPayload):
        try:
            foundation.get_collection(collection_id)
            _resource_payload(payload.resource_type, payload.resource_id)
            foundation.add_to_collection(collection_id, payload.resource_type, payload.resource_id, payload.sort_order)
            return foundation.get_collection(collection_id)
        except KeyError as exc:
            raise HTTPException(404, "Collection or resource not found") from exc

    @app.delete("/api/collections/{collection_id}/links/{resource_type}/{resource_id}")
    def collection_remove(collection_id: str, resource_type: str, resource_id: str):
        foundation.remove_from_collection(collection_id, resource_type, resource_id)
        return {"ok": True}

    @app.delete("/api/collections/{collection_id}")
    def collection_delete(collection_id: str):
        try:
            foundation.delete_collection(collection_id)
            return {"ok": True}
        except KeyError as exc:
            raise HTTPException(404, "Collection not found") from exc

    @app.get("/api/saved-views")
    def saved_views(scope_type: str = Query("world_bible"), scope_id: str | None = Query(None)):
        return {"views": foundation.list_saved_views(scope_type=scope_type, scope_id=scope_id)}

    @app.post("/api/saved-views")
    def save_view(payload: SavedViewPayload):
        return foundation.save_view(payload.name, scope_type=payload.scope_type, scope_id=payload.scope_id, resource_type=payload.resource_type, query=payload.query)

    @app.delete("/api/saved-views/{view_id}")
    def delete_view(view_id: str):
        try:
            foundation.delete_view(view_id)
            return {"ok": True}
        except KeyError as exc:
            raise HTTPException(404, "View not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/run-profiles")
    def run_profiles(project_id: str | None = Query(None)):
        return {"profiles": foundation.list_run_profiles(project_id)}

    @app.post("/api/run-profiles")
    def save_run_profile(payload: RunProfilePayload):
        try:
            return foundation.save_run_profile(payload.name, payload.profile, project_id=payload.project_id, description=payload.description, profile_id=payload.id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/run-profiles/{profile_id}")
    def delete_run_profile(profile_id: str):
        try:
            foundation.delete_run_profile(profile_id)
            return {"ok": True}
        except KeyError as exc:
            raise HTTPException(404, "Profile not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/context-stack")
    def get_context_stack(stack_id: str = Query("default")):
        return foundation.get_context_stack(stack_id)

    @app.put("/api/context-stack")
    def set_context_stack(payload: ContextStackPayload):
        return foundation.set_context_stack(**payload.model_dump())

    @app.get("/api/favorites")
    def favorites(project_id: str | None = Query(None)):
        return {"favorites": foundation.list_favorites(project_id)}

    @app.post("/api/favorites")
    def favorite(payload: FavoritePayload):
        return foundation.favorite(payload.project_id, payload.resource_type, payload.resource_id, payload.label)

    @app.delete("/api/favorites")
    def unfavorite(project_id: str | None = Query(None), resource_type: str = Query(...), resource_id: str = Query(...)):
        foundation.unfavorite(project_id, resource_type, resource_id)
        return {"ok": True}

    @app.get("/api/activity")
    def activity(project_id: str | None = Query(None), limit: int = Query(50)):
        return {"activity": foundation.list_activity(project_id, limit=max(1, min(limit, 200)))}

    @app.get("/api/issues")
    def issues(project_id: str | None = Query(None), world_id: str | None = Query(None), branch_id: str | None = Query(None), status: str | None = Query("open")):
        return {"issues": foundation.list_issues(project_id=project_id, world_id=world_id, branch_id=branch_id, status=status)}

    @app.post("/api/issues")
    def create_issue(payload: IssuePayload):
        return foundation.create_issue(**payload.model_dump())

    @app.post("/api/issues/{issue_id}/resolve")
    def resolve_issue(issue_id: str, status: str = Query("resolved")):
        try:
            return foundation.resolve_issue(issue_id, status=status)
        except KeyError as exc:
            raise HTTPException(404, "Issue not found") from exc

    @app.get("/api/jobs")
    def jobs(project_id: str | None = Query(None)):
        return {"jobs": foundation.list_jobs(project_id)}

    @app.get("/api/preferences")
    def preferences(scope_type: str = Query("app"), scope_id: str = Query("default")):
        return foundation.get_preferences(scope_type, scope_id)

    @app.put("/api/preferences")
    def set_preference(payload: PreferencePayload):
        foundation.set_preference(payload.scope_type, payload.scope_id, payload.key, payload.value)
        return {"ok": True}

    @app.get("/api/search")
    def global_search(q: str = Query(""), project_id: str | None = Query(None), world_id: str | None = Query(None), branch_id: str | None = Query(None), limit: int = Query(60)):
        query = q.strip()
        if not query:
            return {"results": []}
        results = workspace.command_search(query, project_id=project_id)
        project_folder_ids = visible_folder_ids(project_id)
        bible_folder_ids = visible_folder_ids(WORLD_BIBLE_PROJECT_ID)
        alias_hits = foundation.alias_matches(query, limit=limit)
        known = {(item.get("type"), item.get("id")) for item in results}
        for alias in alias_hits:
            key = (alias["resource_type"], alias["resource_id"])
            if key in known or foundation.is_hidden(*key):
                continue
            try:
                resource = _resource_payload(*key)
            except KeyError:
                continue
            folder_scope = bible_folder_ids if alias["resource_type"] in {"entity_family", "entity_variant"} else project_folder_ids
            if resource.get("folder_id") and not resource_folder_visible(resource, folder_scope):
                continue
            label = resource.get("name") or resource.get("display_name") or resource.get("title") or alias["alias"]
            results.insert(0, {"type": alias["resource_type"], "id": alias["resource_id"], "label": label, "description": f"Alias: {alias['alias']}"})
            known.add(key)
        sessions = history.list_sessions(search=query, limit=min(limit, 25), project_id=project_id)
        for session in sessions:
            results.append({"type": "session", "id": session["id"], "label": session["title"], "description": session.get("prompt_preview") or "Chat"})
        visible = []
        for item in results:
            typ = item.get("type")
            rid = item.get("id")
            lifecycle_type = {"entity": "entity_family"}.get(typ, typ)
            if rid and lifecycle_type != "command" and foundation.is_hidden(lifecycle_type, rid):
                continue
            if typ == "entity_variant" and item.get("family_id") and foundation.is_hidden("entity_family", item["family_id"]):
                continue
            folder_id = item.get("folder_id")
            if folder_id:
                scope_ids = bible_folder_ids if typ in {"entity", "entity_family", "entity_variant"} else project_folder_ids
                if folder_id not in scope_ids:
                    continue
            visible.append(item)
            if len(visible) >= limit:
                break
        return {"results": visible}

    @app.get("/api/home")
    def home(project_id: str | None = Query(None), world_id: str | None = Query(None), branch_id: str | None = Query(None)):
        project_folders = effective_folders(workspace.list_folders(project_id)) if project_id else []
        visible_project_folder_ids = {folder["id"] for folder in project_folders}
        documents = [
            doc for doc in foundation.filter_visible("document", workspace.list_documents(project_id) if project_id else [])
            if resource_folder_visible(doc, visible_project_folder_ids)
        ]
        sessions = [session for session in history.list_sessions(project_id=project_id, limit=8) if not foundation.is_hidden("session", session["id"])]
        return {
            "active_scene": workspace.get_active_scene(project_id) if project_id else None,
            "recent_documents": sorted(documents, key=lambda x: x.get("updated_at", ""), reverse=True)[:8],
            "recent_chats": sessions[:8],
            "issues": foundation.list_issues(project_id=project_id, world_id=world_id, branch_id=branch_id, limit=8),
            "activity": foundation.list_activity(project_id, limit=10),
            "feedback": history.dataset_stats(),
            "favorites": foundation.list_favorites(project_id),
        }

    @app.post("/api/projects/world-link")
    def link_project_world(payload: ProjectWorldLinkPayload):
        try:
            result = workspace.link_project_world(payload.project_id, payload.world_id, role=payload.role)
            if payload.role == "primary":
                workspace.update_project(payload.project_id, default_world_id=payload.world_id)
            return result
        except KeyError as exc:
            raise HTTPException(404, "Project or world not found") from exc

    @app.post("/api/state-proposals")
    def state_proposals(payload: StateProposalPayload):
        """Run Arline's deterministic structural/state pipeline without touching canon."""
        text = payload.text.strip()
        if not text:
            raise HTTPException(400, "Text is empty")
        try:
            result = ArlineAnalyticalPipeline.default().run(text)
        except Exception as exc:
            raise HTTPException(500, f"State proposal analysis failed: {exc}") from exc
        extracted = result.extracted_state or {}
        events = result.events or {}
        return {
            "source": {
                "project_id": payload.project_id,
                "world_id": payload.world_id,
                "branch_id": payload.branch_id,
                "session_id": payload.session_id,
                "turn_id": payload.turn_id,
            },
            "entities": extracted.get("entities", []),
            "relations": extracted.get("relations", []),
            "claims": extracted.get("claims", []),
            "reference_resolutions": extracted.get("reference_resolutions", []),
            "patches": events.get("state_patches", []),
            "events": events.get("events", []),
            "conflicts": events.get("conflicts", []),
            "uncertainties": (result.analysis or {}).get("uncertainties", []),
        }

    @app.post("/api/library/entity-merge/preview")
    def entity_merge_preview(payload: EntityFamilyMergePayload):
        try:
            return workspace.preview_entity_family_merge(payload.source_family_id, payload.target_family_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/library/entity-merge")
    def entity_merge(payload: EntityFamilyMergePayload):
        try:
            source = workspace.get_entity_family(payload.source_family_id)
            source_aliases = foundation.list_aliases("entity_family", payload.source_family_id)
            result = workspace.merge_entity_families(payload.source_family_id, payload.target_family_id)
            foundation.merge_resource_refs("entity_family", payload.source_family_id, payload.target_family_id)
            try:
                foundation.add_alias("entity_family", payload.target_family_id, source["name"])
                for alias in source_aliases:
                    foundation.add_alias("entity_family", payload.target_family_id, alias["alias"])
            except ValueError:
                pass
            foundation.log_activity(None, "identity_merge", "entity_family", payload.target_family_id, label=result["name"], detail={"merged_from": payload.source_family_id})
            return result
        except (KeyError, ValueError, sqlite3.IntegrityError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/quick-create/preview")
    def quick_create_preview(payload: QuickCreatePayload):
        try:
            preview = parse_quick_create(payload.text, forced_kind=payload.forced_kind)
            data = preview.to_dict()
            if payload.entity_type:
                data["entity_type"] = payload.entity_type
            if payload.name:
                data["name"] = payload.name
            # Identity resolver: Quick Create should prefer linking an existing
            # Library object over silently producing a near-duplicate.
            candidate_name = str(data.get("name") or payload.text).strip()
            matches: list[dict[str, Any]] = []
            if data.get("kind") == "entity" and candidate_name:
                candidate_type = data.get("entity_type")
                families = foundation.filter_visible("entity_family", workspace.list_entity_families(None))
                by_id = {family["id"]: family for family in families}
                by_match: dict[str, dict[str, Any]] = {}
                for family in families:
                    if candidate_type and family.get("entity_type") != candidate_type:
                        continue
                    score = SequenceMatcher(None, candidate_name.casefold(), str(family.get("name") or "").casefold()).ratio()
                    if score >= 0.68:
                        by_match[family["id"]] = {
                            "type": "entity_family", "id": family["id"], "label": family["name"],
                            "entity_type": family.get("entity_type"), "score": round(score, 3), "alias": None,
                        }
                for alias in foundation.alias_matches(candidate_name, limit=20):
                    if alias.get("resource_type") != "entity_family":
                        continue
                    family = by_id.get(alias.get("resource_id"))
                    if not family or (candidate_type and family.get("entity_type") != candidate_type):
                        continue
                    score = SequenceMatcher(None, candidate_name.casefold(), alias["alias"].casefold()).ratio()
                    current = by_match.get(family["id"])
                    if current is None or score > current["score"]:
                        by_match[family["id"]] = {
                            "type": "entity_family", "id": family["id"], "label": family["name"],
                            "entity_type": family.get("entity_type"), "score": round(score, 3), "alias": alias["alias"],
                        }
                matches = sorted(by_match.values(), key=lambda item: item["score"], reverse=True)
            data["possible_matches"] = matches[:5]
            return data
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/quick-create")
    def quick_create(payload: QuickCreatePayload):
        try:
            preview = parse_quick_create(payload.text, forced_kind=payload.forced_kind).to_dict()
            kind = preview["kind"]
            name = (payload.name or preview["name"]).strip()
            description = payload.description if payload.description is not None else preview.get("description", "")
            if kind == "project":
                return {"kind": kind, "resource": workspace.create_project(name, description=description)}
            if kind == "world":
                result = workspace.create_world(
                    payload.project_id, name, description=description, canon_status="draft",
                    inheritance_mode="none", clone_parent=False,
                )
                return {"kind": kind, "resource": result}
            if kind == "folder":
                if not payload.project_id:
                    raise ValueError("A project is required to create a folder")
                return {"kind": kind, "resource": workspace.create_folder(payload.project_id, name)}
            if kind == "document":
                if not payload.project_id:
                    raise ValueError("A project is required to create a document")
                result = workspace.create_document(
                    payload.project_id, name,
                    document_type=payload.document_type or preview.get("document_type") or "scene",
                    content="", world_id=payload.world_id,
                    branch_id=payload.branch_id if payload.branch_id != WORLD_BIBLE_BRANCH_ID else None,
                    folder_id=payload.folder_id,
                )
                return {"kind": kind, "resource": result}

            entity_type = payload.entity_type or preview.get("entity_type") or "lore"
            shared_core = payload.shared_core if payload.shared_core is not None else preview.get("shared_core", {})
            attributes = payload.attributes if payload.attributes is not None else preview.get("attributes", {})
            world_id = payload.world_id or WORLD_BIBLE_WORLD_ID
            branch_id = payload.branch_id
            if branch_id == WORLD_BIBLE_BRANCH_ID:
                branch_id = None
            family = workspace.create_entity_family(
                None, name, entity_type=entity_type, description=description,
                shared_core=shared_core, folder_id=payload.folder_id, create_variant_in_world=world_id, branch_id=branch_id,
            )
            variant = next(
                (item for item in family.get("variants", []) if item.get("world_id") == world_id and (item.get("branch_id") or None) == branch_id),
                family.get("variants", [None])[0] if family.get("variants") else None,
            )
            if variant and attributes:
                variant = workspace.update_variant(
                    variant["id"], attributes=attributes, summary=description, note="quick create",
                )
            if payload.project_id:
                workspace.set_project_manifest_ref(
                    payload.project_id, "entity_family", family["id"],
                    label=family["name"], priority=1,
                )
            return {"kind": "entity", "resource": family, "variant": variant, "preview": preview}
        except (KeyError, ValueError, sqlite3.IntegrityError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/projects/{project_id}/manifest")
    def project_manifest(project_id: str):
        try:
            return {
                "project": workspace.get_project(project_id),
                "refs": workspace.list_project_manifest_refs(project_id),
                "active_scene": workspace.get_active_scene(project_id),
                "overlays": workspace.list_project_overlays(project_id),
            }
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc

    @app.post("/api/projects/{project_id}/manifest/refs")
    def add_manifest_ref(project_id: str, payload: ManifestRefPayload):
        try:
            return workspace.set_project_manifest_ref(project_id, **payload.model_dump())
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc

    @app.delete("/api/projects/{project_id}/manifest/refs")
    def remove_manifest_ref(project_id: str, resource_type: str = Query(...), resource_id: str = Query(...)):
        workspace.remove_project_manifest_ref(project_id, resource_type, resource_id)
        return {"ok": True}

    @app.post("/api/projects/{project_id}/overlays")
    def upsert_overlay(project_id: str, payload: ProjectOverlayPayload):
        try:
            return workspace.upsert_project_overlay(project_id, **payload.model_dump())
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/overlays/{overlay_id}")
    def delete_overlay(overlay_id: str):
        try:
            workspace.delete_project_overlay(overlay_id)
            return {"ok": True}
        except KeyError as exc:
            raise HTTPException(404, "Overlay not found") from exc

    @app.get("/api/projects/{project_id}/active-scene")
    def get_active_scene(project_id: str):
        return {"active_scene": workspace.get_active_scene(project_id)}

    @app.put("/api/projects/{project_id}/active-scene")
    def set_active_scene(project_id: str, payload: ActiveScenePayload):
        try:
            return workspace.set_active_scene(project_id, **payload.model_dump())
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/projects/{project_id}/continuity")
    def continuity(project_id: str, world_id: str | None = Query(None), branch_id: str | None = Query(None)):
        try:
            return workspace.continuity_report(project_id, world_id=world_id, branch_id=branch_id)
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc

    @app.get("/api/projects/{project_id}/scene-cards")
    def list_scene_cards(project_id: str):
        try:
            workspace.get_project(project_id)
            return {"scene_cards": workspace.list_scene_cards(project_id)}
        except KeyError as exc:
            raise HTTPException(404, "Project not found") from exc

    @app.put("/api/projects/{project_id}/scene-cards/{document_id}")
    def set_scene_card(project_id: str, document_id: str, payload: SceneCardPayload):
        try:
            card = workspace.set_scene_card(project_id, document_id, **payload.model_dump())
            memory_service.schedule_document_refresh(document_id)
            return card
        except KeyError as exc:
            raise HTTPException(404, "Project or document not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/projects/{project_id}/scene-cards/{document_id}")
    def delete_scene_card(project_id: str, document_id: str):
        workspace.delete_scene_card(project_id, document_id)
        return {"ok": True}

    @app.post("/api/projects/{project_id}/staged-changes")
    def stage_change(project_id: str, payload: StagedChangePayload):
        try:
            return workspace.stage_change(project_id=project_id, **payload.model_dump())
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/projects/{project_id}/staged-changes")
    def list_staged(project_id: str, status: str = Query("pending"), world_id: str | None = Query(None), branch_id: str | None = Query(None)):
        return {"changes": workspace.list_staged_changes(project_id, status=status, world_id=world_id, branch_id=branch_id)}

    @app.post("/api/staged-changes/{change_id}/resolve")
    def resolve_staged(change_id: str, payload: StagedResolvePayload):
        try:
            return workspace.resolve_staged_change(change_id, accept=payload.accept)
        except KeyError as exc:
            raise HTTPException(404, "Staged change not found") from exc

    @app.post("/api/timeline")
    def add_timeline(payload: TimelineEventPayload):
        try:
            return workspace.add_timeline_event(**payload.model_dump())
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/timeline")
    def list_timeline(world_id: str = Query(...), branch_id: str | None = Query(None), owner_type: str | None = Query(None), owner_id: str | None = Query(None)):
        return {"events": workspace.list_timeline_events(world_id, branch_id=branch_id, owner_type=owner_type, owner_id=owner_id)}

    @app.get("/api/timeline/state")
    def timeline_state(world_id: str = Query(...), owner_type: str = Query(...), owner_id: str = Query(...), branch_id: str | None = Query(None), at_order: float | None = Query(None)):
        return workspace.timeline_state(world_id, owner_type=owner_type, owner_id=owner_id, branch_id=branch_id, at_order=at_order)

    @app.get("/api/context/recipes")
    def context_recipes(project_id: str | None = Query(None)):
        return {"recipes": workspace.list_context_recipes(project_id)}

    @app.post("/api/projects/{project_id}/context-recipes")
    def save_context_recipe(project_id: str, payload: ContextRecipePayload):
        try:
            return workspace.save_context_recipe(project_id, **payload.model_dump())
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/backlinks/{resource_type}/{resource_id}")
    def backlinks(resource_type: str, resource_id: str):
        return workspace.backlinks(resource_type, resource_id)

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
            result["branches"] = foundation.filter_visible("branch", result.get("branches", []))
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

    @app.delete("/api/worlds/{world_id}")
    def delete_world(world_id: str):
        try:
            _permanent_delete("world", world_id)
        except KeyError as exc:
            raise HTTPException(404, "World not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True}

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

    @app.get("/api/branches/compare/{left_branch_id}/{right_branch_id}")
    def compare_branches(left_branch_id: str, right_branch_id: str):
        try:
            return workspace.compare_branches(left_branch_id, right_branch_id)
        except KeyError as exc:
            raise HTTPException(404, "Branch not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/branches/{source_branch_id}/merge")
    def merge_branch(source_branch_id: str, payload: BranchMergePayload):
        try:
            return workspace.merge_branch_changes(
                source_branch_id, payload.target_branch_id, payload.changes, note=payload.note
            )
        except KeyError as exc:
            raise HTTPException(404, "Branch resource not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/branches/{branch_id}")
    def delete_branch(branch_id: str):
        try:
            _permanent_delete("branch", branch_id)
        except KeyError as exc:
            raise HTTPException(404, "Branch not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True}

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
            deleted_folder_ids = workspace.delete_folder(folder_id)
            for deleted_folder_id in deleted_folder_ids:
                history.clear_folder_reference(deleted_folder_id)
        except KeyError as exc:
            raise HTTPException(404, "Folder not found") from exc
        return {"ok": True}

    @app.post("/api/documents")
    def create_document(payload: DocumentPayload):
        try:
            document = workspace.create_document(**payload.model_dump())
            memory_service.schedule_document_refresh(document["id"])
            return document
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
            document = workspace.update_document(document_id, note=note, **data)
            memory_service.schedule_document_refresh(document_id)
            return document
        except KeyError as exc:
            raise HTTPException(404, "Document not found") from exc

    @app.delete("/api/documents/{document_id}")
    def delete_document(document_id: str):
        try:
            memory_service.cancel_document_refresh(document_id)
            workspace.delete_document(document_id)
            memory_service.forget_document(document_id)
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
        project_id: str | None = Query(None), entity_type: str | None = Query(None), search: str = Query("")
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

    @app.delete("/api/entities/families/{family_id}")
    def delete_entity_family(family_id: str):
        try:
            workspace.delete_entity_family(family_id)
        except KeyError as exc:
            raise HTTPException(404, "Entity family not found") from exc
        return {"ok": True}

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

    @app.delete("/api/entities/variants/{variant_id}")
    def delete_entity_variant(variant_id: str):
        try:
            workspace.delete_variant(variant_id)
        except KeyError as exc:
            raise HTTPException(404, "Variant not found") from exc
        return {"ok": True}

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

    @app.delete("/api/relationships/{relationship_id}")
    def delete_relationship(relationship_id: str):
        try:
            workspace.delete_relationship(relationship_id)
        except KeyError as exc:
            raise HTTPException(404, "Relationship not found") from exc
        return {"ok": True}

    @app.get("/api/templates")
    def list_templates(project_id: str | None = Query(None), entity_type: str | None = Query(None)):
        return {"templates": workspace.list_templates(project_id=project_id, entity_type=entity_type)}

    @app.post("/api/templates")
    def create_template(payload: TemplatePayload):
        try:
            return workspace.create_template(**payload.model_dump())
        except (KeyError, ValueError, sqlite3.IntegrityError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/templates/{template_id}")
    def delete_template(template_id: str):
        try:
            workspace.delete_template(template_id)
        except KeyError as exc:
            raise HTTPException(404, "Template not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True}

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

    @app.delete("/api/tags/{tag_id}")
    def delete_tag(tag_id: str):
        try:
            workspace.delete_tag(tag_id)
        except KeyError as exc:
            raise HTTPException(404, "Tag not found") from exc
        return {"ok": True}

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

    @app.delete("/api/facts/{fact_id}")
    def delete_fact(fact_id: str):
        try:
            workspace.delete_fact(fact_id)
        except KeyError as exc:
            raise HTTPException(404, "Fact not found") from exc
        return {"ok": True}

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

    @app.delete("/api/snapshots/{snapshot_id}")
    def delete_snapshot(snapshot_id: str):
        try:
            workspace.delete_snapshot(snapshot_id)
        except KeyError as exc:
            raise HTTPException(404, "Snapshot not found") from exc
        return {"ok": True}

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
        q: str = Query(""), project_id: str | None = Query(None),
        world_id: str | None = Query(None), branch_id: str | None = Query(None),
        limit: int = Query(20, ge=1, le=50),
    ):
        project_folder_ids = visible_folder_ids(project_id)
        bible_folder_ids = visible_folder_ids(WORLD_BIBLE_PROJECT_ID)
        active_scene = workspace.get_active_scene(project_id) if project_id else {}
        dynamic_results = DirectiveEngine.dynamic_reference_suggestions(
            q, active_scene=active_scene or {}, world_id=world_id, branch_id=branch_id,
        )
        raw_results = workspace.search_mentions(
            q.split(".", 1)[0], project_id=project_id, world_id=world_id,
            branch_id=branch_id, limit=limit,
        )
        results = list(dynamic_results)
        for item in raw_results:
            lifecycle_type = {"entity": "entity_family"}.get(item.get("type"), item.get("type"))
            if item.get("id") and foundation.is_hidden(lifecycle_type, item["id"]):
                continue
            if item.get("type") == "entity_variant" and item.get("family_id") and foundation.is_hidden("entity_family", item["family_id"]):
                continue
            folder_id = item.get("folder_id")
            if folder_id:
                scope_ids = bible_folder_ids if item.get("type") in {"entity_family", "entity_variant"} else project_folder_ids
                if folder_id not in scope_ids:
                    continue
            results.append(item)
        known = {(item.get("type"), item.get("id")) for item in results}
        for alias in foundation.alias_matches(q, limit=limit):
            key = (alias["resource_type"], alias["resource_id"])
            if key in known or foundation.is_hidden(*key):
                continue
            try:
                resource = _resource_payload(*key)
            except KeyError:
                continue
            folder_scope = bible_folder_ids if alias["resource_type"] in {"entity_family", "entity_variant"} else project_folder_ids
            if resource.get("folder_id") and not resource_folder_visible(resource, folder_scope):
                continue
            label = resource.get("display_name") or resource.get("name") or resource.get("title") or alias["alias"]
            results.insert(0, {
                "type": alias["resource_type"], "id": alias["resource_id"], "label": label,
                "subtitle": f"alias · {alias['alias']}", "current_world": True,
            })
            known.add(key)
        return {"results": results[:limit]}

    @app.get("/api/commands")
    def commands(q: str = Query(""), project_id: str | None = Query(None)):
        return {
            "results": workspace.command_search(q, project_id=project_id),
            "command_registry_version": COMMAND_REGISTRY_VERSION,
            "commands": DirectiveEngine.catalog(),
            "reference_selectors": list(REFERENCE_SELECTORS),
            "dynamic_references": list(DYNAMIC_REFERENCES),
        }

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
        sessions = history.list_sessions(
            search=search, limit=limit, project_id=project_id,
            world_id=world_id, branch_id=branch_id, folder_id=folder_id,
            tag=tag, session_kind=session_kind,
        )
        return {"sessions": foundation.filter_visible("session", sessions)}

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

    @app.get("/api/sessions/{session_id}/forks")
    def session_forks(session_id: str):
        try:
            return history.list_session_forks(session_id)
        except KeyError as exc:
            raise HTTPException(404, "Session not found") from exc

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
                scratch_mode=payload.scratch_mode,
                world_fork_id=payload.world_fork_id,
            )
        except KeyError as exc:
            raise HTTPException(404, "Session not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/sessions/{session_id}")
    def delete_session(session_id: str):
        try:
            memory_service.cancel_session_refreshes(session_id)
            history.delete_session(session_id)
            memory_service.forget_session(session_id)
        except KeyError as exc:
            raise HTTPException(404, "Session not found") from exc
        return {"ok": True}

    @app.get("/api/turns/{turn_id}")
    def get_turn(turn_id: str):
        try:
            return history.get_turn(turn_id)
        except KeyError as exc:
            raise HTTPException(404, "Turn not found") from exc

    @app.delete("/api/turns/{turn_id}")
    def delete_turn(turn_id: str):
        try:
            deleted = history.delete_turn(turn_id)
        except KeyError as exc:
            raise HTTPException(404, "Turn not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        try:
            memory_service.forget_turn(turn_id)
        except Exception as exc:
            memory_service._report_refresh_failure(f"turn-delete:{turn_id}", exc)
        return {"ok": True, "turn_id": turn_id, "session_id": deleted.get("session_id")}

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
        memory_service.schedule_turn_refresh(turn["id"])
        return {"ok": True, "turn": turn, "dataset": history.dataset_stats()}

    @app.get("/api/feedback/queue")
    def feedback_queue(status: str = Query("unreviewed"), limit: int = Query(100), project_id: str | None = Query(None)):
        return {"items": history.feedback_queue(status=status, limit=limit, project_id=project_id)}

    @app.get("/api/feedback/comparisons")
    def feedback_comparisons(project_id: str | None = Query(None), limit: int = Query(100)):
        return {"items": history.preference_opportunities(project_id=project_id, limit=limit)}

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
                    recipe_id=payload.context_recipe_id,
                )
                if cfg.workspace.context_enabled and (payload.project_id or payload.world_id)
                else None
            )
            if ws_context is not None:
                ws_context = _augment_memory_context(
                    payload.prompt, payload, ws_context,
                    project_id=payload.project_id,
                    world_id=payload.world_id,
                    branch_id=payload.branch_id,
                    session_id=payload.session_id,
                    refs=refs,
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

    def _sse(event: str, payload: dict[str, Any]) -> str:
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

    @app.post("/api/generate/stream")
    async def generate_stream(payload: PromptPayload):
        if not payload.prompt.strip():
            raise HTTPException(400, "Prompt is empty")
        if payload.generation_mode != "single":
            raise HTTPException(400, "Inline streaming currently supports single-response mode; beats use the normal generation endpoint")

        async def events():
            existing_session = None
            if payload.session_id:
                try:
                    existing_session = history.get_session_meta(payload.session_id)
                except KeyError:
                    yield _sse("error", {"message": "Session not found"})
                    return
            cfg = _apply_payload(RuntimeConfig.load(config_path), payload)
            project_id = payload.project_id or (existing_session or {}).get("project_id")
            world_id = payload.world_id or (existing_session or {}).get("world_id")
            branch_id = payload.branch_id or (existing_session or {}).get("branch_id")
            refs = [item.model_dump() for item in payload.references]
            if not refs and existing_session:
                refs = existing_session.get("workspace_refs") or []

            ws_context = None
            if cfg.workspace.context_enabled and (project_id or world_id):
                try:
                    ws_context = workspace_context.resolve(project_id=project_id, world_id=world_id, branch_id=branch_id, references=refs, recipe_id=payload.context_recipe_id)
                except (KeyError, ValueError) as exc:
                    yield _sse("error", {"message": f"Workspace context error: {exc}"})
                    return
            if ws_context is not None:
                ws_context = _augment_memory_context(
                    payload.prompt, payload, ws_context,
                    project_id=project_id,
                    world_id=world_id,
                    branch_id=branch_id,
                    session_id=(existing_session or {}).get("id"),
                    refs=refs,
                )
            session_context = ""
            if existing_session is not None and cfg.history.smart_hybrid_continuity and payload.input_mode == "smart_hybrid":
                context_policy = (ws_context.scope.get("context_policy") if ws_context else {}) or {}
                requested_turns = context_policy.get("recent_turns", cfg.history.continuity_turns)
                try: requested_turns = max(1, min(50, int(requested_turns)))
                except (TypeError, ValueError): requested_turns = cfg.history.continuity_turns
                session_context = history.build_continuity_context(existing_session["id"], max_turns=requested_turns, max_chars=cfg.history.continuity_chars)

            if existing_session is not None:
                session = existing_session
                history.update_session(session["id"], project_id=project_id, world_id=world_id, branch_id=branch_id, folder_id=None, workspace_refs=refs, scratch_mode=payload.scratch_mode)
            else:
                session = history.create_session(prompt=payload.prompt, project_id=project_id, world_id=world_id, branch_id=branch_id, folder_id=None, session_kind="chat", workspace_refs=refs, scratch_mode=payload.scratch_mode)

            run_id = make_run_id(payload.input_mode, payload.reasoning, payload.timezone)
            base = run_id; index = 2
            while saved_cache.get(run_id) is not None:
                run_id = f"{base}-{index:02d}"; index += 1
            yield _sse("run.start", {"run_id": run_id, "session_id": session["id"], "session_title": session["title"]})

            prepared = None
            partial_story = ""
            partial_reasoning = ""
            try:
                streamer = StreamingArlineService(cfg)
                async for event in streamer.stream(payload.prompt, mode=payload.input_mode, session_context=session_context or None, workspace_context=ws_context):
                    event_type = event.get("type")
                    if event_type == "_prepared":
                        prepared = event["prepared"]
                        continue
                    if event_type == "answer.delta": partial_story += event.get("content", "")
                    if event_type == "reasoning.delta": partial_reasoning += event.get("content", "")
                    if event_type != "_complete":
                        yield _sse(event_type or "message", event)
                        continue

                    bundle = event["bundle"]
                    quality_report = event["quality"]
                    post = bundle.post_validation.to_dict() if bundle.post_validation else {}
                    post["quality_report"] = quality_report
                    saved_cache.put(CachedRun(config=cfg, bundle=bundle, run_id=run_id))
                    lineage = {
                        "application_version": STUDIO_VERSION,
                        "wcf_version": bundle.analysis.writer_context.version,
                        "aif_core_profile": "teacher",
                        "projection_mode": cfg.projection.mode,
                        "narrative_runtime_version": bundle.analysis.narrative_runtime.version,
                        "narrative_brief_version": bundle.analysis.narrative_brief.version,
                        "workspace_context_version": ws_context.version if ws_context else None,
                        "validator_version": post.get("metrics", {}).get("validator_version") if post else None,
                        "model": cfg.lmstudio.model,
                        "run_status": "completed",
                    }
                    turn = history.add_turn(
                        session["id"], run_id=run_id, user_prompt=payload.prompt, story=bundle.story,
                        model=cfg.lmstudio.model, mode=cfg.writer.input_mode, reasoning=cfg.generation.reasoning,
                        projection_mode=cfg.projection.mode, reasoning_text=bundle.reasoning or "", stats=bundle.stats,
                        wcf=bundle.analysis.rendered_context.text, aif_core=bundle.analysis.aif_core,
                        session_context=session_context, workspace_context=ws_context.text if ws_context else "",
                        workspace_scope=ws_context.scope if ws_context else {}, workspace_refs=refs, lineage=lineage,
                        projections=[x.to_dict() for x in bundle.analysis.writer_context.projections], post_validation=post,
                        wcf_validation=bundle.analysis.wcf_validation.to_dict(),
                    )
                    memory_service.schedule_turn_refresh(turn["id"])
                    final_session = history.get_session_meta(session["id"])
                    result = {
                        "run_id": run_id, "session_id": final_session["id"], "session_title": final_session["title"], "turn_id": turn["id"],
                        "continuity_context_used": bool(session_context), "story": bundle.story,
                        "wcf": bundle.analysis.rendered_context.text, "aif_core": bundle.analysis.aif_core,
                        "narrative_brief": bundle.analysis.narrative_brief.to_dict(), "workspace_context": ws_context.to_dict() if ws_context else {},
                        "context_breakdown": _context_breakdown(cfg, bundle.analysis, session_context=session_context),
                        "projections": [x.to_dict() for x in bundle.analysis.writer_context.projections],
                        "reasoning": bundle.reasoning if cfg.ui.show_reasoning else "", "stats": bundle.stats,
                        "post_validation": post, "quality_report": quality_report,
                        "wcf_validation": bundle.analysis.wcf_validation.to_dict(), "summary": _analysis_summary(bundle.analysis),
                        "trace_choices": _trace_choices(bundle.analysis), "scratch_mode": payload.scratch_mode,
                    }
                    yield _sse("quality", quality_report)
                    yield _sse("done", result)
            except asyncio.CancelledError:
                if partial_story and prepared is not None:
                    quality_report = ProseQualityAnalyzer().analyze(partial_story)
                    try:
                        history.add_turn(
                            session["id"], run_id=run_id, user_prompt=payload.prompt, story=partial_story,
                            model=cfg.lmstudio.model, mode=cfg.writer.input_mode, reasoning=cfg.generation.reasoning,
                            projection_mode=cfg.projection.mode, reasoning_text=partial_reasoning,
                            stats={"run_status": "cancelled", "partial": True}, wcf=prepared.analysis.rendered_context.text,
                            aif_core=prepared.analysis.aif_core, session_context=session_context,
                            workspace_context=ws_context.text if ws_context else "", workspace_scope=ws_context.scope if ws_context else {},
                            workspace_refs=refs, lineage={"application_version": STUDIO_VERSION, "run_status": "cancelled", "model": cfg.lmstudio.model},
                            projections=[x.to_dict() for x in prepared.analysis.writer_context.projections],
                            post_validation={"quality_report": quality_report}, wcf_validation=prepared.analysis.wcf_validation.to_dict(),
                        )
                    except Exception:
                        pass
                raise
            except Exception as exc:
                if partial_story and prepared is not None:
                    try:
                        history.add_turn(
                            session["id"], run_id=run_id, user_prompt=payload.prompt, story=partial_story,
                            model=cfg.lmstudio.model, mode=cfg.writer.input_mode, reasoning=cfg.generation.reasoning,
                            projection_mode=cfg.projection.mode, reasoning_text=partial_reasoning,
                            stats={"run_status": "failed", "partial": True, "error": str(exc)}, wcf=prepared.analysis.rendered_context.text,
                            aif_core=prepared.analysis.aif_core, session_context=session_context,
                            workspace_context=ws_context.text if ws_context else "", workspace_scope=ws_context.scope if ws_context else {},
                            workspace_refs=refs, lineage={"application_version": STUDIO_VERSION, "run_status": "failed", "model": cfg.lmstudio.model},
                            projections=[x.to_dict() for x in prepared.analysis.writer_context.projections],
                            post_validation={"quality_report": ProseQualityAnalyzer().analyze(partial_story)}, wcf_validation=prepared.analysis.wcf_validation.to_dict(),
                        )
                    except Exception:
                        pass
                yield _sse("error", {"message": str(exc)})

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

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
        # Project folders are a document/filesystem concern in v1.1. Chats
        # remain a separate layer even when attached to the same project.
        folder_id = None
        refs = [item.model_dump() for item in payload.references]
        if not refs and existing_session:
            refs = existing_session.get("workspace_refs") or []

        ws_context = None
        if cfg.workspace.context_enabled and (project_id or world_id):
            try:
                ws_context = workspace_context.resolve(
                    project_id=project_id,
                    world_id=world_id,
                    branch_id=branch_id,
                    references=refs,
                    recipe_id=payload.context_recipe_id,
                )
            except (KeyError, ValueError) as exc:
                raise HTTPException(400, f"Workspace context error: {exc}") from exc

        if ws_context is not None:
            ws_context = _augment_memory_context(
                payload.prompt, payload, ws_context,
                project_id=project_id,
                world_id=world_id,
                branch_id=branch_id,
                session_id=(existing_session or {}).get("id"),
                refs=refs,
            )
        session_context = ""
        if (
            existing_session is not None
            and cfg.history.smart_hybrid_continuity
            and payload.input_mode == "smart_hybrid"
        ):
            context_policy = (ws_context.scope.get("context_policy") if ws_context else {}) or {}
            requested_turns = context_policy.get("recent_turns", cfg.history.continuity_turns)
            try:
                requested_turns = max(1, min(50, int(requested_turns)))
            except (TypeError, ValueError):
                requested_turns = cfg.history.continuity_turns
            session_context = history.build_continuity_context(
                existing_session["id"],
                max_turns=requested_turns,
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
        quality_report = ProseQualityAnalyzer().analyze(bundle.story)
        post["quality_report"] = quality_report
        if existing_session is not None:
            session = existing_session
            history.update_session(
                session["id"],
                project_id=project_id,
                world_id=world_id,
                branch_id=branch_id,
                folder_id=folder_id,
                workspace_refs=refs,
                scratch_mode=payload.scratch_mode,
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
                scratch_mode=payload.scratch_mode,
            )

        lineage = {
            "application_version": STUDIO_VERSION,
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
        memory_service.schedule_turn_refresh(turn["id"])
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
            "quality_report": quality_report,
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
            "scratch_mode": payload.scratch_mode,
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


    def _public_media(item: dict[str, Any]) -> dict[str, Any]:
        result = dict(item)
        result.pop("storage_path", None)
        result["content_url"] = f"/api/media/{item['id']}/content"
        return result

    def _decode_media_data_url(data_url: str) -> tuple[str, bytes]:
        match = re.fullmatch(r"data:([^;,]+);base64,(.+)", data_url.strip(), flags=re.DOTALL)
        if not match:
            raise ValueError("Expected a base64 image data URL")
        mime = match.group(1).lower()
        if mime not in MEDIA_MIME_EXTENSIONS:
            raise ValueError("Supported images: PNG, JPEG, WebP, and GIF")
        encoded = re.sub(r"\s+", "", match.group(2))
        if len(encoded) > MAX_MEDIA_BYTES * 2:
            raise ValueError("Image is too large")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Invalid base64 image payload") from exc
        if not data or len(data) > MAX_MEDIA_BYTES:
            raise ValueError(f"Image must be between 1 byte and {MAX_MEDIA_BYTES // (1024 * 1024)} MiB")
        return mime, data

    @app.get("/api/media")
    def list_media(
        resource_type: str | None = Query(None),
        resource_id: str | None = Query(None),
        cover_only: bool = Query(False),
    ):
        return {"items": [_public_media(item) for item in foundation.list_media(
            resource_type=resource_type, resource_id=resource_id, cover_only=cover_only
        )]}

    @app.post("/api/media")
    def create_media(payload: MediaCreatePayload):
        if payload.resource_type not in MEDIA_RESOURCE_TYPES:
            raise HTTPException(400, "Unsupported media resource type")
        try:
            _resource_payload(payload.resource_type, payload.resource_id)
            mime, data = _decode_media_data_url(payload.data_url)
        except KeyError as exc:
            raise HTTPException(404, "Media owner not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        suffix = MEDIA_MIME_EXTENSIONS[mime]
        storage_path = (media_root / f"{uuid4().hex}{suffix}").resolve()
        storage_path.write_bytes(data)
        try:
            item = foundation.create_media(
                payload.resource_type, payload.resource_id,
                storage_path=str(storage_path), mime_type=mime,
                original_name=Path(payload.filename).name[:240], kind=payload.kind,
                caption=payload.caption, is_cover=payload.is_cover,
                sort_order=payload.sort_order,
            )
        except Exception:
            storage_path.unlink(missing_ok=True)
            raise
        foundation.log_activity(None, "media_added", payload.resource_type, payload.resource_id, label=payload.filename)
        return _public_media(item)

    @app.get("/api/media/{media_id}/content")
    def media_content(media_id: str):
        try:
            item = foundation.get_media(media_id)
        except KeyError as exc:
            raise HTTPException(404, "Media not found") from exc
        path = Path(item["storage_path"])
        if not path.exists() or not path.is_file():
            raise HTTPException(404, "Media file is missing")
        return FileResponse(path, media_type=item["mime_type"], filename=item.get("original_name") or path.name)

    @app.patch("/api/media/{media_id}")
    def patch_media(media_id: str, payload: MediaPatchPayload):
        try:
            item = foundation.update_media(media_id, **payload.model_dump(exclude_none=True))
        except KeyError as exc:
            raise HTTPException(404, "Media not found") from exc
        return _public_media(item)

    @app.delete("/api/media/{media_id}")
    def delete_media(media_id: str):
        try:
            item = foundation.get_media(media_id)
            foundation.delete_media(media_id)
        except KeyError as exc:
            raise HTTPException(404, "Media not found") from exc
        foundation.log_activity(None, "media_deleted", item["resource_type"], item["resource_id"], label=item.get("original_name") or media_id)
        return {"deleted": True, "id": media_id}

    @app.post("/api/media/{media_id}/describe")
    def describe_media(media_id: str, payload: MediaDescribePayload):
        try:
            item = foundation.get_media(media_id)
        except KeyError as exc:
            raise HTTPException(404, "Media not found") from exc
        path = Path(item["storage_path"])
        if not path.exists() or not path.is_file():
            raise HTTPException(404, "Media file is missing")
        cfg = RuntimeConfig.load(config_path)
        if payload.server_url:
            cfg.lmstudio.base_url = RuntimeConfig.normalize_server_url(payload.server_url)
        if payload.api_key is not None:
            cfg.lmstudio.api_key = payload.api_key
        if payload.model:
            cfg.lmstudio.model = payload.model
        if not cfg.lmstudio.model:
            raise HTTPException(400, "Select a model first")
        client = LMStudioClient(
            base_url=cfg.lmstudio.base_url,
            api_key=cfg.lmstudio.api_key,
            timeout_seconds=cfg.lmstudio.timeout_seconds,
        )
        try:
            if not client.vision_supported(cfg.lmstudio.model):
                raise HTTPException(400, "The selected model does not report vision support in LM Studio")
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            data_url = f"data:{item['mime_type']};base64,{encoded}"
            reasoning_cfg = client.reasoning_config(cfg.lmstudio.model)
            reasoning = "off" if "off" in reasoning_cfg.get("allowed_options", []) else None
            prompt = payload.prompt.strip() or (
                "Describe this image precisely for a fiction/worldbuilding reference library. "
                "Only describe visually observable details. Separate uncertain impressions from facts. "
                "Do not invent identity, backstory, measurements, relationships, or hidden anatomy."
            )
            result = client.chat(
                model=cfg.lmstudio.model,
                input_text=prompt,
                system_prompt=(
                    "You are Arline's visual reference describer. Return a concise, concrete visual description. "
                    "This output is a reviewable media-description proposal, not canon."
                ),
                images=[data_url],
                temperature=0.2,
                top_p=0.9,
                top_k=20,
                min_p=0.0,
                max_tokens=1200,
                repeat_penalty=1.02,
                reasoning=reasoning,
                context_length=min(int(cfg.model_load.context_length), 16384),
            )
        except LMStudioError as exc:
            raise HTTPException(503, str(exc)) from exc
        return {
            "media_id": media_id,
            "model": cfg.lmstudio.model,
            "description": result.text,
            "stats": result.stats,
            "proposal": True,
            "saved": False,
            "canon_changed": False,
        }

    return app


def launch_ui(config_path: Path | str = DEFAULT_CONFIG_PATH) -> None:
    cfg=RuntimeConfig.load(config_path);host=str(cfg.ui.host or "127.0.0.1").strip().lower()
    if host not in {"127.0.0.1","localhost","::1"} and os.getenv("ARLINE_ALLOW_UNAUTHENTICATED_REMOTE_UI")!="1":
        raise RuntimeError("Refusing unauthenticated remote UI bind. Keep ui.host on loopback or explicitly set ARLINE_ALLOW_UNAUTHENTICATED_REMOTE_UI=1.")
    uvicorn.run(
        create_app(config_path),
        host=cfg.ui.host,
        port=cfg.ui.port,
        log_level="info",
    )


# Standard ASGI target: uvicorn src.interface.web.app:app
app = create_app()
