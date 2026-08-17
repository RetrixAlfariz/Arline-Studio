from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Frontend: stable state/scope bridge. memory.js must never assume const state
# is a window property.
# ---------------------------------------------------------------------------
arline_path = "src/interface/web/static/arline.js"
arline = read(arline_path)
state_anchor = '''  conversationRenderLimit: 80,\n};\n'''
state_bridge = '''  conversationRenderLimit: 80,\n};\n\n// Public, read-only bridge for feature modules. Top-level `const state` is not\n// a Window property in browser scripts, so modules must use this interface\n// instead of reaching for window.state.\nwindow.ArlineRuntime = Object.freeze({\n  getState: () => state,\n  getScope: () => ({\n    projectId: state.activeProject?.id || null,\n    worldId: state.activeWorld?.id || null,\n    branchId: state.activeBranch?.id || null,\n    sessionId: state.activeSession?.id || null,\n    activeScene: state.activeScene || null,\n  }),\n});\n'''
if "window.ArlineRuntime = Object.freeze" not in arline:
    arline = replace_once(arline, state_anchor, state_bridge, "frontend runtime bridge")
write(arline_path, arline)

memory_js_path = "src/interface/web/static/js/memory.js"
memory_js = read(memory_js_path)
bridge_anchor = '''  window.ArlineMemory = memoryState;\n\n  async function request'''
bridge_insert = '''  window.ArlineMemory = memoryState;\n\n  function appState() {\n    return window.ArlineRuntime?.getState?.() || {};\n  }\n\n  function activeScope() {\n    const current = appState();\n    const scope = window.ArlineRuntime?.getScope?.() || {};\n    const activeDocumentId = current.activeScene?.document_id || null;\n    const sceneCard = (current.sceneCards || []).find((item) => item.document_id === activeDocumentId) || null;\n    return {\n      projectId: scope.projectId || null,\n      worldId: scope.worldId || null,\n      branchId: scope.branchId || null,\n      sessionId: scope.sessionId || null,\n      storyOrder: memoryState.storyOrder ?? sceneCard?.sort_order ?? current.activeDocument?.sort_order ?? null,\n      worldTime: memoryState.worldTime ?? current.activeScene?.narrative_time ?? sceneCard?.narrative_time ?? null,\n      povVariantId: memoryState.povVariantId ?? current.activeScene?.pov_variant_id ?? sceneCard?.pov_variant_id ?? null,\n    };\n  }\n\n  async function request'''
if "function activeScope()" not in memory_js:
    memory_js = replace_once(memory_js, bridge_anchor, bridge_insert, "memory frontend bridge")
memory_js = memory_js.replace(
    '      const projectId = window.state?.activeProject?.id || null;\n',
    '      const projectId = activeScope().projectId;\n      if (!projectId) throw new Error("Open a project before running scoped Memory backfill.");\n',
    1,
)
old_scope = '''  function currentScope(query) {\n    const projectId = window.state?.activeProject?.id || null;\n    const worldId = window.state?.activeWorld?.id || null;\n    const branchId = window.state?.activeBranch?.id || null;\n    const sessionId = window.state?.activeSession?.id || null;\n    const refs = typeof window.collectPromptReferences === "function" ? window.collectPromptReferences() : [];\n    return {\n      query,\n      project_id: projectId,\n      world_id: worldId,\n      branch_id: branchId,\n      session_id: sessionId,\n      context_lens: memoryState.lens,\n      story_order: memoryState.storyOrder,\n      world_time: memoryState.worldTime,\n      pov_variant_id: memoryState.povVariantId,\n      explicit_references: refs,\n    };\n  }\n'''
new_scope = '''  function currentScope(query) {\n    const scope = activeScope();\n    const refs = typeof window.collectPromptReferences === "function" ? window.collectPromptReferences() : [];\n    return {\n      query,\n      project_id: scope.projectId,\n      world_id: scope.worldId,\n      branch_id: scope.branchId,\n      session_id: scope.sessionId,\n      context_lens: memoryState.lens,\n      story_order: scope.storyOrder,\n      world_time: scope.worldTime,\n      pov_variant_id: scope.povVariantId,\n      explicit_references: refs,\n    };\n  }\n'''
if old_scope in memory_js:
    memory_js = memory_js.replace(old_scope, new_scope, 1)
old_resource = '''  async function openResourceMemory(familyId, variantId) {\n    const worldId = window.state?.activeWorld?.id;\n    const branchId = window.state?.activeBranch?.id;\n'''
new_resource = '''  async function openResourceMemory(familyId, variantId) {\n    const scope = activeScope();\n    const worldId = scope.worldId;\n    const branchId = scope.branchId;\n'''
if old_resource in memory_js:
    memory_js = memory_js.replace(old_resource, new_resource, 1)
export_anchor = '''  document.addEventListener("DOMContentLoaded", () => {\n'''
export_insert = '''  // Tiny executable surface used by the runtime smoke test and future feature\n  // modules. It deliberately returns a snapshot instead of exposing mutable state.\n  window.ArlineMemoryRuntime = Object.freeze({ currentScope, activeScope });\n\n  document.addEventListener("DOMContentLoaded", () => {\n'''
if "window.ArlineMemoryRuntime = Object.freeze" not in memory_js:
    memory_js = replace_once(memory_js, export_anchor, export_insert, "memory runtime test bridge")
if "window.state?." in memory_js:
    raise RuntimeError("memory.js still reaches through window.state")
write(memory_js_path, memory_js)


# ---------------------------------------------------------------------------
# Config/model contracts: explicit Memory packing budget and query allocation.
# ---------------------------------------------------------------------------
config_path = "src/memory/config.py"
config = read(config_path)
config = replace_once(
    config,
    '    trace_enabled: bool = True\n    embedding: EmbeddingConfig',
    '    trace_enabled: bool = True\n    max_pack_tokens: int = 4096\n    embedding: EmbeddingConfig',
    "memory config pack field",
)
config = replace_once(
    config,
    '            trace_enabled=bool(memory.get("trace_enabled", True)),\n            embedding=EmbeddingConfig(',
    '            trace_enabled=bool(memory.get("trace_enabled", True)),\n            max_pack_tokens=max(0, int(memory.get("max_pack_tokens", 4096))),\n            embedding=EmbeddingConfig(',
    "memory config pack load",
)
config = replace_once(
    config,
    '            "trace_enabled": self.trace_enabled,\n            "embedding": {',
    '            "trace_enabled": self.trace_enabled,\n            "max_pack_tokens": self.max_pack_tokens,\n            "embedding": {',
    "memory config pack dict",
)
write(config_path, config)

models_path = "src/memory/models.py"
models = read(models_path)
models = replace_once(
    models,
    '    allow_future_author_knowledge: bool = False\n\n    def __post_init__',
    '    allow_future_author_knowledge: bool = False\n    token_budget: int | None = None\n\n    def __post_init__',
    "query context token budget",
)
models = replace_once(
    models,
    '            "allow_future_author_knowledge": self.allow_future_author_knowledge,\n        }',
    '            "allow_future_author_knowledge": self.allow_future_author_knowledge,\n            "token_budget": self.token_budget,\n        }',
    "query context budget dict",
)
write(models_path, models)

config_toml_path = "config/arline.toml"
config_toml = read(config_toml_path)
if "max_pack_tokens =" not in config_toml:
    config_toml = replace_once(
        config_toml,
        "trace_enabled = true\n",
        "trace_enabled = true\n# Hard ceiling for evidence packed into one model context. The runtime may\n# allocate less when the Context Compiler has less headroom.\nmax_pack_tokens = 4096\n",
        "config toml pack budget",
    )
write(config_toml_path, config_toml)


# ---------------------------------------------------------------------------
# MemoryStore: source recorded time + transactional source-revision swap.
# ---------------------------------------------------------------------------
store_path = "src/memory/store.py"
store = read(store_path)
store = store.replace("MEMORY_SCHEMA_VERSION = 1", "MEMORY_SCHEMA_VERSION = 2", 1)
store = replace_once(
    store,
    "                    source_end_id TEXT,\n                    world_time_json TEXT,",
    "                    source_end_id TEXT,\n                    source_recorded_at TEXT,\n                    world_time_json TEXT,",
    "memory chunk recorded-at schema",
)
migrate_anchor = '''            try:\n                for domain in sorted(FTS_DOMAINS):\n'''
migrate_insert = '''            chunk_columns = {row[1] for row in con.execute("PRAGMA table_info(memory_chunks)").fetchall()}\n            if "source_recorded_at" not in chunk_columns:\n                con.execute("ALTER TABLE memory_chunks ADD COLUMN source_recorded_at TEXT")\n            try:\n                for domain in sorted(FTS_DOMAINS):\n'''
if "ALTER TABLE memory_chunks ADD COLUMN source_recorded_at" not in store:
    store = replace_once(store, migrate_anchor, migrate_insert, "memory schema migration")
