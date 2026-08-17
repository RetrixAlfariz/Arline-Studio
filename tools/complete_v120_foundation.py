from __future__ import annotations

from pathlib import Path
import re
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# MemoryStore: source-revision lifecycle and inspection helpers.
# ---------------------------------------------------------------------------
store_path = "src/memory/store.py"
store = read(store_path)
old_stale = '''            con.execute(
                "UPDATE memory_chunks SET semantic_status='stale',index_state='stale',updated_at=? "
                "WHERE source_type=? AND source_id=? AND semantic_status='active'",
                (utc_now(), source_type, source_id),
            )
'''
if old_stale in store:
    store = store.replace(old_stale, "", 1)

anchor = '''    @staticmethod
    def _fts_query(query: str) -> str:
'''
helpers = dedent('''
    def mark_source_status(self, source_type: str, source_id: str, status: str = "stale") -> int:
        if status not in {"stale", "deleted", "deprecated", "superseded"}:
            raise ValueError(status)
        with self._lock, self.connection() as con:
            rows = con.execute(
                "SELECT id FROM memory_chunks WHERE source_type=? AND source_id=? AND semantic_status='active'",
                (source_type, source_id),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                con.execute(
                    "UPDATE memory_chunks SET semantic_status=?,index_state=?,updated_at=? "
                    "WHERE source_type=? AND source_id=? AND semantic_status='active'",
                    (status, status, utc_now(), source_type, source_id),
                )
                if self.fts_available:
                    domain = self._domain_for_source(source_type)
                    for chunk_id in ids:
                        con.execute(f"DELETE FROM memory_fts_{domain} WHERE chunk_id=?", (chunk_id,))
            return len(ids)

    def mark_session_status(self, session_id: str, status: str = "deleted") -> int:
        if status not in {"stale", "deleted", "deprecated", "superseded"}:
            raise ValueError(status)
        with self._lock, self.connection() as con:
            rows = con.execute(
                "SELECT id,source_type FROM memory_chunks WHERE session_id=? AND semantic_status='active'",
                (session_id,),
            ).fetchall()
            if not rows:
                return 0
            con.execute(
                "UPDATE memory_chunks SET semantic_status=?,index_state=?,updated_at=? "
                "WHERE session_id=? AND semantic_status='active'",
                (status, status, utc_now(), session_id),
            )
            if self.fts_available:
                for row in rows:
                    domain = self._domain_for_source(row["source_type"])
                    con.execute(f"DELETE FROM memory_fts_{domain} WHERE chunk_id=?", (row["id"],))
            return len(rows)

    def list_linked_chunks(self, resource_type: str, resource_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        with self.connection() as con:
            rows = con.execute(
                "SELECT DISTINCT c.id FROM memory_chunks c "
                "JOIN memory_links l ON l.memory_chunk_id=c.id "
                "WHERE l.resource_type=? AND l.resource_id=? AND c.semantic_status='active' "
                "ORDER BY c.updated_at DESC LIMIT ?",
                (resource_type, resource_id, max(1, min(1000, int(limit)))),
            ).fetchall()
        return [self.get_chunk(row["id"]) for row in rows]

''')
if "def mark_source_status(" not in store:
    store = replace_once(store, anchor, helpers + anchor, label="store helpers")

anchor_gen = '''    def active_generation(self) -> dict[str, Any] | None:
'''
gen_helper = dedent('''
    def list_generations(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connection() as con:
            rows = con.execute(
                "SELECT * FROM memory_index_generations ORDER BY generation_id DESC LIMIT ?",
                (max(1, min(200, int(limit))),),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["detail"] = loads(item.pop("detail_json"), {})
            result.append(item)
        return result

''')
if "def list_generations(" not in store:
    store = replace_once(store, anchor_gen, gen_helper + anchor_gen, label="generation list")
write(store_path, store)

