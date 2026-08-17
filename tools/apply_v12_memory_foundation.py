from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Missing patch anchor: {label}")
    return text.replace(old, new, 1)


def patch_workspace_context() -> None:
    path = "src/workspace/context.py"
    text = read(path)
    text = replace_once(
        text,
        "    def __init__(self, store: WorkspaceStore, *, max_items: int = 24):\n        self.store = store\n        self.max_items = max_items\n",
        "    def __init__(self, store: WorkspaceStore, *, max_items: int = 24, memory_service=None):\n        self.store = store\n        self.max_items = max_items\n        self.memory_service = memory_service\n",
        "WorkspaceContextResolver constructor",
    )
    text = replace_once(
        text,
        "        references: list[dict[str, Any]] | None = None,\n        recipe_id: str | None = None,\n    ) -> WorkspaceContext:\n",
        "        references: list[dict[str, Any]] | None = None,\n        recipe_id: str | None = None,\n        query_text: str = \"\",\n        session_id: str | None = None,\n        current_turn_id: str | None = None,\n        world_time: Any = None,\n        story_order: float | None = None,\n        pov_variant_id: str | None = None,\n        context_lens: str = \"scene\",\n        allow_scratch: bool = False,\n        allow_future_author_knowledge: bool = False,\n        explicit_cross_scope_sources: list[dict[str, str]] | None = None,\n    ) -> WorkspaceContext:\n",
        "WorkspaceContextResolver resolve signature",
    )
    match = re.search(r"\n        return WorkspaceContext\(\n(?P<body>.*?)\n        \)\n", text, flags=re.S)
    if not match:
        raise RuntimeError("Could not find WorkspaceContext return block")
    replacement = (
        "\n        context = WorkspaceContext(\n" + match.group("body") + "\n        )\n"
        "        if self.memory_service is not None and query_text.strip():\n"
        "            from src.memory import MemoryQueryContext\n"
        "            memory_result = self.memory_service.retrieve(\n"
        "                query_text,\n"
        "                MemoryQueryContext(\n"
        "                    project_id=project_id, world_id=world_id, branch_id=branch_id,\n"
        "                    session_id=session_id, current_turn_id=current_turn_id,\n"
        "                    world_time=world_time, story_order=story_order,\n"
        "                    pov_variant_id=pov_variant_id or (active_scene or {}).get('pov_variant_id'),\n"
        "                    context_lens=context_lens, explicit_references=refs,\n"
        "                    explicit_cross_scope_sources=explicit_cross_scope_sources or [],\n"
        "                    allow_scratch=allow_scratch,\n"
        "                    allow_future_author_knowledge=allow_future_author_knowledge,\n"
        "                ),\n"
        "            )\n"
        "            context = self.memory_service.augment_workspace_context(context, memory_result)\n"
        "        return context\n"
    )
    text = text[:match.start()] + replacement + text[match.end():]
    write(path, text)