store = replace_once(
    store,
    '                     session_id: str | None = None, source_start_id: str | None = None,\n                     source_end_id: str | None = None, world_time: Any = None,',
    '                     session_id: str | None = None, source_start_id: str | None = None,\n                     source_end_id: str | None = None, source_recorded_at: str | None = None, world_time: Any = None,',
    "upsert chunk recorded-at signature",
)
store = replace_once(
    store,
    '                "INSERT INTO memory_chunks(id,source_type,source_id,source_revision,project_id,world_id,branch_id,session_id,"\n                "source_start_id,source_end_id,world_time_json,story_order,scope_kind,semantic_class,authority,trust_level,text,"',
    '                "INSERT INTO memory_chunks(id,source_type,source_id,source_revision,project_id,world_id,branch_id,session_id,"\n                "source_start_id,source_end_id,source_recorded_at,world_time_json,story_order,scope_kind,semantic_class,authority,trust_level,text,"',
    "upsert chunk recorded-at columns",
)
store = replace_once(
    store,
    '                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,\'active\',\'ready\',?,?,?,?,?)",\n                (chunk_id, source_type, source_id, source_revision, project_id, world_id, branch_id, session_id,\n                 source_start_id, source_end_id, dumps(world_time) if world_time is not None else None, story_order,',
    '                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,\'active\',\'ready\',?,?,?,?,?)",\n                (chunk_id, source_type, source_id, source_revision, project_id, world_id, branch_id, session_id,\n                 source_start_id, source_end_id, source_recorded_at, dumps(world_time) if world_time is not None else None, story_order,',
    "upsert chunk recorded-at values",
)

replace_links_anchor = '''    def replace_links(self, chunk_id: str, links: Iterable[dict[str, Any]]) -> None:\n'''
transactional_method = dedent('''
    def replace_source_revision(
        self,
        *,
        source_type: str,
        source_id: str,
        prepared: list[dict[str, Any]],
        source_guard: dict[str, Any] | None = None,
        generation_id: int | None = None,
        embedding_model: str | None = None,
        vectors: list[list[float]] | None = None,
    ) -> list[dict[str, Any]]:
        """Atomically replace one derived source revision.

        New chunks, FTS rows, links, and optional vectors are staged inside the
        same SQLite transaction. The previous active revision is only marked
        stale immediately before COMMIT, so any failure leaves the old complete
        revision visible.
        """
        if vectors is not None and len(vectors) != len(prepared):
            raise ValueError("Vector count must match prepared chunk count")
        domain = self._domain_for_source(source_type)
        rows_out: list[dict[str, Any]] = []
        with self._lock, self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                if source_guard:
                    table = str(source_guard.get("table") or "")
                    if table not in {"workspace_documents", "turns"}:
                        raise ValueError("Unsupported memory source guard")
                    row = con.execute(
                        f"SELECT updated_at FROM {table} WHERE id=?",
                        (source_guard.get("id"),),
                    ).fetchone()
                    if row is None:
                        raise KeyError(source_guard.get("id"))
                    expected = source_guard.get("updated_at")
                    if expected is not None and str(row["updated_at"]) != str(expected):
                        raise RuntimeError("Source changed while Memory was indexing it")

                old_rows = con.execute(
                    "SELECT id FROM memory_chunks WHERE source_type=? AND source_id=? AND semantic_status='active'",
                    (source_type, source_id),
                ).fetchall()
                old_ids = [row["id"] for row in old_rows]
                new_ids: list[str] = []
                now = utc_now()
                for index, raw in enumerate(prepared):
                    clean = str(raw.get("text") or "").strip()
                    if not clean:
                        raise ValueError("Prepared memory chunk text cannot be empty")
                    chunk_id = make_id("MEM")
                    new_ids.append(chunk_id)
                    digest = checksum(clean)
                    con.execute(
                        "INSERT INTO memory_chunks(id,source_type,source_id,source_revision,project_id,world_id,branch_id,session_id,"
                        "source_start_id,source_end_id,source_recorded_at,world_time_json,story_order,scope_kind,semantic_class,authority,trust_level,text,"
                        "retrieval_text,display_excerpt,token_count,importance,extraction_confidence,identity_confidence,semantic_status,"
                        "index_state,checksum,chunker_version,index_generation,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active','ready',?,?,?,?,?)",
                        (
                            chunk_id, source_type, source_id, raw.get("source_revision"), raw.get("project_id"),
                            raw.get("world_id"), raw.get("branch_id"), raw.get("session_id"), raw.get("source_start_id"),
                            raw.get("source_end_id"), raw.get("source_recorded_at"),
                            dumps(raw.get("world_time")) if raw.get("world_time") is not None else None,
                            raw.get("story_order"), raw.get("scope_kind", "project"), raw.get("semantic_class", SemanticClass.EVIDENCE.value),
                            raw.get("authority", Authority.PROJECT_MANUSCRIPT.value), raw.get("trust_level", TrustLevel.TRUSTED_LOCAL.value),
                            clean, raw.get("retrieval_text") or clean, raw.get("display_excerpt") or clean[:500],
                            max(1, int(raw.get("token_count") or len(clean) // 4)), float(raw.get("importance", 0.5)),
                            float(raw.get("extraction_confidence", 1.0)), float(raw.get("identity_confidence", 1.0)),
                            digest, int(raw.get("chunker_version", 1)), generation_id, now, now,
                        ),
                    )
                    if self.fts_available:
                        con.execute(
                            f"INSERT INTO memory_fts_{domain}(chunk_id,text) VALUES(?,?)",
                            (chunk_id, raw.get("retrieval_text") or clean),
                        )
                    for link in raw.get("links") or []:
                        con.execute(
                            "INSERT OR IGNORE INTO memory_links(memory_chunk_id,resource_type,resource_id,relation,confidence,resolution_method) "
                            "VALUES(?,?,?,?,?,?)",
                            (chunk_id, link["resource_type"], link["resource_id"], link.get("relation", "mentions"),
                             float(link.get("confidence", 1.0)), link.get("resolution_method", "exact")),
                        )
                    if vectors is not None:
                        if generation_id is None or not embedding_model:
                            raise ValueError("Dense replacement requires generation_id and embedding_model")
                        blob, norm = self._vector_blob(vectors[index])
                        con.execute(
                            "INSERT INTO memory_vectors(memory_chunk_id,generation_id,model_id,dimension,vector_blob,norm,created_at) "
                            "VALUES(?,?,?,?,?,?,?)",
                            (chunk_id, generation_id, embedding_model, len(vectors[index]), blob, norm, now),
                        )

                if old_ids:
                    placeholders = ",".join("?" for _ in old_ids)
                    con.execute(
                        f"UPDATE memory_chunks SET semantic_status='stale',index_state='stale',updated_at=? WHERE id IN ({placeholders})",
                        [now, *old_ids],
                    )
                    if self.fts_available:
                        for chunk_id in old_ids:
                            con.execute(f"DELETE FROM memory_fts_{domain} WHERE chunk_id=?", (chunk_id,))
                if new_ids:
                    placeholders = ",".join("?" for _ in new_ids)
                    rows = con.execute(
                        f"SELECT * FROM memory_chunks WHERE id IN ({placeholders}) ORDER BY created_at,id",
                        new_ids,
                    ).fetchall()
                    rows_out = [self._chunk_row(row) for row in rows]
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        return rows_out

    def vector_coverage(self, generation_id: int, chunk_ids: Iterable[str]) -> dict[str, Any]:
        ids = list(dict.fromkeys(str(item) for item in chunk_ids if item))
        if not ids:
            return {"expected": 0, "covered": 0, "missing": []}
        placeholders = ",".join("?" for _ in ids)
        with self.connection() as con:
            rows = con.execute(
                f"SELECT memory_chunk_id FROM memory_vectors WHERE generation_id=? AND memory_chunk_id IN ({placeholders})",
                [generation_id, *ids],
            ).fetchall()
        covered = {row["memory_chunk_id"] for row in rows}
        missing = [chunk_id for chunk_id in ids if chunk_id not in covered]
        return {"expected": len(ids), "covered": len(covered), "missing": missing}

''')
if "def replace_source_revision(" not in store:
    store = replace_once(store, replace_links_anchor, transactional_method + replace_links_anchor, "atomic source replacement")
write(store_path, store)