# ---------------------------------------------------------------------------
# Indexer: supersede a source once per revision, never once per chunk.
# ---------------------------------------------------------------------------
index_path = "src/memory/index.py"
index = read(index_path)
old_doc = '''        chunks = self.chunker.chunk(body, source_id=source_id)
        catalog = catalog if catalog is not None else self._identity_catalog()
        rows=[]
'''
new_doc = '''        chunks = self.chunker.chunk(body, source_id=source_id)
        active_rows = self.store.list_chunks(source_type="document", source_id=source_id, status="active", limit=5000)
        if len(active_rows) == len(chunks) and active_rows and all(
            str(row.get("source_revision") or "").startswith(f"{revision}:") for row in active_rows
        ):
            return active_rows
        self.store.mark_source_status("document", source_id, "stale")
        catalog = catalog if catalog is not None else self._identity_catalog()
        rows=[]
'''
if old_doc in index:
    index = index.replace(old_doc, new_doc, 1)

old_turn = '''        revision = self._revision(turn.get("updated_at"), combined, feedback)
        catalog = catalog if catalog is not None else self._identity_catalog()
        rows=[]
        for unit in self.chunker.chunk(combined, source_id=turn["id"]):
'''
new_turn = '''        revision = self._revision(turn.get("updated_at"), combined, feedback)
        units = self.chunker.chunk(combined, source_id=turn["id"])
        active_rows = self.store.list_chunks(source_type="chat_window", source_id=turn["id"], status="active", limit=5000)
        if len(active_rows) == len(units) and active_rows and all(
            str(row.get("source_revision") or "").startswith(f"{revision}:") for row in active_rows
        ):
            return active_rows
        self.store.mark_source_status("chat_window", turn["id"], "stale")
        catalog = catalog if catalog is not None else self._identity_catalog()
        rows=[]
        for unit in units:
'''
if old_turn in index:
    index = index.replace(old_turn, new_turn, 1)
write(index_path, index)

# ---------------------------------------------------------------------------
# Query engine: hard Scope Gate BEFORE rank fusion.
# ---------------------------------------------------------------------------
query_path = "src/memory/query.py"
query = read(query_path)
old_execute = '''        lane_results = {lane: self._run_lane(lane, plan) for lane in lanes}
        raw = self._rrf(lane_results)
        allowed, excluded = self.gate.filter(raw, scope)
        selected = self._diversify(allowed, plan.final_candidate_budget)
'''
new_execute = '''        lane_results = {lane: self._run_lane(lane, plan) for lane in lanes}
        gated_lane_results: dict[RetrievalLane, list[MemoryCandidate]] = {}
        excluded: list[dict[str, Any]] = []
        for lane, candidates in lane_results.items():
            allowed, rejected = self.gate.filter(candidates, scope)
            gated_lane_results[lane] = allowed
            excluded.extend(rejected)
        raw = self._rrf(gated_lane_results)
        selected = self._diversify(raw, plan.final_candidate_budget)
'''
if old_execute in query:
    query = query.replace(old_execute, new_execute, 1)
write(query_path, query)

# ---------------------------------------------------------------------------
# MemoryService: incremental source refresh with lightweight debounce.
# ---------------------------------------------------------------------------
service_path = "src/memory/service.py"
service = read(service_path)
if "from threading import RLock, Timer" not in service:
    service = service.replace("from typing import Any\n", "from typing import Any\nfrom threading import RLock, Timer\n", 1)
old_init = '''        self.query_engine = MemoryQueryEngine(
            store=store, workspace=workspace, history=history, foundation=foundation,
            config=config, embedding=embedding, reranker=self.reranker,
        )
'''
new_init = old_init + '''        self._refresh_lock = RLock()
        self._refresh_timers: dict[str, Timer] = {}
'''
if "self._refresh_timers" not in service:
    service = replace_once(service, old_init, new_init, label="memory service init")