def patch_app() -> None:
    path = "src/interface/web/app.py"
    text = read(path)
    text = replace_once(
        text,
        "from src.workspace.store import WORKSPACE_SCHEMA_VERSION\n",
        "from src.workspace.store import WORKSPACE_SCHEMA_VERSION\nfrom src.memory import (\n    ContextLens, MEMORY_SCHEMA_VERSION, MemoryConfig, MemoryQueryContext,\n    MemoryService, MemoryStore, SpatialMemory, TemporalMemory,\n)\n",
        "memory imports",
    )
    text = text.replace('STUDIO_VERSION = "1.1.0"', 'STUDIO_VERSION = "1.2.0a1"')
    text = replace_once(
        text,
        "    context_recipe_id: str | None = None\n    scratch_mode: bool = False\n",
        "    context_recipe_id: str | None = None\n    scratch_mode: bool = False\n    context_lens: str = \"scene\"\n    world_time: Any = None\n    story_order: float | None = None\n    pov_variant_id: str | None = None\n    allow_future_author_knowledge: bool = False\n    explicit_cross_scope_sources: list[dict[str, str]] = Field(default_factory=list)\n",
        "PromptPayload memory fields",
    )
    payload_anchor = "class SavePayload(BaseModel):\n    run_id: str\n"
    payloads = '''class MemoryBackfillPayload(BaseModel):
    project_id: str | None = None


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
    explicit_references: list[dict[str, Any]] = Field(default_factory=list)
    explicit_cross_scope_sources: list[dict[str, str]] = Field(default_factory=list)
    allow_scratch: bool = False
    allow_future_author_knowledge: bool = False


class SpatialEdgePayload(BaseModel):
    world_id: str
    subject_type: str
    subject_id: str
    relation: str
    object_type: str
    object_id: str
    branch_id: str | None = None
    structural: bool = True
    source_type: str = "manual"
    source_id: str | None = None
    story_order_from: float | None = None
    story_order_to: float | None = None


class CurrentStatePayload(BaseModel):
    world_id: str
    owner_type: str
    owner_id: str
    state_key: str
    value: Any
    branch_id: str | None = None
    source_type: str = "manual"
    source_id: str | None = None
    authority: str = "user_accepted_world_canon"


class StateIntervalPayload(CurrentStatePayload):
    valid_from_event_id: str | None = None
    valid_to_event_id: str | None = None
    valid_from_world_time: Any = None
    valid_to_world_time: Any = None
    story_order_from: float | None = None
    story_order_to: float | None = None


class EpistemicIntervalPayload(BaseModel):
    world_id: str
    character_variant_id: str
    topic_type: str
    topic_id: str
    state_type: str
    value: Any
    branch_id: str | None = None
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    story_order_from: float | None = None
    story_order_to: float | None = None
    source_type: str = "manual"
    source_id: str | None = None


class StoryThreadPayload(BaseModel):
    world_id: str
    thread_type: str
    title: str
    project_id: str | None = None
    branch_id: str | None = None
    description: str = ""
    status: str = "open"
    links: list[dict[str, Any]] = Field(default_factory=list)
    source_type: str = "manual"
    source_id: str | None = None


'''
    text = replace_once(text, payload_anchor, payloads + payload_anchor, "memory payloads")
    text = replace_once(
        text,
        '    migration_targets.setdefault(workspace_path, {})["workspace_meta"] = max(WORKSPACE_SCHEMA_VERSION, FoundationStore.SCHEMA_VERSION)\n',
        '    migration_targets.setdefault(workspace_path, {})["workspace_meta"] = max(WORKSPACE_SCHEMA_VERSION, FoundationStore.SCHEMA_VERSION)\n    migration_targets.setdefault(workspace_path, {})["memory_meta"] = MEMORY_SCHEMA_VERSION\n',
        "memory migration target",
    )
    text = replace_once(
        text,
        "    foundation = FoundationStore(initial_cfg.workspace.database_path)\n    media_root = workspace_path.parent / \"media\"\n",
        "    foundation = FoundationStore(initial_cfg.workspace.database_path)\n    memory_config = MemoryConfig.load(config_path)\n    memory_store = MemoryStore(initial_cfg.workspace.database_path)\n    memory_service = MemoryService(\n        store=memory_store, workspace=workspace, history=history, foundation=foundation,\n        config=memory_config, lmstudio_base_url=initial_cfg.lmstudio.base_url,\n        lmstudio_api_key=initial_cfg.lmstudio.api_key,\n    )\n    spatial_memory = SpatialMemory(memory_store)\n    temporal_memory = TemporalMemory(memory_store)\n    media_root = workspace_path.parent / \"media\"\n",
        "memory service initialization",
    )
    text = replace_once(
        text,
        "    workspace_context = WorkspaceContextResolver(\n        workspace, max_items=initial_cfg.workspace.pinned_context_limit\n    )\n",
        "    workspace_context = WorkspaceContextResolver(\n        workspace, max_items=initial_cfg.workspace.pinned_context_limit,\n        memory_service=memory_service,\n    )\n",
        "memory context integration",
    )
    # Multi-line calls use this anchor.
    text = text.replace(
        "                    recipe_id=payload.context_recipe_id,\n                )",
        "                    recipe_id=payload.context_recipe_id, query_text=payload.prompt,\n                    session_id=(existing_session or {}).get('id'), world_time=payload.world_time,\n                    story_order=payload.story_order, pov_variant_id=payload.pov_variant_id,\n                    context_lens=payload.context_lens, allow_scratch=payload.scratch_mode,\n                    allow_future_author_knowledge=payload.allow_future_author_knowledge,\n                    explicit_cross_scope_sources=payload.explicit_cross_scope_sources,\n                )",
    )
    text = text.replace(
        "                    recipe_id=payload.context_recipe_id,\n                )\n                if cfg.workspace.context_enabled",
        "                    recipe_id=payload.context_recipe_id, query_text=payload.prompt,\n                    world_time=payload.world_time, story_order=payload.story_order,\n                    pov_variant_id=payload.pov_variant_id, context_lens=payload.context_lens,\n                    allow_scratch=payload.scratch_mode,\n                    allow_future_author_knowledge=payload.allow_future_author_knowledge,\n                    explicit_cross_scope_sources=payload.explicit_cross_scope_sources,\n                )\n                if cfg.workspace.context_enabled",
    )
    text = text.replace(
        "workspace_context.resolve(project_id=project_id, world_id=world_id, branch_id=branch_id, references=refs, recipe_id=payload.context_recipe_id)",
        "workspace_context.resolve(project_id=project_id, world_id=world_id, branch_id=branch_id, references=refs, "
        "recipe_id=payload.context_recipe_id, query_text=payload.prompt, session_id=(existing_session or {}).get('id'), "
        "world_time=payload.world_time, story_order=payload.story_order, pov_variant_id=payload.pov_variant_id, "
        "context_lens=payload.context_lens, allow_scratch=payload.scratch_mode, "
        "allow_future_author_knowledge=payload.allow_future_author_knowledge, "
        "explicit_cross_scope_sources=payload.explicit_cross_scope_sources)",
    )
    routes = r'''

    # ------------------------------------------------------------------
    # v1.2 Memory Query Engine
    # ------------------------------------------------------------------

    def _memory_context(payload: MemoryQueryPayload) -> MemoryQueryContext:
        try:
            lens = ContextLens(payload.context_lens)
        except ValueError as exc:
            raise HTTPException(400, f"Unsupported context lens: {payload.context_lens}") from exc
        return MemoryQueryContext(
            project_id=payload.project_id, world_id=payload.world_id,
            branch_id=payload.branch_id, session_id=payload.session_id,
            current_turn_id=payload.current_turn_id, world_time=payload.world_time,
            story_order=payload.story_order, pov_variant_id=payload.pov_variant_id,
            context_lens=lens, explicit_references=payload.explicit_references,
            explicit_cross_scope_sources=payload.explicit_cross_scope_sources,
            allow_scratch=payload.allow_scratch,
            allow_future_author_knowledge=payload.allow_future_author_knowledge,
        )

    @app.get("/api/memory/status")
    def memory_status():
        return memory_service.status()

    @app.post("/api/memory/backfill")
    def memory_backfill(payload: MemoryBackfillPayload):
        job = foundation.create_job(
            "memory_backfill", project_id=payload.project_id,
            payload={"project_id": payload.project_id}, message="Indexing source-backed evidence",
        )
        try:
            foundation.update_job(job["id"], status="running", progress=0.05, message="Chunking documents and chats")
            result = memory_service.backfill(payload.project_id)
            foundation.update_job(job["id"], status="done", progress=1.0, message="Memory generation active", result=result)
            foundation.log_activity(payload.project_id, "memory_backfill", "memory_generation", str(result["generation_id"]), label=f"Indexed {result['chunks']} evidence chunks")
            return {**result, "job": foundation.get_job(job["id"])}
        except Exception as exc:
            foundation.update_job(job["id"], status="failed", message=str(exc))
            raise HTTPException(500, str(exc)) from exc

    @app.post("/api/memory/plan")
    def memory_plan(payload: MemoryQueryPayload):
        context = _memory_context(payload)
        return memory_service.query_engine.compiler.compile(payload.query, context).to_dict()

    @app.post("/api/memory/query")
    def memory_query(payload: MemoryQueryPayload):
        try:
            return memory_service.retrieve(payload.query, _memory_context(payload)).to_dict()
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc

    @app.get("/api/memory/retrieval/{run_id}")
    def memory_retrieval_trace(run_id: str):
        try:
            return memory_store.get_retrieval_run(run_id)
        except KeyError as exc:
            raise HTTPException(404, "Retrieval trace not found") from exc

    @app.get("/api/memory/chunks")
    def memory_chunks(
        source_type: str | None = Query(None), source_id: str | None = Query(None),
        resource_type: str | None = Query(None), resource_id: str | None = Query(None),
        status: str | None = Query("active"), limit: int = Query(200),
    ):
        if resource_type and resource_id:
            with memory_store.connection() as con:
                rows = con.execute(
                    "SELECT c.* FROM memory_chunks c JOIN memory_links l ON l.memory_chunk_id=c.id "
                    "WHERE l.resource_type=? AND l.resource_id=? AND (? IS NULL OR c.semantic_status=?) "
                    "ORDER BY c.updated_at DESC LIMIT ?",
                    (resource_type, resource_id, status, status, min(1000, max(1, limit))),
                ).fetchall()
            items = [memory_store.get_chunk(row["id"]) for row in rows]
        else:
            items = memory_store.list_chunks(source_type=source_type, source_id=source_id, status=status, limit=limit)
        return {"items": items}

    @app.post("/api/memory/spatial")
    def create_spatial_link(payload: SpatialEdgePayload):
        try:
            return spatial_memory.link(**payload.model_dump())
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/memory/spatial")
    def list_spatial_links(
        world_id: str, branch_id: str | None = Query(None),
        resource_type: str | None = Query(None), resource_id: str | None = Query(None),
        relation: str | None = Query(None),
    ):
        return {"items": memory_store.list_spatial_edges(
            world_id=world_id, branch_id=branch_id, resource_type=resource_type,
            resource_id=resource_id, relation=relation,
        )}

    @app.get("/api/memory/spatial/neighborhood")
    def spatial_neighborhood(
        world_id: str, resource_type: str, resource_id: str,
        branch_id: str | None = Query(None), depth: int = Query(2, ge=0, le=8),
    ):
        return spatial_memory.neighborhood(
            world_id=world_id, branch_id=branch_id,
            resource_type=resource_type, resource_id=resource_id, depth=depth,
        )

    @app.delete("/api/memory/spatial/{edge_id}")
    def delete_spatial_link(edge_id: str):
        try:
            spatial_memory.unlink(edge_id)
        except KeyError as exc:
            raise HTTPException(404, "Spatial link not found") from exc
        return {"deleted": True, "id": edge_id}

    @app.post("/api/memory/state/current")
    def set_current_memory_state(payload: CurrentStatePayload):
        memory_store.upsert_current_state(**payload.model_dump())
        return {"ok": True}

    @app.get("/api/memory/state/current")
    def get_current_memory_state(
        world_id: str, owner_type: str, owner_id: str,
        branch_id: str | None = Query(None), state_key: str | None = Query(None),
    ):
        return {"items": temporal_memory.current_state(
            world_id=world_id, branch_id=branch_id, owner_type=owner_type,
            owner_id=owner_id, state_key=state_key,
        )}

    @app.post("/api/memory/state/interval")
    def create_state_interval(payload: StateIntervalPayload):
        return memory_store.add_state_interval(**payload.model_dump())

    @app.get("/api/memory/state/at")
    def state_at_time(
        world_id: str, owner_type: str, owner_id: str,
        branch_id: str | None = Query(None), story_order: float | None = Query(None),
    ):
        return {"items": temporal_memory.state_at(
            world_id=world_id, branch_id=branch_id, owner_type=owner_type,
            owner_id=owner_id, story_order=story_order,
        )}

    @app.post("/api/memory/epistemic")
    def create_epistemic_interval(payload: EpistemicIntervalPayload):
        return memory_store.upsert_epistemic_interval(**payload.model_dump())

    @app.get("/api/memory/epistemic")
    def epistemic_state(
        world_id: str, character_variant_id: str,
        branch_id: str | None = Query(None), topic_type: str | None = Query(None),
        topic_id: str | None = Query(None), story_order: float | None = Query(None),
    ):
        return {"items": temporal_memory.epistemic_state(
            world_id=world_id, branch_id=branch_id,
            character_variant_id=character_variant_id,
            topic_type=topic_type, topic_id=topic_id, story_order=story_order,
        )}

    @app.post("/api/memory/threads")
    def create_story_thread(payload: StoryThreadPayload):
        return memory_store.create_thread(**payload.model_dump())

    @app.get("/api/memory/threads")
    def list_story_threads(
        world_id: str, branch_id: str | None = Query(None), status: str | None = Query(None),
        resource_type: str | None = Query(None), resource_id: str | None = Query(None),
    ):
        return {"items": memory_store.list_threads(
            world_id=world_id, branch_id=branch_id, status=status,
            resource_type=resource_type, resource_id=resource_id,
        )}

    @app.patch("/api/memory/threads/{thread_id}")
    def patch_story_thread(thread_id: str, payload: dict[str, Any]):
        try:
            return memory_store.update_thread(thread_id, **payload)
        except KeyError as exc:
            raise HTTPException(404, "Story thread not found") from exc

'''
    text = replace_once(text, "\n    return app\n", routes + "\n    return app\n", "memory API routes")
    write(path, text)