# ---------------------------------------------------------------------------
# Indexer: production temporal metadata, dense generation coverage, and atomic
# replacement guarded against source update/delete races.
# ---------------------------------------------------------------------------
index_path = "src/memory/index.py"
write(index_path, dedent('''
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from .config import MemoryConfig
from .embedding import EmbeddingProvider
from .models import Authority, SemanticClass, TrustLevel
from .security import inspect_retrieved_text
from .store import MemoryStore


@dataclass(slots=True)
class ChunkUnit:
    text: str
    start_id: str
    end_id: str
    ordinal: int


class StructuralChunker:
    VERSION = 1

    def __init__(self, max_chars: int = 1800, overlap_chars: int = 180):
        self.max_chars = max(400, int(max_chars))
        self.overlap_chars = max(0, min(int(overlap_chars), self.max_chars // 3))

    def chunk(self, text: str, *, source_id: str) -> list[ChunkUnit]:
        normalized = text.replace("\\r\\n", "\\n").strip()
        if not normalized:
            return []
        blocks = [block.strip() for block in re.split(r"\\n\\s*\\n", normalized) if block.strip()] or [normalized]
        output: list[ChunkUnit] = []
        current: list[str] = []
        current_chars = 0

        def flush() -> None:
            nonlocal current, current_chars
            if not current:
                return
            body = "\\n\\n".join(current).strip()
            ordinal = len(output)
            output.append(ChunkUnit(body, f"{source_id}:block:{ordinal}", f"{source_id}:block:{ordinal}", ordinal))
            overlap = body[-self.overlap_chars:].strip() if self.overlap_chars else ""
            current = [overlap] if overlap else []
            current_chars = len(overlap)

        for block in blocks:
            sentences = re.split(r"(?<=[.!?])\\s+", block) if len(block) > self.max_chars else [block]
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                projected = current_chars + len(sentence) + (2 if current else 0)
                if current and projected > self.max_chars:
                    flush()
                current.append(sentence)
                current_chars += len(sentence) + (2 if len(current) > 1 else 0)
        flush()
        return output


class MemoryIndexer:
    def __init__(self, *, store: MemoryStore, workspace, history, foundation=None,
                 config: MemoryConfig | None = None, embedding: EmbeddingProvider | None = None):
        self.store = store
        self.workspace = workspace
        self.history = history
        self.foundation = foundation
        self.config = config or MemoryConfig()
        self.embedding = embedding
        self.chunker = StructuralChunker(self.config.chunk_chars, self.config.chunk_overlap_chars)

    @staticmethod
    def _revision(*parts: Any) -> str:
        return hashlib.sha256("|".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()[:24]

    def _identity_catalog(self) -> list[dict[str, Any]]:
        catalog: list[dict[str, Any]] = []
        try:
            families = self.workspace.list_entity_families(None)
        except Exception:
            families = []
        for family in families:
            catalog.append({"resource_type": "entity_family", "resource_id": family["id"], "label": family.get("name") or family["id"]})
        try:
            variants = self.workspace.list_variants()
        except Exception:
            variants = []
        for variant in variants:
            catalog.append({"resource_type": "entity_variant", "resource_id": variant["id"], "label": variant.get("display_name") or variant["id"]})
        if self.foundation is not None:
            for item in list(catalog):
                try:
                    aliases = self.foundation.list_aliases(item["resource_type"], item["resource_id"])
                except Exception:
                    aliases = []
                for alias in aliases:
                    catalog.append({**item, "label": alias.get("alias") or ""})
        return [item for item in catalog if item.get("label")]

    def _links(self, text: str, catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
        lower = text.casefold(); links=[]; seen=set()
        for item in sorted(catalog, key=lambda row: len(row["label"]), reverse=True):
            label = item["label"].strip()
            if len(label) < 2 or label.casefold() not in lower:
                continue
            key=(item["resource_type"], item["resource_id"])
            if key in seen:
                continue
            seen.add(key)
            links.append({"resource_type": key[0], "resource_id": key[1], "relation": "mentions", "confidence": 0.95, "resolution_method": "name_or_alias"})
        return links[:48]

    def _document_temporal(self, document: dict[str, Any]) -> tuple[float | None, Any]:
        scene_card = None
        try:
            scene_card = self.workspace.get_scene_card(document["id"])
        except Exception:
            scene_card = None
        story_order = (scene_card or {}).get("sort_order")
        if story_order is None:
            story_order = document.get("sort_order")
        world_time = (scene_card or {}).get("narrative_time") or None
        return (float(story_order) if story_order is not None else None, world_time)

    @staticmethod
    def _turn_scope(turn: dict[str, Any]) -> dict[str, Any]:
        scope = turn.get("workspace_scope")
        if isinstance(scope, dict):
            return scope
        raw = turn.get("workspace_scope_json")
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    def _turn_temporal(self, turn: dict[str, Any]) -> tuple[float | None, Any]:
        scope = self._turn_scope(turn)
        scene_card = scope.get("scene_card") or {}
        active_scene = scope.get("active_scene") or {}
        order = scene_card.get("sort_order")
        world_time = active_scene.get("narrative_time") or scene_card.get("narrative_time") or None
        return (float(order) if order is not None else None, world_time)

    def _same_source_database(self, owner: Any) -> bool:
        path = getattr(owner, "path", None)
        if path is None:
            return False
        try:
            return Path(path).resolve() == self.store.path.resolve()
        except Exception:
            return False

    def _vectors(self, rows: list[dict[str, Any]], generation_id: int | None) -> list[list[float]] | None:
        if not rows or generation_id is None or not self.config.dense_enabled:
            return None
        if self.embedding is None or not self.embedding.available():
            raise RuntimeError("Dense retrieval is enabled but the embedding provider is unavailable")
        texts = [row.get("retrieval_text") or row.get("text") or "" for row in rows]
        vectors = self.embedding.embed_passages(texts)
        if len(vectors) != len(rows):
            raise RuntimeError("Embedding provider returned incomplete vector coverage")
        return vectors

    def _ensure_generation_vectors(self, rows: list[dict[str, Any]], generation_id: int | None) -> None:
        if not rows or generation_id is None or not self.config.dense_enabled:
            return
        coverage = self.store.vector_coverage(generation_id, [row["id"] for row in rows])
        if not coverage["missing"]:
            return
        missing = set(coverage["missing"])
        subset = [row for row in rows if row["id"] in missing]
        vectors = self._vectors(subset, generation_id) or []
        for row, vector in zip(subset, vectors):
            self.store.upsert_vector(row["id"], generation_id, self.embedding.model_id, vector)

    def index_document(self, document: dict[str, Any], *, generation_id: int | None = None,
                       catalog: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        if not self.config.enabled:
            return []
        source_id = document["id"]
        revision = self._revision(document.get("updated_at"), document.get("title"), document.get("content"))
        title = str(document.get("title") or "Untitled")
        units = self.chunker.chunk(str(document.get("content") or ""), source_id=source_id)
        active_rows = self.store.list_chunks(source_type="document", source_id=source_id, status="active", limit=5000)
        if len(active_rows) == len(units) and active_rows and all(
            str(row.get("source_revision") or "").startswith(f"{revision}:") for row in active_rows
        ):
            self._ensure_generation_vectors(active_rows, generation_id)
            return active_rows

        catalog = catalog if catalog is not None else self._identity_catalog()
        story_order, world_time = self._document_temporal(document)
        prepared = []
        for unit in units:
            retrieval = f"Document: {title}\\nType: {document.get('document_type','scene')}\\n{unit.text}"
            prepared.append({
                "source_revision": f"{revision}:{unit.ordinal}", "text": unit.text, "retrieval_text": retrieval,
                "display_excerpt": unit.text[:700], "project_id": document.get("project_id"),
                "world_id": document.get("world_id"), "branch_id": document.get("branch_id"),
                "source_start_id": unit.start_id, "source_end_id": unit.end_id,
                "source_recorded_at": document.get("updated_at") or document.get("created_at"),
                "world_time": world_time, "story_order": story_order,
                "semantic_class": SemanticClass.EVIDENCE.value, "authority": Authority.PROJECT_MANUSCRIPT.value,
                "trust_level": TrustLevel.TRUSTED_LOCAL.value, "importance": 0.65,
                "chunker_version": self.chunker.VERSION, "links": self._links(unit.text, catalog),
            })
        vectors = self._vectors(prepared, generation_id)
        guard = {"table": "workspace_documents", "id": source_id, "updated_at": document.get("updated_at")} if self._same_source_database(self.workspace) else None
        if guard is None:
            current = self.workspace.get_document(source_id)
            if str(current.get("updated_at")) != str(document.get("updated_at")):
                raise RuntimeError("Document changed while Memory was indexing it")
        return self.store.replace_source_revision(
            source_type="document", source_id=source_id, prepared=prepared, source_guard=guard,
            generation_id=generation_id, embedding_model=self.embedding.model_id if vectors is not None else None,
            vectors=vectors,
        )

    def _iter_turns(self, project_id: str | None = None) -> list[dict[str, Any]]:
        path = getattr(self.history, "path", None)
        if path is None:
            return []
        con = sqlite3.connect(path, timeout=30); con.row_factory=sqlite3.Row
        try:
            where=""; params=[]
            if project_id:
                where="WHERE s.project_id=?"; params=[project_id]
            rows = con.execute(
                "SELECT t.*,s.project_id,s.world_id,s.branch_id,s.scratch_mode,s.parent_session_id,s.forked_from_turn_id "
                "FROM turns t JOIN sessions s ON s.id=t.session_id " + where + " ORDER BY t.created_at,t.rowid", params
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            con.close()

    def index_turn(self, turn: dict[str, Any], *, generation_id: int | None = None,
                   catalog: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        if not self.config.enabled:
            return []
        scratch = bool(turn.get("scratch_mode")); feedback = turn.get("feedback_status") or "unreviewed"
        semantic = SemanticClass.EXPLORATORY.value
        authority = Authority.SCRATCH.value if scratch else Authority.CHAT_EXPLORATION.value
        if feedback in {"accepted", "edited_accept"}:
            semantic = SemanticClass.DECISION.value
            authority = Authority.ACCEPTED_GENERATED_OUTPUT.value
        combined = f"USER:\\n{turn.get('user_prompt') or ''}\\n\\nASSISTANT:\\n{turn.get('edited_story') if feedback == 'edited_accept' and turn.get('edited_story') else turn.get('story') or ''}".strip()
        if not combined:
            return []
        report = inspect_retrieved_text(combined, trust_level=TrustLevel.GENERATED.value)
        revision = self._revision(turn.get("updated_at"), combined, feedback)
        units = self.chunker.chunk(combined, source_id=turn["id"])
        active_rows = self.store.list_chunks(source_type="chat_window", source_id=turn["id"], status="active", limit=5000)
        if len(active_rows) == len(units) and active_rows and all(
            str(row.get("source_revision") or "").startswith(f"{revision}:") for row in active_rows
        ):
            self._ensure_generation_vectors(active_rows, generation_id)
            return active_rows

        catalog = catalog if catalog is not None else self._identity_catalog()
        story_order, world_time = self._turn_temporal(turn)
        prepared = []
        for unit in units:
            prepared.append({
                "source_revision": f"{revision}:{unit.ordinal}", "text": unit.text, "retrieval_text": unit.text,
                "display_excerpt": unit.text[:700], "project_id": turn.get("project_id"), "world_id": turn.get("world_id"),
                "branch_id": turn.get("branch_id"), "session_id": turn.get("session_id"),
                "source_start_id": unit.start_id, "source_end_id": unit.end_id,
                "source_recorded_at": turn.get("updated_at") or turn.get("created_at"),
                "world_time": world_time, "story_order": story_order,
                "semantic_class": semantic, "authority": authority, "trust_level": report.trust_level,
                "importance": 0.75 if feedback in {"accepted", "edited_accept"} else 0.4,
                "chunker_version": self.chunker.VERSION, "links": self._links(unit.text, catalog),
            })
        vectors = self._vectors(prepared, generation_id)
        guard = {"table": "turns", "id": turn["id"], "updated_at": turn.get("updated_at")} if self._same_source_database(self.history) else None
        if guard is None:
            current = self.history.get_turn(turn["id"])
            if str(current.get("updated_at")) != str(turn.get("updated_at")):
                raise RuntimeError("Chat turn changed while Memory was indexing it")
        return self.store.replace_source_revision(
            source_type="chat_window", source_id=turn["id"], prepared=prepared, source_guard=guard,
            generation_id=generation_id, embedding_model=self.embedding.model_id if vectors is not None else None,
            vectors=vectors,
        )

    def backfill(self, project_id: str | None = None) -> dict[str, Any]:
        if not self.config.enabled:
            return {"disabled": True, "documents": 0, "turns": 0, "chunks": 0}
        # Dense generations are global derived snapshots. Activating a generation
        # that only covers one project would make every other project disappear
        # from vector search, so a dense rebuild always covers the whole store.
        effective_project_id = None if self.config.dense_enabled else project_id
        generation = self.store.create_generation(
            provider=("lmstudio" if self.config.dense_enabled and not self.config.fts_enabled else
                      "fts5+lmstudio" if self.config.dense_enabled else "fts5"),
            embedding_model=self.embedding.model_id if self.embedding and self.config.dense_enabled else None,
            dimension=self.embedding.dimension if self.embedding and self.config.dense_enabled else None,
            chunker_version=self.chunker.VERSION,
            detail={"requested_project_id": project_id, "effective_project_id": effective_project_id},
        )
        generation_id = generation["generation_id"]
        catalog = self._identity_catalog()
        expected_ids: list[str] = []
        document_count = turn_count = 0
        try:
            if self.config.dense_enabled and (self.embedding is None or not self.embedding.available()):
                raise RuntimeError("Dense backfill requested but embedding provider is unavailable")
            projects = [self.workspace.get_project(effective_project_id)] if effective_project_id else self.workspace.list_projects()
            for project in projects:
                if project.get("id") == "PROJ-WORLD-BIBLE":
                    continue
                for document in self.workspace.list_documents(project["id"]):
                    rows = self.index_document(document, generation_id=generation_id, catalog=catalog)
                    document_count += 1
                    expected_ids.extend(row["id"] for row in rows)
            for turn in self._iter_turns(effective_project_id):
                rows = self.index_turn(turn, generation_id=generation_id, catalog=catalog)
                turn_count += 1
                expected_ids.extend(row["id"] for row in rows)
            coverage = self.store.vector_coverage(generation_id, expected_ids) if self.config.dense_enabled else {"expected": 0, "covered": 0, "missing": []}
            if coverage["missing"]:
                raise RuntimeError(f"Dense generation is incomplete: {len(coverage['missing'])} chunks lack vectors")
            self.store.set_generation_status(generation_id, "verified")
            self.store.set_generation_status(generation_id, "active")
        except Exception:
            self.store.set_generation_status(generation_id, "failed")
            raise
        return {
            "generation_id": generation_id, "documents": document_count, "turns": turn_count,
            "chunks": len(expected_ids), "dense_requested": self.config.dense_enabled,
            "dense_model": self.embedding.model_id if self.embedding else None,
            "dense_scope": "global" if self.config.dense_enabled else (project_id or "global"),
            "vector_coverage": coverage,
        }
'''))