status_anchor = '''    def status(self) -> dict[str, Any]:
'''
methods = dedent('''
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

''')
if "def refresh_document(" not in service:
    service = replace_once(service, status_anchor, methods + status_anchor, label="memory refresh methods")
service = service.replace('"fallback_active": not embedding_available,', '"fallback_active": bool(self.config.dense_enabled and not embedding_available),')
write(service_path, service)

# ---------------------------------------------------------------------------
# Web app: instantiate MemoryService, expose router, and pack selected memory.
# ---------------------------------------------------------------------------
app_path = "src/interface/web/app.py"
app = read(app_path)
import_anchor = "from src.storage_backup import backup_sqlite_before_migrations\n"
imports = import_anchor + "from src.memory import MemoryConfig, MemoryQueryContext, MemoryService, MemoryStore\nfrom src.memory.web import create_memory_router\n"
if "from src.memory import MemoryConfig" not in app:
    app = replace_once(app, import_anchor, imports, label="app memory imports")

prompt_anchor = '''    context_recipe_id: str | None = None
    scratch_mode: bool = False
'''
prompt_new = '''    context_recipe_id: str | None = None
    context_lens: str | None = None
    world_time: Any = None
    story_order: float | None = None
    pov_variant_id: str | None = None
    scratch_mode: bool = False
'''
if "context_lens: str | None = None" not in app:
    app = replace_once(app, prompt_anchor, prompt_new, label="prompt memory scope")

init_anchor = '''    foundation = FoundationStore(initial_cfg.workspace.database_path)
    media_root = workspace_path.parent / "media"
'''
init_new = '''    foundation = FoundationStore(initial_cfg.workspace.database_path)
    memory_config = MemoryConfig.load(config_path)
    memory_store = MemoryStore(initial_cfg.workspace.database_path)
    memory_service = MemoryService(
        store=memory_store,
        workspace=workspace,
        history=history,
        foundation=foundation,
        config=memory_config,
        lmstudio_base_url=initial_cfg.lmstudio.base_url,
        lmstudio_api_key=initial_cfg.lmstudio.api_key,
    )
    media_root = workspace_path.parent / "media"
'''
if "memory_service = MemoryService(" not in app:
    app = replace_once(app, init_anchor, init_new, label="memory service bootstrap")

helper_anchor = '''    app = FastAPI(title="Arline Studio", version=STUDIO_VERSION)
'''
helper = dedent('''
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
        lens = str(payload.context_lens or memory_config.default_lens or "scene").lower()
        if lens not in {"author", "scene", "pov"}:
            lens = memory_config.default_lens if memory_config.default_lens in {"author", "scene", "pov"} else "scene"
        memory_scope = MemoryQueryContext(
            project_id=project_id,
            world_id=world_id,
            branch_id=branch_id,
            session_id=session_id,
            world_time=payload.world_time if payload.world_time is not None else (active_scene.get("narrative_time") or None),
            story_order=payload.story_order,
            pov_variant_id=payload.pov_variant_id or active_scene.get("pov_variant_id"),
            context_lens=lens,
            retrieval_mode="generation",
            explicit_references=refs,
            allow_scratch=bool(payload.scratch_mode),
            allow_future_author_knowledge=(lens == "author"),
        )
        try:
            result = memory_service.retrieve(prompt, memory_scope)
            return memory_service.augment_workspace_context(ws_context, result)
        except Exception as exc:
            ws_context.scope["memory"] = {
                "fallback": True,
                "error": str(exc),
                "reason": "Memory retrieval failed; v1.1 workspace context remained active.",
            }
            return ws_context

''')
if "def _augment_memory_context(" not in app:
    app = replace_once(app, helper_anchor, helper + helper_anchor, label="memory context helper")

mount_anchor = '''    app.mount("/static", StaticFiles(directory=static_dir), name="static")
'''
mount_new = mount_anchor + '''    app.include_router(create_memory_router(
        service=memory_service,
        store=memory_store,
        foundation=foundation,
    ))
'''
if "create_memory_router(" not in app.split(mount_anchor, 1)[1][:500]:
    app = replace_once(app, mount_anchor, mount_new, label="memory router")