def patch_config() -> None:
    path = "config/arline.toml"
    text = read(path)
    if "[memory]" not in text:
        text = text.rstrip() + '''

[memory]
enabled = true
fts_enabled = true
# Dense retrieval is optional. Enable after the recommended embedding model is
# installed in LM Studio; structured indexes + FTS5 remain the fallback.
dense_enabled = false
automatic_context = true
default_lens = "scene"
chunk_chars = 1800
chunk_overlap_chars = 180
max_candidates = 60
final_k = 12
max_per_source = 2
rrf_k = 60
trace_enabled = true

[memory.embedding]
enabled = false
provider = "lmstudio"
model = "intfloat/multilingual-e5-base"
dimension = 768
query_prefix = "query: "
passage_prefix = "passage: "
batch_size = 32
timeout_seconds = 120.0

[memory.reranker]
# LM Studio currently has no native rerank endpoint. Keep disabled until an
# evaluated provider materially improves Arline-specific retrieval benchmarks.
enabled = false
provider = "disabled"
model = "Qwen/Qwen3-Reranker-0.6B"
top_k_input = 20
top_k_output = 8
'''
    write(path, text)


def patch_frontend() -> None:
    html_path = "src/interface/web/static/index.html"
    html = read(html_path)
    html = html.replace("Studio v1.1", "Studio v1.2 alpha")
    html = re.sub(r"1\.1\.3-media", "1.2.0-alpha1", html)
    if "/static/js/memory.js" not in html:
        html = html.replace(
            '<script src="/static/js/stream.js?v=1.2.0-alpha1" defer></script>',
            '<script src="/static/js/stream.js?v=1.2.0-alpha1" defer></script>\n  <script src="/static/js/memory.js?v=1.2.0-alpha1" defer></script>',
        )
    write(html_path, html)

    js_path = "src/interface/web/static/arline.js"
    js = read(js_path)
    if "window.state = state;" not in js:
        js = js.rstrip() + '''

// v1.2 extension points. The Memory UI is a separate classic script and uses
// these stable read/action surfaces without duplicating core state.
window.state = state;
window.collectPromptReferences = collectPromptReferences;
window.openEntitySheet = openEntitySheet;
window.promptPayload = promptPayload;
window.toast = toast;
'''
    write(js_path, js)

    css_path = "src/interface/web/static/arline.css"
    css = read(css_path)
    if ".memory-settings-card" not in css:
        css = css.rstrip() + '''

/* v1.2 Memory Query Engine */
.memory-settings-card{display:grid;gap:12px;padding:16px;border:1px solid var(--line);border-radius:16px;background:color-mix(in srgb,var(--panel) 92%,transparent);margin-top:16px}
.memory-settings-card h3{margin:0}.memory-settings-card label{display:grid;gap:6px}.memory-settings-actions{display:flex;gap:8px;flex-wrap:wrap}
.memory-runtime-status,.memory-settings-card .info-card{display:grid;gap:7px}.memory-settings-card .info-card>div{display:flex;justify-content:space-between;gap:18px}
.memory-settings-card small{color:var(--muted)}.memory-debugger{border-top:1px solid var(--line);padding-top:10px}.memory-debugger summary{cursor:pointer;font-weight:700}
.memory-debugger[open]{display:grid;gap:10px}.memory-debugger .json-block{max-height:360px;overflow:auto;white-space:pre-wrap}
.memory-entity-btn{margin-right:auto}
'''
    write(css_path, css)