# ---------------------------------------------------------------------------
# ScopeGate: session fork cutoffs + branch recorded-time cutoffs + story order.
# ---------------------------------------------------------------------------
scope_path = "src/memory/scope.py"
write(scope_path, dedent('''
from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import ContextLens, MemoryCandidate, MemoryQueryContext, ScopeDecision, SemanticStatus
from .security import inspect_retrieved_text


class ScopeGate:
    """One authoritative gate used by every retrieval lane."""

    def __init__(self, workspace, history=None):
        self.workspace = workspace
        self.history = history
        self._turn_cutoff_cache: dict[tuple[str, str], set[str]] = {}

    def branch_cutoffs(self, branch_id: str | None) -> dict[str | None, str | None]:
        visible: dict[str | None, str | None] = {None: None}
        current = branch_id
        running_cutoff: str | None = None
        guard = 0
        while current and guard < 128:
            if current in visible:
                break
            visible[current] = running_cutoff
            try:
                branch = self.workspace.get_branch(current)
            except KeyError:
                break
            created = branch.get("created_at")
            if created and (running_cutoff is None or str(created) < str(running_cutoff)):
                running_cutoff = str(created)
            current = branch.get("parent_branch_id")
            guard += 1
        return visible

    def session_cutoffs(self, session_id: str | None) -> dict[str | None, str | None]:
        visible: dict[str | None, str | None] = {None: None}
        if not session_id or self.history is None:
            return visible
        current = session_id
        guard = 0
        while current and guard < 256:
            if current in visible:
                break
            try:
                meta = self.history.get_session_meta(current)
            except KeyError:
                break
            visible[current] = None if current == session_id else visible.get(current)
            parent = meta.get("parent_session_id")
            if parent:
                visible[parent] = meta.get("forked_from_turn_id")
            current = parent
            guard += 1
        return visible

    def _turn_ids_through(self, session_id: str, cutoff_turn_id: str) -> set[str]:
        key = (session_id, cutoff_turn_id)
        cached = self._turn_cutoff_cache.get(key)
        if cached is not None:
            return cached
        allowed: set[str] = set()
        try:
            turns = self.history.get_session(session_id).get("turns", [])
        except Exception:
            turns = []
        for turn in turns:
            allowed.add(turn["id"])
            if turn["id"] == cutoff_turn_id:
                self._turn_cutoff_cache[key] = allowed
                return allowed
        self._turn_cutoff_cache[key] = set()
        return set()

    @staticmethod
    def _recorded_at(candidate: MemoryCandidate) -> str | None:
        direct = candidate.metadata.get("source_recorded_at")
        if direct:
            return str(direct)
        for key in ("event", "spatial_edge", "thread", "interval", "epistemic"):
            payload = candidate.metadata.get(key)
            if isinstance(payload, dict):
                value = payload.get("updated_at") or payload.get("created_at")
                if value:
                    return str(value)
        return None

    @staticmethod
    def _after(value: str, cutoff: str) -> bool:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")) > datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
        except ValueError:
            return value > cutoff

    @staticmethod
    def _explicitly_allowed(candidate: MemoryCandidate, context: MemoryQueryContext) -> bool:
        return any(
            item.get("source_type") == candidate.source_type and item.get("source_id") == candidate.source_id
            for item in context.explicit_cross_scope_sources
        )

    def evaluate(self, candidate: MemoryCandidate, context: MemoryQueryContext) -> ScopeDecision:
        explicit = self._explicitly_allowed(candidate, context)
        if candidate.semantic_status != SemanticStatus.ACTIVE.value:
            return ScopeDecision(False, f"semantic status is {candidate.semantic_status}", "semantic_status")
        hygiene = inspect_retrieved_text(candidate.text, trust_level=candidate.trust_level)
        if not hygiene.safe_for_automatic_context and not explicit:
            return ScopeDecision(False, ", ".join(hygiene.flags) or "source is quarantined", "trust")
        if candidate.authority == "scratch" and not context.allow_scratch and not explicit:
            return ScopeDecision(False, "scratch evidence is disabled", "scratch")
        if candidate.project_id and context.project_id and candidate.project_id != context.project_id and not explicit:
            return ScopeDecision(False, "different project", "project")
        if candidate.world_id and context.world_id and candidate.world_id != context.world_id and not explicit:
            return ScopeDecision(False, "different world", "world")

        branches = self.branch_cutoffs(context.branch_id)
        if candidate.branch_id not in branches and not explicit:
            return ScopeDecision(False, "sibling/descendant branch is not visible", "branch")
        branch_cutoff = branches.get(candidate.branch_id)
        if candidate.branch_id is not None and branch_cutoff and not explicit:
            recorded_at = self._recorded_at(candidate)
            if recorded_at is None:
                return ScopeDecision(False, "ancestor-branch evidence has no fork-cutoff timestamp", "branch_cutoff_unknown")
            if self._after(recorded_at, branch_cutoff):
                return ScopeDecision(False, "ancestor-branch evidence was recorded after this branch forked", "branch_cutoff")

        sessions = self.session_cutoffs(context.session_id)
        if candidate.session_id not in sessions and not explicit:
            return ScopeDecision(False, "sibling/later chat fork is not visible", "session")
        session_cutoff = sessions.get(candidate.session_id)
        if candidate.session_id is not None and session_cutoff and not explicit:
            if candidate.source_type not in {"chat_window", "turn"}:
                return ScopeDecision(False, "ancestor-chat evidence cannot be bounded to the fork point", "session_cutoff_unknown")
            allowed_turns = self._turn_ids_through(candidate.session_id, session_cutoff)
            if candidate.source_id not in allowed_turns:
                return ScopeDecision(False, "parent-chat turn was written after the child fork point", "session_cutoff")

        if context.story_order is not None and candidate.story_order is not None and candidate.story_order > context.story_order:
            if not (context.context_lens == ContextLens.AUTHOR and context.allow_future_author_knowledge) and not explicit:
                return ScopeDecision(False, "future story-order evidence blocked by active lens", "story_order")
        if context.context_lens == ContextLens.POV and candidate.metadata.get("author_only") and not explicit:
            return ScopeDecision(False, "author-only evidence blocked by POV lens", "pov")
        if explicit:
            candidate.metadata["cross_scope_evidence"] = True
            return ScopeDecision(True, "explicit cross-scope comparison evidence", "explicit_override")
        return ScopeDecision(True, "visible in current scope", "allowed")

    def filter(self, candidates: list[MemoryCandidate], context: MemoryQueryContext) -> tuple[list[MemoryCandidate], list[dict[str, Any]]]:
        allowed: list[MemoryCandidate] = []
        excluded: list[dict[str, Any]] = []
        for candidate in candidates:
            decision = self.evaluate(candidate, context)
            if decision.allowed:
                allowed.append(candidate)
            else:
                excluded.append({"candidate": candidate.to_dict(), "decision": decision.to_dict()})
        return allowed, excluded
'''))