if '"memory": MemoryConfig.load(cfg.path).to_dict(),' not in app:
    app = replace_once(
        app,
        '        "reasoning_guard": {\n',
        '        "memory": MemoryConfig.load(cfg.path).to_dict(),\n        "reasoning_guard": {\n',
        label="public memory config",
    )

analyze_anchor = '''            bundle = ArlineService(cfg).analyze(
'''
analyze_insert = '''            if ws_context is not None:
                ws_context = _augment_memory_context(
                    payload.prompt, payload, ws_context,
                    project_id=payload.project_id,
                    world_id=payload.world_id,
                    branch_id=payload.branch_id,
                    session_id=payload.session_id,
                    refs=refs,
                )
            bundle = ArlineService(cfg).analyze(
'''
if analyze_insert not in app:
    app = replace_once(app, analyze_anchor, analyze_insert, label="analyze memory")

stream_session_anchor = '''            session_context = ""
'''
stream_memory = '''            if ws_context is not None:
                ws_context = _augment_memory_context(
                    payload.prompt, payload, ws_context,
                    project_id=project_id,
                    world_id=world_id,
                    branch_id=branch_id,
                    session_id=(existing_session or {}).get("id"),
                    refs=refs,
                )
            session_context = ""
'''
if stream_memory not in app:
    app = replace_once(app, stream_session_anchor, stream_memory, label="stream memory")

normal_session_anchor = '''        session_context = ""
'''
normal_memory = '''        if ws_context is not None:
            ws_context = _augment_memory_context(
                payload.prompt, payload, ws_context,
                project_id=project_id,
                world_id=world_id,
                branch_id=branch_id,
                session_id=(existing_session or {}).get("id"),
                refs=refs,
            )
        session_context = ""
'''
if normal_memory not in app:
    app = replace_once(app, normal_session_anchor, normal_memory, label="normal generation memory")

# Completed turns become searchable shortly after persistence.
stream_done_anchor = '''                    final_session = history.get_session_meta(session["id"])
'''
if 'memory_service.schedule_turn_refresh(turn["id"])\n                    final_session' not in app:
    app = replace_once(
        app,
        stream_done_anchor,
        '                    memory_service.schedule_turn_refresh(turn["id"])\n' + stream_done_anchor,
        label="stream incremental indexing",
    )
normal_done_anchor = '''        session = history.get_session_meta(session["id"])
'''
if 'memory_service.schedule_turn_refresh(turn["id"])\n        session = history.get_session_meta' not in app:
    app = replace_once(
        app,
        normal_done_anchor,
        '        memory_service.schedule_turn_refresh(turn["id"])\n' + normal_done_anchor,
        label="normal incremental indexing",
    )

# Document write hooks.
create_doc_old = '''    @app.post("/api/documents")
    def create_document(payload: DocumentPayload):
        try:
            return workspace.create_document(**payload.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
'''
create_doc_new = '''    @app.post("/api/documents")
    def create_document(payload: DocumentPayload):
        try:
            document = workspace.create_document(**payload.model_dump())
            memory_service.schedule_document_refresh(document["id"])
            return document
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
'''
if create_doc_old in app:
    app = app.replace(create_doc_old, create_doc_new, 1)

patch_doc_old = '''        try:
            return workspace.update_document(document_id, note=note, **data)
        except KeyError as exc:
            raise HTTPException(404, "Document not found") from exc
'''
patch_doc_new = '''        try:
            document = workspace.update_document(document_id, note=note, **data)
            memory_service.schedule_document_refresh(document_id)
            return document
        except KeyError as exc:
            raise HTTPException(404, "Document not found") from exc
'''
if patch_doc_old in app:
    app = app.replace(patch_doc_old, patch_doc_new, 1)