def patch_metadata_docs_ci() -> None:
    pyproject = read("pyproject.toml")
    pyproject = re.sub(r'version = "[^"]+"', 'version = "1.2.0a1"', pyproject, count=1)
    pyproject = pyproject.replace(
        'description = "Arline story workspace with projects, worlds, entity variants, canon workflow, WCF, LM Studio writing, and dataset feedback"',
        'description = "Branch-aware, time-aware narrative workspace with evidence memory, specialized queries, LM Studio writing, and continuity tooling"',
    )
    write("pyproject.toml", pyproject)

    eval_init = read("src/eval/__init__.py")
    if "MemoryEvalCase" not in eval_init:
        eval_init = eval_init.rstrip() + '\nfrom .memory import MemoryEvalCase, MemoryEvalResult, aggregate_memory_results, score_memory_case\n\n__all__ += ["MemoryEvalCase", "MemoryEvalResult", "aggregate_memory_results", "score_memory_case"]\n'
    write("src/eval/__init__.py", eval_init)

    root_init = read("src/__init__.py")
    if "MemoryService" not in root_init:
        root_init = root_init.replace("from .analytical_system import ProjectionEngine\n", "from .analytical_system import ProjectionEngine\nfrom .memory import MemoryConfig, MemoryQueryContext, MemoryService, MemoryStore, QueryPlan, QueryRoute\n")
        root_init = root_init.replace('    "ProjectionEngine",\n', '    "ProjectionEngine",\n    "MemoryConfig",\n    "MemoryQueryContext",\n    "MemoryService",\n    "MemoryStore",\n    "QueryPlan",\n    "QueryRoute",\n')
    write("src/__init__.py", root_init)

    ci = read(".github/workflows/ci.yml")
    if '      - "develop/**"' not in ci:
        ci = ci.replace('      - "release/**"\n', '      - "release/**"\n      - "develop/**"\n')
    if "memory.js" not in ci:
        ci = ci.replace("          node --check src/interface/web/static/js/stream.js\n", "          node --check src/interface/web/static/js/stream.js\n          node --check src/interface/web/static/js/memory.js\n")
    write(".github/workflows/ci.yml", ci)

    readme = read("README.md")
    marker = "## Arline v1.2 development branch"
    if marker not in readme:
        readme = readme.rstrip() + r'''

## Arline v1.2 development branch

The `develop/v1.2` branch introduces a **Memory Query Engine**, not an
unscoped "remember everything" feature. Library truth, accepted history,
source evidence, and recall remain separate. Every retrieval is compiled into
an explicit query plan and passes one shared Scope Gate for project, world,
branch, chat lineage, story time, viewpoint, trust, and scratch isolation.

### Recommended LM Studio models

Download models normally in LM Studio. Arline does not bundle or automatically
download model weights, and local LM Studio identifiers may differ from the
repository names below.

- **Generation / vision:**
  [HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive)
- **Recommended dense retrieval:**
  [intfloat/multilingual-e5-base](https://huggingface.co/intfloat/multilingual-e5-base)
- **Optional embedding challenger:**
  [Qwen/Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
- **Optional reranker experiment:**
  [Qwen/Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)

The reranker is disabled by default because LM Studio does not expose a native
rerank endpoint. Arline v1.2 starts with structured indexes, separate FTS5
domains, entity links, Scope Gate filtering, and Reciprocal Rank Fusion. Dense
retrieval through LM Studio is optional; when unavailable, the application
continues using structured lookup and FTS5.

### v1.2 alpha capabilities

- source-backed manuscript and chat chunks with provenance;
- incremental hash/revision-aware indexing and safe generations;
- deterministic query routes and explicit `QueryPlan` objects;
- current and historical state projections;
- linked spatial containment/placement graph;
- character knowledge and belief intervals;
- open story threads;
- separate manuscript/chat/summary/import FTS5 lanes;
- optional LM Studio embedding provider and RRF fusion;
- branch, chat-fork, scratch, trust, time, and viewpoint Scope Gate;
- retrieval traces showing selected and excluded candidates;
- automatic Context Stack evidence packing without canon writes;
- Developer Settings controls for lens, status, backfill, and query debugging.

No retrieved text, summary, model output, image description, or extracted
proposal can commit canon automatically. Review remains authoritative.
'''
    write("README.md", readme)