# ---------------------------------------------------------------------------
# Query compiler: intent-safe routing, real config switches, required-lane
# semantics, trace switch, and Memory-internal token packing budget.
# ---------------------------------------------------------------------------
query_path = "src/memory/query.py"
query = read(query_path)
start = query.index("    ROUTE_PATTERNS:")
end = query.index("\n\n    def __init__", start)
route_block = '''    STORY_CONTINUE_PATTERN = re.compile(\n        r"^\\s*(?:please\\s+)?(?:continue|write|lanjut(?:kan)?|tulis(?:kan)?)\\b|"\n        r"\\bcontinue\\s+(?:the\\s+)?(?:current\\s+)?(?:scene|dialogue)\\b|"\n        r"\\b(?:write|tulis(?:kan)?)\\s+(?:the\\s+)?(?:next|current)?\\s*(?:scene|adegan|dialogue)\\b",\n        re.I,\n    )\n    ROUTE_PATTERNS: list[tuple[QueryRoute, re.Pattern[str]]] = [\n        (QueryRoute.EPISTEMIC_STATE, re.compile(r"\\b(know|knew|believe|believed|suspect|aware|secret|tahu|percaya|curiga)\\b", re.I)),\n        (QueryRoute.TEMPORAL_STATE, re.compile(r"\\b(before|after|at the time|used to|previously|historical|sebelum|setelah|saat itu|dulu)\\b", re.I)),\n        (QueryRoute.BRANCH_COMPARE, re.compile(r"\\b(compare branches?|alternate timeline|what-if|bandingkan cabang|timeline alternatif)\\b", re.I)),\n        (QueryRoute.CONTINUITY_CHECK, re.compile(r"\\b(continuity|contradiction|inconsistent|conflict|kontinuitas|kontradiksi|tidak konsisten)\\b", re.I)),\n        (QueryRoute.GLOBAL_SUMMARY, re.compile(r"\\b(summar(?:y|ize)|overview|across the chapter|recap|ringkas|rangkuman)\\b", re.I)),\n        (QueryRoute.SPATIAL_LOOKUP, re.compile(r"\\b(where|inside|contains?|room|stored|located|near|adjacent|happen(?:ed)?\\s+where|di mana|ruang|berisi|tersimpan)\\b", re.I)),\n        (QueryRoute.THREAD_LOOKUP, re.compile(r"\\b(unresolved|promise|mystery|goal|foreshadow|thread|belum selesai|janji|misteri|tujuan)\\b", re.I)),\n        (QueryRoute.WHY_CAUSAL, re.compile(r"\\b(why|cause|caused|because|motivated|mengapa|kenapa|sebab)\\b", re.I)),\n        (QueryRoute.EVENT_LOOKUP, re.compile(r"\\b(when|what happened|event|changed|happened|kapan|terjadi|peristiwa|berubah)\\b", re.I)),\n        (QueryRoute.CURRENT_STATE, re.compile(r"\\b(current|currently|now|status|sekarang|punya|milik)\\b", re.I)),\n    ]'''
query = query[:start] + route_block + query[end:]
old_route = '''    @classmethod\n    def route(cls, query: str) -> QueryRoute:\n        stripped = query.strip()\n        for route, pattern in cls.ROUTE_PATTERNS:\n            if pattern.search(stripped):\n                return route\n        if re.search(r"\\b(continue|write|scene|dialogue|lanjut|tulis|adegan)\\b", stripped, re.I):\n            return QueryRoute.STORY_CONTINUE\n        return QueryRoute.TEXT_RECALL\n'''
new_route = '''    @classmethod\n    def route(cls, query: str) -> QueryRoute:\n        stripped = query.strip()\n        for route, pattern in cls.ROUTE_PATTERNS:\n            if pattern.search(stripped):\n                return route\n        if cls.STORY_CONTINUE_PATTERN.search(stripped):\n            return QueryRoute.STORY_CONTINUE\n        return QueryRoute.TEXT_RECALL\n'''
query = replace_once(query, old_route, new_route, "query intent routing")
# Story continuation uses all available evidence but has no single hard-required
# lane; deterministic factual routes keep their required-lane semantics.
query = query.replace(
    '            QueryRoute.STORY_CONTINUE: ([RetrievalLane.STRUCTURED_STATE], [RetrievalLane.EVENTS, RetrievalLane.THREADS, RetrievalLane.FTS_MANUSCRIPT, RetrievalLane.FTS_CHAT, RetrievalLane.DENSE]),',
    '            QueryRoute.STORY_CONTINUE: ([], [RetrievalLane.STRUCTURED_STATE, RetrievalLane.EVENTS, RetrievalLane.THREADS, RetrievalLane.FTS_MANUSCRIPT, RetrievalLane.FTS_CHAT, RetrievalLane.DENSE]),',
    1,
)
query = query.replace(
    '            QueryRoute.TEXT_RECALL: ([RetrievalLane.FTS_MANUSCRIPT], [RetrievalLane.FTS_CHAT, RetrievalLane.FTS_SUMMARY, RetrievalLane.FTS_IMPORT, RetrievalLane.DENSE]),',
    '            QueryRoute.TEXT_RECALL: ([], [RetrievalLane.FTS_MANUSCRIPT, RetrievalLane.FTS_CHAT, RetrievalLane.FTS_SUMMARY, RetrievalLane.FTS_IMPORT, RetrievalLane.DENSE]),',
    1,
)
compile_anchor = '''        required, optional = policies[route]\n        if not self.config.dense_enabled:\n            optional = [lane for lane in optional if lane != RetrievalLane.DENSE]\n'''
compile_new = '''        required, optional = policies[route]\n        fts_lanes = {RetrievalLane.FTS_MANUSCRIPT, RetrievalLane.FTS_CHAT, RetrievalLane.FTS_SUMMARY, RetrievalLane.FTS_IMPORT}\n        if not self.config.fts_enabled:\n            required = [lane for lane in required if lane not in fts_lanes]\n            optional = [lane for lane in optional if lane not in fts_lanes]\n        if not self.config.dense_enabled:\n            required = [lane for lane in required if lane != RetrievalLane.DENSE]\n            optional = [lane for lane in optional if lane != RetrievalLane.DENSE]\n'''
query = replace_once(query, compile_anchor, compile_new, "query config lanes")
query = replace_once(
    query,
    '            normalized_query=" ".join(query.split()),\n        )',
    '            trace=self.config.trace_enabled,\n            normalized_query=" ".join(query.split()),\n        )',
    "query trace plan",
)
query = replace_once(
    query,
    '            metadata={"domain": row.get("domain"), "snippet": row.get("snippet"), "checksum": row.get("checksum")},',
    '            metadata={"domain": row.get("domain"), "snippet": row.get("snippet"), "checksum": row.get("checksum"), "source_recorded_at": row.get("source_recorded_at")},',
    "chunk candidate recorded-at",
)
query = replace_once(
    query,
    '                metadata={"event": event},\n',
    '                metadata={"event": event, "source_recorded_at": event.get("updated_at") or event.get("created_at")},\n',
    "event candidate recorded-at",
)
query = replace_once(
    query,
    '    def _fts(self, query: str, lane: RetrievalLane, budget: int) -> list[MemoryCandidate]:\n        domain = {',
    '    def _fts(self, query: str, lane: RetrievalLane, budget: int) -> list[MemoryCandidate]:\n        if not self.config.fts_enabled:\n            return []\n        domain = {',
    "fts runtime switch",
)
fit_anchor = '''    @staticmethod\n    def _pack(plan: QueryPlan, selected: list[MemoryCandidate], excluded: list[dict[str, Any]]) -> str:\n'''
fit_method = '''    @staticmethod\n    def _fit_token_budget(candidates: list[MemoryCandidate], token_budget: int | None) -> list[MemoryCandidate]:\n        if token_budget is None:\n            return candidates\n        remaining = max(0, int(token_budget) - 48)  # Memory header/section overhead.\n        if remaining <= 0:\n            return []\n        fitted: list[MemoryCandidate] = []\n        for item in candidates:\n            cost = max(16, len(item.text) // 4 + 20)\n            if cost <= remaining:\n                fitted.append(item)\n                remaining -= cost\n                continue\n            if not fitted and remaining > 36:\n                item.text = item.text[: max(40, (remaining - 20) * 4)].rstrip() + "…"\n                fitted.append(item)\n            break\n        return fitted\n\n'''
if "def _fit_token_budget" not in query:
    query = replace_once(query, fit_anchor, fit_method + fit_anchor, "memory packing budget")