delete_doc_old = '''        try:
            workspace.delete_document(document_id)
        except KeyError as exc:
            raise HTTPException(404, "Document not found") from exc
        return {"ok": True}
'''
delete_doc_new = '''        try:
            workspace.delete_document(document_id)
            memory_service.forget_document(document_id)
        except KeyError as exc:
            raise HTTPException(404, "Document not found") from exc
        return {"ok": True}
'''
if delete_doc_old in app:
    app = app.replace(delete_doc_old, delete_doc_new, 1)

# Chat lifecycle hooks.
delete_session_old = '''        try:
            history.delete_session(session_id)
        except KeyError as exc:
            raise HTTPException(404, "Session not found") from exc
        return {"ok": True}
'''
delete_session_new = '''        try:
            history.delete_session(session_id)
            memory_service.forget_session(session_id)
        except KeyError as exc:
            raise HTTPException(404, "Session not found") from exc
        return {"ok": True}
'''
if delete_session_old in app:
    app = app.replace(delete_session_old, delete_session_new, 1)

feedback_anchor = '''        return {"ok": True, "turn": turn, "dataset": history.dataset_stats()}
'''
if 'memory_service.schedule_turn_refresh(turn["id"])\n        return {"ok": True, "turn": turn' not in app:
    app = replace_once(
        app,
        feedback_anchor,
        '        memory_service.schedule_turn_refresh(turn["id"])\n' + feedback_anchor,
        label="feedback reindex",
    )

# Imported manuscript documents are indexed after the import transaction succeeds.
import_anchor = '''            foundation.update_job(job["id"], status="done", progress=1, message="Import complete", result={"document_ids": [x["id"] for x in created]})
            foundation.log_activity(payload.project_id, "manuscript_import", "project", payload.project_id, label=f"Imported {len(created)} manuscript items")
'''
import_new = '''            foundation.update_job(job["id"], status="done", progress=1, message="Import complete", result={"document_ids": [x["id"] for x in created]})
            for document in created:
                memory_service.schedule_document_refresh(document["id"])
            foundation.log_activity(payload.project_id, "manuscript_import", "project", payload.project_id, label=f"Imported {len(created)} manuscript items")
'''
if import_anchor in app:
    app = app.replace(import_anchor, import_new, 1)

write(app_path, app)

# ---------------------------------------------------------------------------
# Config + UI asset wiring.
# ---------------------------------------------------------------------------
config_path = "config/arline.toml"
config = read(config_path)
if "[memory]" not in config:
    config += dedent('''

    [memory]
    enabled = true
    fts_enabled = true
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
    # Install the recommended model in LM Studio normally, then set its local
    # model key here. Dense retrieval stays optional in v1.2.0.
    enabled = false
    provider = "lmstudio"
    model = "intfloat/multilingual-e5-base"
    dimension = 768
    query_prefix = "query: "
    passage_prefix = "passage: "
    batch_size = 32
    timeout_seconds = 120.0

    [memory.reranker]
    enabled = false
    provider = "disabled"
    model = "Qwen/Qwen3-Reranker-0.6B"
    top_k_input = 20
    top_k_output = 8
    ''')
write(config_path, config)

index_html_path = "src/interface/web/static/index.html"
html = read(index_html_path)
if "/static/js/memory.js" not in html:
    html = replace_once(
        html,
        '  <script src="/static/arline.js?v=1.1.3-media" defer></script>\n',
        '  <script src="/static/arline.js?v=1.2.0-memory" defer></script>\n  <script src="/static/js/memory.js?v=1.2.0-memory" defer></script>\n',
        label="memory frontend asset",
    )
    html = html.replace('/static/js/stream.js?v=1.1.3-media', '/static/js/stream.js?v=1.2.0-memory')
write(index_html_path, html)