def add_integration_test() -> None:
    path = "tests/memory/test_app_integration.py"
    if (ROOT / path).exists():
        return
    write(path, r'''from __future__ import annotations

from pathlib import Path
import tempfile
import textwrap
import unittest

from fastapi.testclient import TestClient

from src.interface.web.app import create_app


class MemoryAppIntegrationTests(unittest.TestCase):
    def test_status_query_spatial_and_thread_endpoints(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); db=root/"arline.db"; cfg=root/"arline.toml"
            cfg.write_text(textwrap.dedent(f"""
            [lmstudio]
            base_url = "http://127.0.0.1:1234"
            model = ""
            api_key = ""
            timeout_seconds = 1.0
            auto_load = false
            [model_load]
            gpu_ratio = 1.0
            context_length = 32768
            flash_attention = false
            [generation]
            temperature = 0.8
            top_p = 0.95
            top_k = 40
            min_p = 0.0
            repeat_penalty = 1.05
            reasoning = "off"
            visible_output_tokens = 1024
            reasoning_reserve_tokens = 0
            generation_mode = "single"
            beat_count = 2
            beat_tokens = 512
            total_story_target_tokens = 1024
            seed = -1
            [generation.extra]
            [writer]
            input_mode = "smart_hybrid"
            system_prompt_file = "writer_system.txt"
            story_filename = "story.txt"
            save_request_packet = false
            post_validate = false
            [context_budget]
            safety_margin = 512
            minimum_writer_context_tokens = 512
            system_prompt_token_estimate = 256
            [reasoning_budget]
            max_depth = 2
            max_nodes = 50
            min_confidence = 0.3
            min_relevance = 0.2
            [projection]
            mode = "off"
            min_confidence = 0.5
            max_items = 4
            [reasoning_runtime]
            enforce_model_capabilities = false
            guard_prompt_file = "reasoning_guard.txt"
            dominance_ratio_warn = 2.0
            reasoning_share_warn = 0.65
            story_target_ratio_warn = 0.35
            [artifacts]
            output_root = "{(root/'output').as_posix()}"
            saved_root = "{(root/'saved').as_posix()}"
            [history]
            database_path = "{db.as_posix()}"
            dataset_root = "{(root/'datasets').as_posix()}"
            recent_limit = 100
            continuity_turns = 2
            continuity_chars = 12000
            smart_hybrid_continuity = true
            [workspace]
            database_path = "{db.as_posix()}"
            default_project_id = ""
            context_enabled = true
            mention_limit = 20
            pinned_context_limit = 24
            autosave_drafts = true
            language_mode = "follow_prompt"
            [memory]
            enabled = true
            fts_enabled = true
            dense_enabled = false
            automatic_context = true
            default_lens = "scene"
            [ui]
            host = "127.0.0.1"
            port = 7860
            show_reasoning = true
            """).strip()+"\n",encoding="utf-8")
            (root/"writer_system.txt").write_text("writer",encoding="utf-8")
            (root/"reasoning_guard.txt").write_text("guard",encoding="utf-8")
            client=TestClient(create_app(cfg))
            bootstrap=client.get("/api/workspace/bootstrap").json()
            world_id=bootstrap["world_bible"]["default_world_id"]
            branch_id=bootstrap["world_bible"]["default_branch_id"]
            status=client.get("/api/memory/status")
            self.assertEqual(status.status_code,200)
            self.assertTrue(status.json()["fts_available"])
            edge=client.post("/api/memory/spatial",json={
                "world_id":world_id,"branch_id":branch_id,
                "subject_type":"entity_family","subject_id":"APARTMENT",
                "relation":"contains","object_type":"entity_family","object_id":"BEDROOM",
            })
            self.assertEqual(edge.status_code,200,edge.text)
            graph=client.get("/api/memory/spatial/neighborhood",params={
                "world_id":world_id,"branch_id":branch_id,
                "resource_type":"entity_family","resource_id":"APARTMENT","depth":2,
            }).json()
            self.assertEqual(len(graph["edges"]),1)
            thread=client.post("/api/memory/threads",json={
                "world_id":world_id,"branch_id":branch_id,
                "thread_type":"promise","title":"Return the sword",
            })
            self.assertEqual(thread.status_code,200,thread.text)
            plan=client.post("/api/memory/plan",json={
                "query":"Where is the sword stored?","world_id":world_id,"branch_id":branch_id,
            }).json()
            self.assertEqual(plan["route"],"SPATIAL_LOOKUP")


if __name__ == "__main__":
    unittest.main()
''')


patch_workspace_context()
patch_app()
patch_config()
patch_frontend()
patch_metadata_docs_ci()
add_integration_test()
print("Applied Arline v1.2 memory/query foundation")