old_execute_tail = '''        raw = self._rrf(gated_lane_results)\n        selected = self._diversify(raw, plan.final_candidate_budget)\n        if self.reranker.available() and len(selected) > 1:\n            payloads = [item.to_dict() for item in selected]\n            reranked = self.reranker.rerank(query, payloads, plan.final_candidate_budget)\n            order = {item["id"]: i for i, item in enumerate(reranked)}\n            selected.sort(key=lambda item: order.get(item.id, 10_000))\n        diagnostics = []\n        if self.config.dense_enabled and RetrievalLane.DENSE in lanes and not lane_results.get(RetrievalLane.DENSE):\n            diagnostics.append("Dense retrieval unavailable; structured lookup and FTS remained active.")\n        required_count = sum(len(lane_results.get(lane) or []) for lane in plan.required_lanes)\n        abstain = not selected and plan.require_abstention\n        reason = "No allowed evidence was found in the active scope." if abstain else ""\n        run_id = make_id("RETRIEVE")\n        result = RetrievalResult(run_id, plan, selected, excluded, self._pack(plan, selected, excluded),\n                                 {lane.value: len(items) for lane, items in lane_results.items()}, abstain, reason, diagnostics)\n        self.store.record_retrieval_run(\n            run_id=run_id, query_text=query, route=plan.route.value, scope=scope.to_dict(), plan=plan.to_dict(),\n            selected=[item.to_dict() for item in selected], excluded=excluded, diagnostics=diagnostics,\n            latency_ms=(time.perf_counter() - started) * 1000,\n        )\n        return result\n'''
new_execute_tail = '''        raw = self._rrf(gated_lane_results)\n        selected = self._diversify(raw, plan.final_candidate_budget)\n        if self.config.reranker.enabled and self.reranker.available() and len(selected) > 1:\n            payloads = [item.to_dict() for item in selected]\n            reranked = self.reranker.rerank(query, payloads, plan.final_candidate_budget)\n            order = {item["id"]: i for i, item in enumerate(reranked)}\n            selected.sort(key=lambda item: order.get(item.id, 10_000))\n        diagnostics = []\n        if self.config.dense_enabled and RetrievalLane.DENSE in lanes and not gated_lane_results.get(RetrievalLane.DENSE):\n            diagnostics.append("Dense retrieval unavailable; other enabled lanes remained active.")\n        missing_required = [lane for lane in plan.required_lanes if not gated_lane_results.get(lane)]\n        if missing_required:\n            diagnostics.append("Required evidence lane(s) empty after Scope Gate: " + ", ".join(lane.value for lane in missing_required))\n            if plan.require_abstention:\n                selected = []\n        selected = self._fit_token_budget(selected, scope.token_budget)\n        abstain = bool(plan.require_abstention and (missing_required or not selected))\n        if missing_required:\n            reason = "Required structured evidence was not available in the active scope."\n        elif abstain:\n            reason = "No allowed evidence was found in the active scope."\n        else:\n            reason = ""\n        run_id = make_id("RETRIEVE")\n        result = RetrievalResult(run_id, plan, selected, excluded, self._pack(plan, selected, excluded),\n                                 {lane.value: len(items) for lane, items in lane_results.items()}, abstain, reason, diagnostics)\n        if self.config.trace_enabled and plan.trace:\n            self.store.record_retrieval_run(\n                run_id=run_id, query_text=query, route=plan.route.value, scope=scope.to_dict(), plan=plan.to_dict(),\n                selected=[item.to_dict() for item in selected], excluded=excluded, diagnostics=diagnostics,\n                latency_ms=(time.perf_counter() - started) * 1000,\n            )\n        return result\n'''
query = replace_once(query, old_execute_tail, new_execute_tail, "query execute hardening")
write(query_path, query)