# memory.js expects asynchronous backfill; teach it to poll jobs rather than
# displaying a queued job as if it were a completed index.
memory_js_path = "src/interface/web/static/js/memory.js"
memory_js = read(memory_js_path)
old_backfill = '''      const result = await request("/api/memory/backfill", {
        method: "POST",
        body: JSON.stringify({project_id: projectId}),
      });
      button.textContent = `Indexed ${result.chunks || 0} chunks`;
      await loadStatus();
'''
new_backfill = '''      const result = await request("/api/memory/backfill", {
        method: "POST",
        body: JSON.stringify({project_id: projectId, background: true}),
      });
      if (result.job?.id) {
        let job = result.job;
        while (!["done", "failed"].includes(job.status)) {
          await new Promise((resolve) => setTimeout(resolve, 350));
          job = await request(`/api/memory/jobs/${encodeURIComponent(job.id)}`);
          button.textContent = `${Math.round((job.progress || 0) * 100)}% · ${job.message || "Indexing"}`;
        }
        if (job.status === "failed") throw new Error(job.message || "Memory indexing failed");
        button.textContent = `Indexed ${job.result?.chunks || 0} chunks`;
      } else {
        button.textContent = `Indexed ${result.chunks || 0} chunks`;
      }
      await loadStatus();
'''
if old_backfill in memory_js:
    memory_js = memory_js.replace(old_backfill, new_backfill, 1)
write(memory_js_path, memory_js)

# ---------------------------------------------------------------------------
# Version, docs, README and permanent CI.
# ---------------------------------------------------------------------------
pyproject_path = "pyproject.toml"
pyproject = read(pyproject_path)
pyproject = re.sub(r'(?m)^version\s*=\s*"[^"]+"', 'version = "1.2.0a1"', pyproject, count=1)
write(pyproject_path, pyproject)

readme_path = "README.md"
readme = read(readme_path)
if "## v1.2 development — Evidence & Retrieval Foundation" not in readme:
    readme = dedent('''
    # Arline Studio

    ## v1.2 development — Evidence & Retrieval Foundation

    `develop/v1.2` contains the unmerged v1.2 development line. The v1.2.0
    milestone adds branch-aware evidence retrieval without turning search output
    into canon: source-backed chunks, SQLite FTS5, deterministic query routing,
    one hard Scope Gate, RRF fusion, retrieval traces, incremental indexing, and
    Context Stack integration. Dense embeddings are optional; structured lookup
    and FTS remain the baseline when LM Studio embeddings are unavailable.

    ### Recommended LM Studio models

    Arline does not bundle or download model weights. Install models in LM
    Studio normally and select the local model key in Settings/config.

    - **Generation + vision:** [HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive)
    - **Recommended embedding baseline:** [intfloat/multilingual-e5-base](https://huggingface.co/intfloat/multilingual-e5-base)
    - **Embedding challenger (disabled by default):** [Qwen/Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
    - **Experimental reranker (not required by v1.2.0):** [Qwen/Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)

    `multilingual-e5-base` should be exposed through LM Studio's embeddings
    endpoint when dense retrieval is enabled. v1.2.0 remains fully usable with
    `dense_enabled = false`.

    ---

    ''') + re.sub(r'^# Arline Studio 1\.1\s*\n', '', readme, count=1)
write(readme_path, readme)