# ---------------------------------------------------------------------------
# Service: enrich real active-scene order, wire switches, report background
# failures, cancel pending refreshes on delete, and respect Memory allocation.
# ---------------------------------------------------------------------------
service_path = "src/memory/service.py"
write(service_path, dedent('''
from __future__ import annotations

from typing import Any
from threading import RLock, Timer

from .config import MemoryConfig
from .embedding import DisabledEmbeddingProvider, DisabledRerankerProvider, LMStudioEmbeddingProvider
from .index import MemoryIndexer
from .models import MemoryQueryContext, RetrievalResult
from .query import MemoryQueryEngine
from .store import MemoryStore


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
        if context.story_order is None and scene_card.get("sort_order") is not None:
            context.story_order = float(scene_card["sort_order"])
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
                "reranker_requested": self.config.reranker.enabled, "reranker_available": self.reranker.available()}

    def backfill(self, project_id: str | None = None) -> dict[str, Any]:
        if not self.config.enabled:
            return {"disabled": True, "documents": 0, "turns": 0, "chunks": 0}
        return self.indexer.backfill(project_id)

    def retrieve(self, query: str, context: MemoryQueryContext) -> RetrievalResult:
        if not self.config.enabled or not query.strip():
            from .models import QueryPlan, QueryRoute
            plan = QueryPlan(QueryRoute.TEXT_RECALL, context, normalized_query=query.strip())
            return RetrievalResult("disabled", plan, [], [], "", {}, True, "Memory retrieval is disabled.")
        return self.query_engine.execute(query, self._enrich_context(context))

    def augment_workspace_context(self, workspace_context, result: RetrievalResult):
        memory_meta = {
            "run_id": result.run_id, "route": result.plan.route.value, "selected": len(result.selected),
            "excluded": len(result.excluded), "abstain": result.abstain, "reason": result.abstention_reason,
            "token_budget": result.plan.scope.token_budget,
        }
        if not result.packed_text:
            workspace_context.scope["memory"] = memory_meta
            return workspace_context
        workspace_context.text = workspace_context.text.rstrip() + "\\n\\n" + result.packed_text.rstrip() + "\\n"
        packed_tokens = max(1, len(result.packed_text) // 4)
        workspace_context.estimated_tokens += packed_tokens
        workspace_context.scope["memory"] = {
            **memory_meta, "lens": result.plan.scope.context_lens.value, "lane_counts": result.lane_counts,
            "packed_tokens": packed_tokens, "diagnostics": result.diagnostics,
            "selected_sources": [{"id": item.id, "lane": item.lane.value, "source_type": item.source_type,
                                  "source_id": item.source_id, "score": round(item.score, 6), "ranks": item.ranks}
                                 for item in result.selected],
            "excluded_preview": result.excluded[:20],
        }
        return workspace_context
'''))


# ---------------------------------------------------------------------------
# FastAPI integration: allocate Memory inside context headroom; refresh scene
# order changes; cancel timers before destructive lifecycle actions.
# ---------------------------------------------------------------------------
app_path = "src/interface/web/app.py"
app = read(app_path)
old_scope_build = '''        memory_scope = MemoryQueryContext(\n            project_id=project_id,\n            world_id=world_id,\n            branch_id=branch_id,\n            session_id=session_id,\n            world_time=payload.world_time if payload.world_time is not None else (active_scene.get("narrative_time") or None),\n            story_order=payload.story_order,\n            pov_variant_id=payload.pov_variant_id or active_scene.get("pov_variant_id"),\n            context_lens=lens,\n            retrieval_mode="generation",\n            explicit_references=refs,\n            allow_scratch=bool(payload.scratch_mode),\n            allow_future_author_knowledge=(lens == "author"),\n        )\n'''
new_scope_build = '''        output_reserve = int(payload.visible_output_tokens) + (int(payload.reasoning_reserve_tokens) if payload.reasoning != "off" else 0)\n        fixed_reserve = (\n            initial_cfg.context_budget.safety_margin\n            + initial_cfg.context_budget.system_prompt_token_estimate\n            + initial_cfg.context_budget.minimum_writer_context_tokens\n            + int(ws_context.estimated_tokens or 0)\n        )\n        remaining = max(0, int(payload.context_length) - output_reserve - fixed_reserve)\n        memory_budget = min(memory_config.max_pack_tokens, remaining)\n        memory_scope = MemoryQueryContext(\n            project_id=project_id,\n            world_id=world_id,\n            branch_id=branch_id,\n            session_id=session_id,\n            world_time=payload.world_time if payload.world_time is not None else (active_scene.get("narrative_time") or None),\n            story_order=payload.story_order,\n            pov_variant_id=payload.pov_variant_id or active_scene.get("pov_variant_id"),\n            context_lens=lens,\n            retrieval_mode="generation",\n            explicit_references=refs,\n            allow_scratch=bool(payload.scratch_mode),\n            allow_future_author_knowledge=(lens == "author"),\n            token_budget=memory_budget,\n        )\n'''
app = replace_once(app, old_scope_build, new_scope_build, "app memory budget")
old_scene_card = '''    @app.put("/api/projects/{project_id}/scene-cards/{document_id}")\n    def set_scene_card(project_id: str, document_id: str, payload: SceneCardPayload):\n        try:\n            return workspace.set_scene_card(project_id, document_id, **payload.model_dump())\n'''
new_scene_card = '''    @app.put("/api/projects/{project_id}/scene-cards/{document_id}")\n    def set_scene_card(project_id: str, document_id: str, payload: SceneCardPayload):\n        try:\n            card = workspace.set_scene_card(project_id, document_id, **payload.model_dump())\n            memory_service.schedule_document_refresh(document_id)\n            return card\n'''
app = replace_once(app, old_scene_card, new_scene_card, "scene card memory refresh")
old_delete_doc = '''    @app.delete("/api/documents/{document_id}")\n    def delete_document(document_id: str):\n        try:\n            workspace.delete_document(document_id)\n            memory_service.forget_document(document_id)\n'''
new_delete_doc = '''    @app.delete("/api/documents/{document_id}")\n    def delete_document(document_id: str):\n        try:\n            memory_service.cancel_document_refresh(document_id)\n            workspace.delete_document(document_id)\n            memory_service.forget_document(document_id)\n'''
app = replace_once(app, old_delete_doc, new_delete_doc, "document delete race")
old_delete_session = '''    @app.delete("/api/sessions/{session_id}")\n    def delete_session(session_id: str):\n        try:\n            history.delete_session(session_id)\n            memory_service.forget_session(session_id)\n'''
new_delete_session = '''    @app.delete("/api/sessions/{session_id}")\n    def delete_session(session_id: str):\n        try:\n            memory_service.cancel_session_refreshes(session_id)\n            history.delete_session(session_id)\n            memory_service.forget_session(session_id)\n'''
app = replace_once(app, old_delete_session, new_delete_session, "session delete race")
write(app_path, app)


# ---------------------------------------------------------------------------
# Executable frontend runtime smoke: catches the exact const-state/window-state
# integration bug rather than merely syntax-checking memory.js.
# ---------------------------------------------------------------------------
write("tests/frontend/memory_runtime_smoke.js", dedent(r'''
"use strict";
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const appState = {
  activeProject: {id: "P-ACTIVE"}, activeWorld: {id: "W-ACTIVE"}, activeBranch: {id: "B-ACTIVE"},
  activeSession: {id: "S-ACTIVE"}, activeScene: {document_id: "DOC-2", narrative_time: "Day 2", pov_variant_id: "POV-1"},
  sceneCards: [{document_id: "DOC-2", sort_order: 2, narrative_time: "Day 2", pov_variant_id: "POV-1"}],
};
global.window = {
  ArlineRuntime: {
    getState: () => appState,
    getScope: () => ({projectId: "P-ACTIVE", worldId: "W-ACTIVE", branchId: "B-ACTIVE", sessionId: "S-ACTIVE"}),
  },
  collectPromptReferences: () => [{type: "entity_family", id: "E-1"}],
};
global.localStorage = {getItem: () => null, setItem: () => {}};
global.document = {getElementById: () => null, querySelector: () => null, addEventListener: () => {}};
global.fetch = async () => { throw new Error("network should not be used by scope smoke"); };

vm.runInThisContext(fs.readFileSync("src/interface/web/static/js/memory.js", "utf8"), {filename: "memory.js"});
const scope = window.ArlineMemoryRuntime.currentScope("where is it?");
assert.deepStrictEqual(
  {project: scope.project_id, world: scope.world_id, branch: scope.branch_id, session: scope.session_id},
  {project: "P-ACTIVE", world: "W-ACTIVE", branch: "B-ACTIVE", session: "S-ACTIVE"},
);
assert.strictEqual(scope.story_order, 2);
assert.strictEqual(scope.world_time, "Day 2");
assert.strictEqual(scope.pov_variant_id, "POV-1");
assert.strictEqual(scope.explicit_references[0].id, "E-1");
assert.ok(!fs.readFileSync("src/interface/web/static/js/memory.js", "utf8").includes("window.state?."));
console.log("memory runtime scope bridge: ok");
'''))