write("docs/V12_IMPLEMENTATION_STATUS.md", dedent('''
# Arline v1.2 implementation status

**Development branch:** `develop/v1.2`  
**Package version:** `1.2.0a1`  
**Merge policy:** do not merge into `main` until the repository owner explicitly approves v1.2.

## v1.2.0 milestone — complete foundation

The v1.2.0 milestone is the Evidence & Retrieval Foundation. It deliberately
stops before temporal reconstruction, epistemic continuity, and summary/trust
productization planned for later v1.2.x milestones.

Implemented:

- source-backed MemoryStore with revision/checksum/provenance metadata;
- split SQLite FTS5 domains with structured/FTS fallback;
- optional LM Studio `multilingual-e5-base` embedding provider;
- deterministic Query Compiler and specialized retrieval lanes;
- hard Scope Gate applied before rank fusion;
- RRF fusion, authority boosts, source diversity and abstention;
- retrieval-run traces with admitted and excluded evidence;
- MemoryService wired into Analyze, streamed generation and normal generation;
- Context Stack receives selected memory as a separately labelled evidence block;
- generation continues with the v1.1 Workspace Context if retrieval fails;
- multi-chunk source revisions supersede atomically at the source level;
- document and completed-chat indexing hooks with debounced refresh;
- deleted document/session evidence is removed from automatic retrieval;
- full and Project-scoped backfill jobs with progress/status API;
- Developer Context panel for memory status, backfill and query debugging;
- README model recommendations; Arline does not download model weights;
- permanent CI covers the v1.2 memory modules and frontend assets.

## Explicit v1.2.0 boundary

Not required for this milestone: dense retrieval as a mandatory dependency,
reranking, full world-time interval reconstruction, POV knowledge continuity,
autonomous summaries, consequence simulation, or semantic branch merge. Those
remain later v1.2.x/v1.3 work according to the research specification.
'''))

ci_path = ".github/workflows/ci.yml"
ci = read(ci_path)
if '      - "develop/**"' not in ci:
    ci = ci.replace('      - "release/**"\n', '      - "release/**"\n      - "develop/**"\n')
for js in (
    "src/interface/web/static/js/memory.js",
    "src/interface/web/static/js/quick-create.js",
):
    line = f"          node --check {js}\n"
    if line not in ci:
        ci = ci.replace(
            "          node --check src/interface/web/static/js/stream.js\n",
            "          node --check src/interface/web/static/js/stream.js\n" + line,
            1,
        )
write(ci_path, ci)

# ---------------------------------------------------------------------------
# End-to-end tests: actual FastAPI + actual SQLite + no LM Studio required.
# ---------------------------------------------------------------------------
write("tests/test_v120_memory_foundation.py", dedent(r'''
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from src.interface.web.app import create_app


class V120MemoryFoundationTests(unittest.TestCase):
    def _app(self, root: Path) -> TestClient:
        db = root / "arline.db"
        cfg = root / "arline.toml"
        (root / "writer_system.txt").write_text("Write the requested fiction.", encoding="utf-8")
        (root / "reasoning_guard.txt").write_text("Keep reasoning bounded.", encoding="utf-8")
        config_text = f"""[lmstudio]
base_url = "http://127.0.0.1:1"
model = ""
api_key = ""
timeout_seconds = 0.2
auto_load = false

[history]
database_path = "{db.as_posix()}"
dataset_root = "{(root / 'datasets').as_posix()}"
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

[writer]
input_mode = "smart_hybrid"
system_prompt_file = "writer_system.txt"
story_filename = "story.txt"
save_request_packet = false
post_validate = false

[reasoning_runtime]
enforce_model_capabilities = false
guard_prompt_file = "reasoning_guard.txt"

[memory]
enabled = true
fts_enabled = true
dense_enabled = false
automatic_context = true
default_lens = "scene"
chunk_chars = 700
chunk_overlap_chars = 40
max_candidates = 40
final_k = 8
max_per_source = 3
rrf_k = 60
trace_enabled = true

[memory.embedding]
enabled = false
provider = "lmstudio"
model = "intfloat/multilingual-e5-base"
dimension = 768
query_prefix = "query: "
passage_prefix = "passage: "
"""
        cfg.write_text(config_text, encoding="utf-8")
        return TestClient(create_app(cfg))

    def test_memory_vertical_slice_and_scope_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = self._app(Path(td))
            bootstrap = client.get("/api/workspace/bootstrap").json()
            project = bootstrap["active"]["project"]
            world = bootstrap["active"]["world"]
            branch = bootstrap["active"]["branch"]

            phrase = "obsidian-lantern-seven"
            body = (f"Vian keeps the {phrase} on the bedroom desk. " * 90).strip()
            created = client.post("/api/documents", json={
                "project_id": project["id"], "world_id": world["id"],
                "branch_id": branch["id"], "title": "Memory fixture",
                "document_type": "scene", "content": body,
            })
            self.assertEqual(created.status_code, 200, created.text)
            document_id = created.json()["id"]

            refreshed = client.post("/api/memory/refresh", json={"document_id": document_id})
            self.assertEqual(refreshed.status_code, 200, refreshed.text)
            chunks = client.get(f"/api/memory/chunks?source_type=document&source_id={document_id}").json()["items"]
            self.assertGreater(len(chunks), 1, "multi-chunk documents must keep every current chunk active")

            # Re-indexing an unchanged revision must be idempotent.
            again = client.post("/api/memory/refresh", json={"document_id": document_id})
            self.assertEqual(again.status_code, 200, again.text)
            chunks_again = client.get(f"/api/memory/chunks?source_type=document&source_id={document_id}").json()["items"]
            self.assertEqual(len(chunks_again), len(chunks))

            second_project = client.post("/api/projects", json={"name": "Other Story"}).json()
            second_world = client.get(f"/api/projects/{second_project['id']}").json()["worlds"][0]
            hidden_doc = client.post("/api/documents", json={
                "project_id": second_project["id"], "world_id": second_world["id"],
                "title": "Wrong project", "document_type": "scene",
                "content": f"The {phrase} is secretly on Mars.",
            }).json()
            client.post("/api/memory/refresh", json={"document_id": hidden_doc["id"]})

            result = client.post("/api/memory/query", json={
                "query": phrase,
                "project_id": project["id"], "world_id": world["id"],
                "branch_id": branch["id"], "context_lens": "scene",
            })
            self.assertEqual(result.status_code, 200, result.text)
            payload = result.json()
            self.assertTrue(payload["selected"], payload)
            self.assertTrue(all(item.get("project_id") in {None, project["id"]} for item in payload["selected"]))
            self.assertTrue(any(item["decision"]["rule"] == "project" for item in payload["excluded"]), payload["excluded"])

            trace = client.get(f"/api/memory/retrieval/{payload['run_id']}")
            self.assertEqual(trace.status_code, 200, trace.text)

            status = client.get("/api/memory/status")
            self.assertEqual(status.status_code, 200, status.text)
            self.assertTrue(status.json()["fts_available"])

    def test_deleted_document_leaves_no_active_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = self._app(Path(td))
            bootstrap = client.get("/api/workspace/bootstrap").json()
            project = bootstrap["active"]["project"]
            world = bootstrap["active"]["world"]
            doc = client.post("/api/documents", json={
                "project_id": project["id"], "world_id": world["id"],
                "title": "Disposable", "content": "rare-delete-fixture", "document_type": "scene",
            }).json()
            client.post("/api/memory/refresh", json={"document_id": doc["id"]})
            self.assertTrue(client.get(f"/api/memory/chunks?source_type=document&source_id={doc['id']}").json()["items"])
            self.assertEqual(client.delete(f"/api/documents/{doc['id']}").status_code, 200)
            self.assertFalse(client.get(f"/api/memory/chunks?source_type=document&source_id={doc['id']}").json()["items"])


if __name__ == "__main__":
    unittest.main()
'''))

# ---------------------------------------------------------------------------
# Remove experimental applicators/workflows now that source is canonical.
# ---------------------------------------------------------------------------
for path in (ROOT / ".github" / "workflows").glob("*.yml"):
    if "v12" in path.name.lower() or "v1.2" in path.name.lower():
        path.unlink(missing_ok=True)
for path in (ROOT / "tools").glob("*.py"):
    name = path.name.lower()
    if "v12" in name or "v120" in name or "v1_2" in name or name.startswith("apply_v12"):
        path.unlink(missing_ok=True)