# ---------------------------------------------------------------------------
# Python regression coverage for production temporal metadata, fork cutoff,
# atomic revision replacement, dense generation rollover, routing and switches.
# ---------------------------------------------------------------------------
write("tests/memory/test_v120_correctness_hardening.py", dedent('''
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.history.store import HistoryStore
from src.memory import MemoryConfig, MemoryQueryContext, MemoryQueryEngine, MemoryStore, QueryCompiler, QueryRoute, ScopeGate
from src.memory.config import EmbeddingConfig
from src.memory.index import MemoryIndexer
from src.memory.models import MemoryCandidate, RetrievalLane
from src.workspace.store import WorkspaceStore


class _NoEntities:
    path = Path("__different__.db")
    def list_entity_families(self, _project=None): return []
    def list_variants(self, **_kwargs): return []
    def get_scene_card(self, _document_id): raise KeyError(_document_id)
    def get_document(self, _document_id): raise KeyError(_document_id)
    def get_branch(self, branch_id): raise KeyError(branch_id)


class _FakeEmbedding:
    model_id = "fake-e5"
    dimension = 3
    def available(self): return True
    def embed_passages(self, texts): return [[float(len(text) % 7 + 1), 1.0, 0.5] for text in texts]
    def embed_query(self, text): return [float(len(text) % 7 + 1), 1.0, 0.5]


class V120CorrectnessHardeningTests(unittest.TestCase):
    def test_routing_does_not_treat_scene_word_as_continue(self):
        workspace = _NoEntities()
        self.assertEqual(QueryCompiler.route("Summarize this scene"), QueryRoute.GLOBAL_SUMMARY)
        self.assertEqual(QueryCompiler.route("Where did this scene happen?"), QueryRoute.SPATIAL_LOOKUP)
        self.assertEqual(QueryCompiler.route("Continue the current scene"), QueryRoute.STORY_CONTINUE)

    def test_atomic_source_replacement_rolls_back_on_failure(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "arline.db"
            workspace = WorkspaceStore(db)
            project = workspace.create_project("Atomic")
            document = workspace.create_document(project["id"], "Scene", content="old complete revision")
            store = MemoryStore(db)
            store.upsert_chunk(source_type="document", source_id=document["id"], source_revision="old:0", text="old complete revision")
            with self.assertRaises(ValueError):
                store.replace_source_revision(
                    source_type="document", source_id=document["id"],
                    source_guard={"table": "workspace_documents", "id": document["id"], "updated_at": document["updated_at"]},
                    prepared=[{"source_revision": "new:0", "text": "first new chunk"}, {"source_revision": "new:1", "text": ""}],
                )
            active = store.list_chunks(source_type="document", source_id=document["id"], status="active")
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["text"], "old complete revision")

    def test_real_document_index_carries_scene_order_and_blocks_future_scene(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "arline.db"
            workspace = WorkspaceStore(db)
            history = HistoryStore(db, backup_before_migration=False)
            project = workspace.create_project("Temporal")
            world_id = project["default_world_id"]
            branch = next(item for item in workspace.get_world(world_id)["branches"] if item["kind"] == "main")
            earlier = workspace.create_document(project["id"], "Earlier", content="shared clue early", world_id=world_id, branch_id=branch["id"], sort_order=1)
            later = workspace.create_document(project["id"], "Later", content="shared clue spoiler", world_id=world_id, branch_id=branch["id"], sort_order=2)
            store = MemoryStore(db)
            indexer = MemoryIndexer(store=store, workspace=workspace, history=history, config=MemoryConfig())
            indexer.index_document(earlier); indexer.index_document(later)
            rows = store.search_fts("shared clue", domains=["manuscript"], limit=10)
            by_source = {row["source_id"]: row for row in rows}
            self.assertEqual(by_source[earlier["id"]]["story_order"], 1.0)
            self.assertEqual(by_source[later["id"]]["story_order"], 2.0)
            gate = ScopeGate(workspace, history)
            candidate = MemoryQueryEngine._candidate_from_chunk(by_source[later["id"]], RetrievalLane.FTS_MANUSCRIPT, 1)
            decision = gate.evaluate(candidate, MemoryQueryContext(project_id=project["id"], world_id=world_id, branch_id=branch["id"], story_order=1, context_lens="scene"))
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.rule, "story_order")

    def test_parent_chat_after_fork_is_blocked_from_real_indexed_turn(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "arline.db"
            history = HistoryStore(db, backup_before_migration=False)
            parent = history.create_session(prompt="parent", project_id="P")
            turns = []
            for i, story in enumerate(("first", "fork point", "SECRET AFTER FORK"), 1):
                turns.append(history.add_turn(parent["id"], run_id=f"R{i}", user_prompt=f"u{i}", story=story,
                                              model="m", mode="smart_hybrid", reasoning="off", projection_mode="off"))
            child = history.fork_session(parent["id"], through_turn_id=turns[1]["id"])
            workspace = _NoEntities()
            store = MemoryStore(db)
            indexer = MemoryIndexer(store=store, workspace=workspace, history=history, config=MemoryConfig())
            parent_meta = history.get_session_meta(parent["id"])
            for turn in turns:
                indexer.index_turn({**turn, "project_id": "P", "session_id": parent["id"], "scratch_mode": False})
            row = next(item for item in store.search_fts("SECRET AFTER FORK", domains=["chat"], limit=10) if item["source_id"] == turns[2]["id"])
            candidate = MemoryQueryEngine._candidate_from_chunk(row, RetrievalLane.FTS_CHAT, 1)
            decision = ScopeGate(workspace, history).evaluate(candidate, MemoryQueryContext(project_id="P", session_id=child["id"]))
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.rule, "session_cutoff")
            self.assertEqual(parent_meta["id"], parent["id"])

    def test_dense_rollover_embeds_unchanged_chunks_into_new_generation(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "memory.db"
            store = MemoryStore(db)
            workspace = _NoEntities()
            class _History: path = Path(td) / "other.db"
            config = MemoryConfig(dense_enabled=True, embedding=EmbeddingConfig(enabled=True, provider="fake", model="fake-e5", dimension=3))
            indexer = MemoryIndexer(store=store, workspace=workspace, history=_History(), config=config, embedding=_FakeEmbedding())
            document = {"id": "DOC-1", "project_id": "P", "world_id": None, "branch_id": None, "title": "Dense", "content": "unchanged dense evidence", "sort_order": 1, "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00"}
            # Fake workspace cannot source-guard, so provide current document for revision check.
            workspace.get_document = lambda _id: dict(document)
            g1 = store.create_generation(provider="fake", embedding_model="fake-e5", dimension=3, chunker_version=1)
            rows = indexer.index_document(document, generation_id=g1["generation_id"])
            self.assertFalse(store.vector_coverage(g1["generation_id"], [r["id"] for r in rows])["missing"])
            g2 = store.create_generation(provider="fake", embedding_model="fake-e5", dimension=3, chunker_version=1)
            rows2 = indexer.index_document(document, generation_id=g2["generation_id"])
            self.assertEqual([r["id"] for r in rows2], [r["id"] for r in rows])
            self.assertFalse(store.vector_coverage(g2["generation_id"], [r["id"] for r in rows2])["missing"])

    def test_fts_and_trace_switches_and_required_lane_abstention(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "memory.db")
            workspace = _NoEntities()
            config = MemoryConfig(fts_enabled=False, trace_enabled=False, dense_enabled=False)
            engine = MemoryQueryEngine(store=store, workspace=workspace, config=config)
            result = engine.execute("remember this wording", MemoryQueryContext(project_id="P", token_budget=128))
            self.assertFalse(any(lane.value.startswith("fts_") for lane in result.plan.optional_lanes + result.plan.required_lanes))
            with self.assertRaises(KeyError):
                store.get_retrieval_run(result.run_id)

            config2 = MemoryConfig(fts_enabled=True, trace_enabled=False)
            engine2 = MemoryQueryEngine(store=store, workspace=workspace, config=config2)
            store.upsert_chunk(source_type="document", source_id="DOC", text="Whereabouts are mentioned in prose", project_id="P")
            spatial = engine2.execute("Where is Vian?", MemoryQueryContext(project_id="P"))
            self.assertTrue(spatial.abstain)
            self.assertIn("Required structured evidence", spatial.abstention_reason)


if __name__ == "__main__":
    unittest.main()
'''))


# ---------------------------------------------------------------------------
# Milestone notes: do not claim correctness without these invariants.
# ---------------------------------------------------------------------------
status_path = "docs/V12_IMPLEMENTATION_STATUS.md"
status = read(status_path)
if "fork cutoffs are enforced" not in status:
    status += dedent('''

## v1.2.0 correctness hardening

- Memory frontend scope is read through the explicit `ArlineRuntime` bridge; a missing active project can no longer silently turn a UI backfill into a global backfill.
- Production document/chat chunks carry story-order/world-time metadata when the active Scene Card provides it; parent-chat fork cutoffs and ancestor-branch recorded-time cutoffs are enforced by ScopeGate.
- Source revision replacement is transactional: old evidence remains active until every new chunk/link/vector is ready and the source revision guard still matches.
- Dense generation activation verifies vector coverage, including unchanged chunks during generation rollover; dense rebuild generations are global snapshots.
- Memory receives an explicit remaining-token allocation and packs evidence inside that allocation rather than appending an unbounded block after the v1.1 context boundary.
- Background refresh failures create a visible issue/activity record, pending refreshes are cancelled on delete, and source guards prevent a late timer from resurrecting deleted/stale evidence.
- `enabled`, `fts_enabled`, `trace_enabled`, and `reranker.enabled` now control their advertised runtime behavior.
- Query routing no longer treats the mere words “scene” or “dialogue” as a continuation command; deterministic routes abstain when their required evidence lanes are empty after ScopeGate.
''')
write(status_path, status)

print("v1.2.0 correctness hardening staged")
