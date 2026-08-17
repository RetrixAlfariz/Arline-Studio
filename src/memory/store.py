from __future__ import annotations

from array import array
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Iterable
from uuid import uuid4

from .models import Authority, SemanticClass, SemanticStatus, TrustLevel


MEMORY_SCHEMA_VERSION = 1
FTS_DOMAINS = {"manuscript", "chat", "summary", "import"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{prefix}-{stamp}-{uuid4().hex[:8].upper()}"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class MemoryStore:
    """Authoritative metadata + disposable retrieval projections in SQLite.

    The source documents, turns, Library objects and accepted events remain the
    source of truth. Memory chunks and vectors can always be rebuilt.
    """

    SCHEMA_VERSION = MEMORY_SCHEMA_VERSION

    def __init__(self, database_path: Path | str):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.fts_available = True
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=30000")
        return con

    @contextmanager
    def connection(self):
        con = self._connect()
        try:
            yield con
        finally:
            con.close()

    def _init_db(self) -> None:
        with self._lock, self.connection() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_meta(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_chunks(
                    id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_revision TEXT,
                    project_id TEXT,
                    world_id TEXT,
                    branch_id TEXT,
                    session_id TEXT,
                    source_start_id TEXT,
                    source_end_id TEXT,
                    world_time_json TEXT,
                    story_order REAL,
                    scope_kind TEXT NOT NULL DEFAULT 'project',
                    semantic_class TEXT NOT NULL DEFAULT 'evidence',
                    authority TEXT NOT NULL DEFAULT 'project_manuscript',
                    trust_level TEXT NOT NULL DEFAULT 'trusted_local',
                    text TEXT NOT NULL,
                    retrieval_text TEXT,
                    display_excerpt TEXT,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    importance REAL NOT NULL DEFAULT 0.5,
                    extraction_confidence REAL NOT NULL DEFAULT 1.0,
                    identity_confidence REAL NOT NULL DEFAULT 1.0,
                    semantic_status TEXT NOT NULL DEFAULT 'active',
                    index_state TEXT NOT NULL DEFAULT 'pending',
                    checksum TEXT NOT NULL,
                    chunker_version INTEGER NOT NULL DEFAULT 1,
                    index_generation INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_chunks_source
                    ON memory_chunks(source_type,source_id,semantic_status);
                CREATE INDEX IF NOT EXISTS idx_memory_chunks_scope
                    ON memory_chunks(world_id,branch_id,project_id,session_id,semantic_status);
                CREATE INDEX IF NOT EXISTS idx_memory_chunks_order
                    ON memory_chunks(world_id,branch_id,story_order);
                CREATE INDEX IF NOT EXISTS idx_memory_chunks_checksum
                    ON memory_chunks(source_type,source_id,source_revision,checksum);

                CREATE TABLE IF NOT EXISTS memory_links(
                    memory_chunk_id TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    relation TEXT NOT NULL DEFAULT 'mentions',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    resolution_method TEXT NOT NULL DEFAULT 'exact',
                    PRIMARY KEY(memory_chunk_id,resource_type,resource_id,relation),
                    FOREIGN KEY(memory_chunk_id) REFERENCES memory_chunks(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_memory_links_resource
                    ON memory_links(resource_type,resource_id,relation);

                CREATE TABLE IF NOT EXISTS memory_summaries(
                    id TEXT PRIMARY KEY,
                    summary_type TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    project_id TEXT,
                    world_id TEXT,
                    branch_id TEXT,
                    world_time_from_json TEXT,
                    world_time_to_json TEXT,
                    story_order_from REAL,
                    story_order_to REAL,
                    text TEXT NOT NULL,
                    structured_payload_json TEXT NOT NULL DEFAULT '{}',
                    evidence_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_summary_sources(
                    summary_id TEXT NOT NULL,
                    memory_chunk_id TEXT NOT NULL,
                    PRIMARY KEY(summary_id,memory_chunk_id),
                    FOREIGN KEY(summary_id) REFERENCES memory_summaries(id) ON DELETE CASCADE,
                    FOREIGN KEY(memory_chunk_id) REFERENCES memory_chunks(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS story_threads(
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    world_id TEXT NOT NULL,
                    branch_id TEXT,
                    thread_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open',
                    opened_event_id TEXT,
                    resolved_event_id TEXT,
                    world_time_json TEXT,
                    story_order REAL,
                    authority TEXT NOT NULL DEFAULT 'user_accepted_world_canon',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    source_type TEXT NOT NULL DEFAULT 'manual',
                    source_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_story_threads_scope
                    ON story_threads(world_id,branch_id,status,thread_type);

                CREATE TABLE IF NOT EXISTS story_thread_links(
                    thread_id TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    relation TEXT NOT NULL DEFAULT 'related',
                    PRIMARY KEY(thread_id,resource_type,resource_id,relation),
                    FOREIGN KEY(thread_id) REFERENCES story_threads(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS memory_index_generations(
                    generation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    embedding_model TEXT,
                    embedding_dimension INTEGER,
                    chunker_version INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'building',
                    created_at TEXT NOT NULL,
                    activated_at TEXT,
                    detail_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS memory_vectors(
                    memory_chunk_id TEXT NOT NULL,
                    generation_id INTEGER NOT NULL,
                    model_id TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    vector_blob BLOB NOT NULL,
                    norm REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(memory_chunk_id,generation_id),
                    FOREIGN KEY(memory_chunk_id) REFERENCES memory_chunks(id) ON DELETE CASCADE,
                    FOREIGN KEY(generation_id) REFERENCES memory_index_generations(generation_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_memory_vectors_generation
                    ON memory_vectors(generation_id,model_id);

                CREATE TABLE IF NOT EXISTS retrieval_runs(
                    id TEXT PRIMARY KEY,
                    query_text TEXT NOT NULL,
                    route TEXT NOT NULL,
                    scope_json TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    selected_json TEXT NOT NULL DEFAULT '[]',
                    excluded_json TEXT NOT NULL DEFAULT '[]',
                    diagnostics_json TEXT NOT NULL DEFAULT '[]',
                    latency_ms REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS branch_visibility(
                    query_branch_id TEXT NOT NULL,
                    visible_branch_id TEXT NOT NULL,
                    depth INTEGER NOT NULL DEFAULT 0,
                    fork_event_id TEXT,
                    max_world_time_json TEXT,
                    max_story_order REAL,
                    PRIMARY KEY(query_branch_id,visible_branch_id)
                );

                CREATE TABLE IF NOT EXISTS current_state_projection(
                    world_id TEXT NOT NULL,
                    branch_id TEXT,
                    owner_type TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    state_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_id TEXT,
                    authority TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(world_id,branch_id,owner_type,owner_id,state_key)
                );
                CREATE INDEX IF NOT EXISTS idx_current_state_owner
                    ON current_state_projection(world_id,branch_id,owner_type,owner_id);

                CREATE TABLE IF NOT EXISTS state_intervals(
                    id TEXT PRIMARY KEY,
                    world_id TEXT NOT NULL,
                    branch_id TEXT,
                    owner_type TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    state_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    valid_from_event_id TEXT,
                    valid_to_event_id TEXT,
                    valid_from_world_time_json TEXT,
                    valid_to_world_time_json TEXT,
                    story_order_from REAL,
                    story_order_to REAL,
                    source_type TEXT NOT NULL,
                    source_id TEXT,
                    authority TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'accepted',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_state_intervals_lookup
                    ON state_intervals(world_id,branch_id,owner_type,owner_id,state_key,story_order_from,story_order_to);

                CREATE TABLE IF NOT EXISTS event_participants(
                    event_id TEXT NOT NULL,
                    entity_variant_id TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'participant',
                    PRIMARY KEY(event_id,entity_variant_id,role)
                );
                CREATE INDEX IF NOT EXISTS idx_event_participant_entity
                    ON event_participants(entity_variant_id,event_id);

                CREATE TABLE IF NOT EXISTS event_causal_edges(
                    source_event_id TEXT NOT NULL,
                    target_event_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    authority TEXT NOT NULL DEFAULT 'accepted_event',
                    status TEXT NOT NULL DEFAULT 'accepted',
                    PRIMARY KEY(source_event_id,target_event_id,relation)
                );

                CREATE TABLE IF NOT EXISTS epistemic_intervals(
                    id TEXT PRIMARY KEY,
                    world_id TEXT NOT NULL,
                    branch_id TEXT,
                    character_variant_id TEXT NOT NULL,
                    topic_type TEXT NOT NULL,
                    topic_id TEXT NOT NULL,
                    state_type TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    valid_from_event_id TEXT,
                    valid_to_event_id TEXT,
                    valid_from_world_time_json TEXT,
                    valid_to_world_time_json TEXT,
                    story_order_from REAL,
                    story_order_to REAL,
                    source_type TEXT NOT NULL,
                    source_id TEXT,
                    status TEXT NOT NULL DEFAULT 'accepted',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_epistemic_lookup
                    ON epistemic_intervals(world_id,branch_id,character_variant_id,topic_type,topic_id,state_type);

                CREATE TABLE IF NOT EXISTS spatial_edges(
                    id TEXT PRIMARY KEY,
                    world_id TEXT NOT NULL,
                    branch_id TEXT,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    structural INTEGER NOT NULL DEFAULT 1,
                    valid_from_event_id TEXT,
                    valid_to_event_id TEXT,
                    valid_from_world_time_json TEXT,
                    valid_to_world_time_json TEXT,
                    story_order_from REAL,
                    story_order_to REAL,
                    authority TEXT NOT NULL DEFAULT 'user_accepted_world_canon',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    status TEXT NOT NULL DEFAULT 'accepted',
                    source_type TEXT NOT NULL DEFAULT 'manual',
                    source_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_spatial_subject
                    ON spatial_edges(world_id,branch_id,subject_type,subject_id,relation,status);
                CREATE INDEX IF NOT EXISTS idx_spatial_object
                    ON spatial_edges(world_id,branch_id,object_type,object_id,relation,status);

                CREATE TABLE IF NOT EXISTS current_spatial_index(
                    world_id TEXT NOT NULL,
                    branch_id TEXT,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    source_edge_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(world_id,branch_id,subject_type,subject_id,relation,object_type,object_id)
                );
                """
            )
            try:
                for domain in sorted(FTS_DOMAINS):
                    con.execute(
                        f"CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts_{domain} "
                        "USING fts5(chunk_id UNINDEXED, text, tokenize='unicode61 remove_diacritics 2')"
                    )
            except sqlite3.OperationalError:
                self.fts_available = False
            con.execute(
                "INSERT INTO memory_meta(key,value) VALUES('schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(self.SCHEMA_VERSION),),
            )

    @staticmethod
    def _chunk_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["world_time"] = loads(item.pop("world_time_json"), None)
        return item

    @staticmethod
    def _domain_for_source(source_type: str) -> str:
        return {
            "document": "manuscript",
            "chat_window": "chat",
            "turn": "chat",
            "derived_summary": "summary",
            "import": "import",
        }.get(source_type, "manuscript")

    def upsert_chunk(self, *, source_type: str, source_id: str, text: str,
                     source_revision: str | None = None, retrieval_text: str | None = None,
                     display_excerpt: str | None = None, project_id: str | None = None,
                     world_id: str | None = None, branch_id: str | None = None,
                     session_id: str | None = None, source_start_id: str | None = None,
                     source_end_id: str | None = None, world_time: Any = None,
                     story_order: float | None = None, scope_kind: str = "project",
                     semantic_class: str = SemanticClass.EVIDENCE.value,
                     authority: str = Authority.PROJECT_MANUSCRIPT.value,
                     trust_level: str = TrustLevel.TRUSTED_LOCAL.value,
                     importance: float = 0.5, extraction_confidence: float = 1.0,
                     identity_confidence: float = 1.0, chunker_version: int = 1,
                     index_generation: int | None = None) -> dict[str, Any]:
        clean = text.strip()
        if not clean:
            raise ValueError("Memory chunk text cannot be empty")
        digest = checksum(clean)
        with self._lock, self.connection() as con:
            existing = con.execute(
                "SELECT * FROM memory_chunks WHERE source_type=? AND source_id=? AND "
                "source_revision IS ? AND checksum=? AND semantic_status='active' LIMIT 1",
                (source_type, source_id, source_revision, digest),
            ).fetchone()
            if existing:
                return self._chunk_row(existing)
            chunk_id = make_id("MEM")
            now = utc_now()
            con.execute(
                "INSERT INTO memory_chunks(id,source_type,source_id,source_revision,project_id,world_id,branch_id,session_id,"
                "source_start_id,source_end_id,world_time_json,story_order,scope_kind,semantic_class,authority,trust_level,text,"
                "retrieval_text,display_excerpt,token_count,importance,extraction_confidence,identity_confidence,semantic_status,"
                "index_state,checksum,chunker_version,index_generation,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active','ready',?,?,?,?,?)",
                (chunk_id, source_type, source_id, source_revision, project_id, world_id, branch_id, session_id,
                 source_start_id, source_end_id, dumps(world_time) if world_time is not None else None, story_order,
                 scope_kind, semantic_class, authority, trust_level, clean, retrieval_text or clean,
                 display_excerpt or clean[:500], max(1, len(clean) // 4), float(importance),
                 float(extraction_confidence), float(identity_confidence), digest, int(chunker_version),
                 index_generation, now, now),
            )
            if self.fts_available:
                domain = self._domain_for_source(source_type)
                con.execute(f"INSERT INTO memory_fts_{domain}(chunk_id,text) VALUES(?,?)", (chunk_id, retrieval_text or clean))
            row = con.execute("SELECT * FROM memory_chunks WHERE id=?", (chunk_id,)).fetchone()
        return self._chunk_row(row)

    def replace_links(self, chunk_id: str, links: Iterable[dict[str, Any]]) -> None:
        with self._lock, self.connection() as con:
            con.execute("DELETE FROM memory_links WHERE memory_chunk_id=?", (chunk_id,))
            for link in links:
                con.execute(
                    "INSERT OR IGNORE INTO memory_links(memory_chunk_id,resource_type,resource_id,relation,confidence,resolution_method) "
                    "VALUES(?,?,?,?,?,?)",
                    (chunk_id, link["resource_type"], link["resource_id"], link.get("relation", "mentions"),
                     float(link.get("confidence", 1.0)), link.get("resolution_method", "exact")),
                )

    def get_chunk(self, chunk_id: str) -> dict[str, Any]:
        with self.connection() as con:
            row = con.execute("SELECT * FROM memory_chunks WHERE id=?", (chunk_id,)).fetchone()
            if not row:
                raise KeyError(chunk_id)
            links = con.execute("SELECT * FROM memory_links WHERE memory_chunk_id=?", (chunk_id,)).fetchall()
        item = self._chunk_row(row)
        item["links"] = [dict(link) for link in links]
        return item

    def list_chunks(self, *, source_type: str | None = None, source_id: str | None = None,
                    status: str | None = "active", limit: int = 200) -> list[dict[str, Any]]:
        where = ["1=1"]; params: list[Any] = []
        if source_type: where.append("source_type=?"); params.append(source_type)
        if source_id: where.append("source_id=?"); params.append(source_id)
        if status: where.append("semantic_status=?"); params.append(status)
        params.append(max(1, min(5000, int(limit))))
        with self.connection() as con:
            rows = con.execute(
                f"SELECT * FROM memory_chunks WHERE {' AND '.join(where)} ORDER BY updated_at DESC LIMIT ?", params
            ).fetchall()
        return [self._chunk_row(row) for row in rows]


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

    @staticmethod
    def _fts_query(query: str) -> str:
        terms = [token for token in query.replace('"', ' ').split() if len(token) > 1][:24]
        return " OR ".join(f'"{term}"' for term in terms)

    def search_fts(self, query: str, *, domains: Iterable[str] | None = None, limit: int = 30) -> list[dict[str, Any]]:
        if not self.fts_available:
            return []
        expression = self._fts_query(query)
        if not expression:
            return []
        selected_domains = [d for d in (domains or FTS_DOMAINS) if d in FTS_DOMAINS]
        results: list[dict[str, Any]] = []
        with self.connection() as con:
            for domain in selected_domains:
                try:
                    rows = con.execute(
                        f"SELECT chunk_id,bm25(memory_fts_{domain}) AS raw_rank,"
                        f"snippet(memory_fts_{domain},1,'[',']',' … ',20) AS snippet "
                        f"FROM memory_fts_{domain} WHERE memory_fts_{domain} MATCH ? ORDER BY raw_rank LIMIT ?",
                        (expression, max(1, int(limit))),
                    ).fetchall()
                except sqlite3.OperationalError:
                    continue
                for rank, row in enumerate(rows, 1):
                    chunk = con.execute("SELECT * FROM memory_chunks WHERE id=?", (row["chunk_id"],)).fetchone()
                    if not chunk:
                        continue
                    item = self._chunk_row(chunk)
                    item.update({"domain": domain, "rank": rank, "raw_rank": row["raw_rank"], "snippet": row["snippet"]})
                    results.append(item)
        return results

    def create_generation(self, *, provider: str, embedding_model: str | None, dimension: int | None,
                          chunker_version: int, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock, self.connection() as con:
            cur = con.execute(
                "INSERT INTO memory_index_generations(provider,embedding_model,embedding_dimension,chunker_version,status,created_at,detail_json) "
                "VALUES(?,?,?,?, 'building',?,?)",
                (provider, embedding_model, dimension, chunker_version, utc_now(), dumps(detail or {})),
            )
            generation_id = int(cur.lastrowid)
        return self.get_generation(generation_id)

    def get_generation(self, generation_id: int) -> dict[str, Any]:
        with self.connection() as con:
            row = con.execute("SELECT * FROM memory_index_generations WHERE generation_id=?", (generation_id,)).fetchone()
        if not row: raise KeyError(generation_id)
        item = dict(row); item["detail"] = loads(item.pop("detail_json"), {})
        return item


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

    def active_generation(self) -> dict[str, Any] | None:
        with self.connection() as con:
            row = con.execute("SELECT * FROM memory_index_generations WHERE status='active' ORDER BY generation_id DESC LIMIT 1").fetchone()
        if not row: return None
        item = dict(row); item["detail"] = loads(item.pop("detail_json"), {})
        return item

    def set_generation_status(self, generation_id: int, status: str) -> dict[str, Any]:
        if status not in {"building", "verified", "active", "retired", "failed"}:
            raise ValueError(status)
        with self._lock, self.connection() as con:
            if status == "active":
                con.execute("UPDATE memory_index_generations SET status='retired' WHERE status='active'")
            con.execute(
                "UPDATE memory_index_generations SET status=?,activated_at=CASE WHEN ?='active' THEN ? ELSE activated_at END WHERE generation_id=?",
                (status, status, utc_now(), generation_id),
            )
        return self.get_generation(generation_id)

    @staticmethod
    def _vector_blob(values: list[float]) -> tuple[bytes, float]:
        data = array("f", (float(value) for value in values))
        norm = math.sqrt(sum(float(value) * float(value) for value in data)) or 1.0
        return data.tobytes(), norm

    def upsert_vector(self, chunk_id: str, generation_id: int, model_id: str, values: list[float]) -> None:
        blob, norm = self._vector_blob(values)
        with self._lock, self.connection() as con:
            con.execute(
                "INSERT INTO memory_vectors(memory_chunk_id,generation_id,model_id,dimension,vector_blob,norm,created_at) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(memory_chunk_id,generation_id) DO UPDATE SET "
                "model_id=excluded.model_id,dimension=excluded.dimension,vector_blob=excluded.vector_blob,norm=excluded.norm,created_at=excluded.created_at",
                (chunk_id, generation_id, model_id, len(values), blob, norm, utc_now()),
            )

    def search_vectors(self, query_vector: list[float], *, generation_id: int, limit: int = 30) -> list[dict[str, Any]]:
        q_blob, q_norm = self._vector_blob(query_vector)
        q = array("f"); q.frombytes(q_blob)
        results: list[tuple[float, dict[str, Any]]] = []
        with self.connection() as con:
            rows = con.execute(
                "SELECT v.*,c.* FROM memory_vectors v JOIN memory_chunks c ON c.id=v.memory_chunk_id "
                "WHERE v.generation_id=? AND c.semantic_status='active'",
                (generation_id,),
            ).fetchall()
        for row in rows:
            if int(row["dimension"]) != len(q):
                continue
            vector = array("f"); vector.frombytes(row["vector_blob"])
            score = sum(float(a) * float(b) for a, b in zip(q, vector)) / (q_norm * float(row["norm"] or 1.0))
            item = self._chunk_row(row)
            item["dense_score"] = score
            results.append((score, item))
        results.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in results[:max(1, int(limit))]]

    def upsert_current_state(self, *, world_id: str, branch_id: str | None, owner_type: str,
                             owner_id: str, state_key: str, value: Any, source_type: str,
                             source_id: str | None, authority: str) -> None:
        with self._lock, self.connection() as con:
            con.execute(
                "INSERT INTO current_state_projection(world_id,branch_id,owner_type,owner_id,state_key,value_json,source_type,source_id,authority,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(world_id,branch_id,owner_type,owner_id,state_key) DO UPDATE SET "
                "value_json=excluded.value_json,source_type=excluded.source_type,source_id=excluded.source_id,authority=excluded.authority,updated_at=excluded.updated_at",
                (world_id, branch_id, owner_type, owner_id, state_key, dumps(value), source_type, source_id, authority, utc_now()),
            )

    def query_current_state(self, world_id: str, branch_id: str | None, owner_type: str,
                            owner_id: str, state_key: str | None = None) -> list[dict[str, Any]]:
        where = ["world_id=?", "branch_id IS ?", "owner_type=?", "owner_id=?"]
        params: list[Any] = [world_id, branch_id, owner_type, owner_id]
        if state_key: where.append("state_key=?"); params.append(state_key)
        with self.connection() as con:
            rows = con.execute(f"SELECT * FROM current_state_projection WHERE {' AND '.join(where)} ORDER BY state_key", params).fetchall()
        result = []
        for row in rows:
            item = dict(row); item["value"] = loads(item.pop("value_json"), None); result.append(item)
        return result

    def add_state_interval(self, **values: Any) -> dict[str, Any]:
        interval_id = values.get("id") or make_id("STATEINT")
        with self._lock, self.connection() as con:
            con.execute(
                "INSERT INTO state_intervals(id,world_id,branch_id,owner_type,owner_id,state_key,value_json,valid_from_event_id,valid_to_event_id,"
                "valid_from_world_time_json,valid_to_world_time_json,story_order_from,story_order_to,source_type,source_id,authority,status,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (interval_id, values["world_id"], values.get("branch_id"), values["owner_type"], values["owner_id"], values["state_key"],
                 dumps(values.get("value")), values.get("valid_from_event_id"), values.get("valid_to_event_id"),
                 dumps(values.get("valid_from_world_time")) if values.get("valid_from_world_time") is not None else None,
                 dumps(values.get("valid_to_world_time")) if values.get("valid_to_world_time") is not None else None,
                 values.get("story_order_from"), values.get("story_order_to"), values.get("source_type", "manual"),
                 values.get("source_id"), values.get("authority", Authority.USER_ACCEPTED_WORLD_CANON.value),
                 values.get("status", "accepted"), utc_now()),
            )
        return self.get_state_interval(interval_id)

    def get_state_interval(self, interval_id: str) -> dict[str, Any]:
        with self.connection() as con:
            row = con.execute("SELECT * FROM state_intervals WHERE id=?", (interval_id,)).fetchone()
        if not row: raise KeyError(interval_id)
        item = dict(row); item["value"] = loads(item.pop("value_json"), None)
        item["valid_from_world_time"] = loads(item.pop("valid_from_world_time_json"), None)
        item["valid_to_world_time"] = loads(item.pop("valid_to_world_time_json"), None)
        return item

    def state_at(self, *, world_id: str, branch_id: str | None, owner_type: str,
                 owner_id: str, story_order: float | None = None) -> list[dict[str, Any]]:
        where = ["world_id=?", "branch_id IS ?", "owner_type=?", "owner_id=?", "status='accepted'"]
        params: list[Any] = [world_id, branch_id, owner_type, owner_id]
        if story_order is not None:
            where += ["(story_order_from IS NULL OR story_order_from<=?)", "(story_order_to IS NULL OR story_order_to>?)"]
            params += [story_order, story_order]
        with self.connection() as con:
            rows = con.execute(f"SELECT * FROM state_intervals WHERE {' AND '.join(where)} ORDER BY state_key,story_order_from DESC", params).fetchall()
        seen: set[str] = set(); result = []
        for row in rows:
            if row["state_key"] in seen: continue
            seen.add(row["state_key"]); result.append(self.get_state_interval(row["id"]))
        return result

    def create_spatial_edge(self, *, world_id: str, subject_type: str, subject_id: str,
                            relation: str, object_type: str, object_id: str, branch_id: str | None = None,
                            structural: bool = True, authority: str = Authority.USER_ACCEPTED_WORLD_CANON.value,
                            confidence: float = 1.0, source_type: str = "manual", source_id: str | None = None,
                            story_order_from: float | None = None, story_order_to: float | None = None) -> dict[str, Any]:
        if subject_type == object_type and subject_id == object_id:
            raise ValueError("A spatial edge cannot contain itself")
        edge_id = make_id("SPACE")
        now = utc_now()
        with self._lock, self.connection() as con:
            con.execute(
                "INSERT INTO spatial_edges(id,world_id,branch_id,subject_type,subject_id,relation,object_type,object_id,structural,"
                "story_order_from,story_order_to,authority,confidence,status,source_type,source_id,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'accepted',?,?,?,?)",
                (edge_id, world_id, branch_id, subject_type, subject_id, relation, object_type, object_id,
                 int(bool(structural)), story_order_from, story_order_to, authority, float(confidence), source_type, source_id, now, now),
            )
            con.execute(
                "INSERT OR REPLACE INTO current_spatial_index(world_id,branch_id,subject_type,subject_id,relation,object_type,object_id,source_edge_id,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (world_id, branch_id, subject_type, subject_id, relation, object_type, object_id, edge_id, now),
            )
        return self.get_spatial_edge(edge_id)

    def get_spatial_edge(self, edge_id: str) -> dict[str, Any]:
        with self.connection() as con:
            row = con.execute("SELECT * FROM spatial_edges WHERE id=?", (edge_id,)).fetchone()
        if not row: raise KeyError(edge_id)
        item = dict(row); item["structural"] = bool(item["structural"]); return item

    def list_spatial_edges(self, *, world_id: str, branch_id: str | None = None,
                           resource_type: str | None = None, resource_id: str | None = None,
                           relation: str | None = None) -> list[dict[str, Any]]:
        where = ["world_id=?", "(branch_id IS NULL OR branch_id IS ?)", "status='accepted'"]
        params: list[Any] = [world_id, branch_id]
        if resource_type and resource_id:
            where.append("((subject_type=? AND subject_id=?) OR (object_type=? AND object_id=?))")
            params += [resource_type, resource_id, resource_type, resource_id]
        if relation: where.append("relation=?"); params.append(relation)
        with self.connection() as con:
            rows = con.execute(f"SELECT * FROM spatial_edges WHERE {' AND '.join(where)} ORDER BY structural DESC,created_at", params).fetchall()
        return [{**dict(row), "structural": bool(row["structural"])} for row in rows]

    def delete_spatial_edge(self, edge_id: str) -> None:
        with self._lock, self.connection() as con:
            row = con.execute("SELECT * FROM spatial_edges WHERE id=?", (edge_id,)).fetchone()
            if not row: raise KeyError(edge_id)
            con.execute("DELETE FROM current_spatial_index WHERE source_edge_id=?", (edge_id,))
            con.execute("DELETE FROM spatial_edges WHERE id=?", (edge_id,))

    def spatial_neighborhood(self, *, world_id: str, branch_id: str | None,
                             resource_type: str, resource_id: str, depth: int = 2) -> dict[str, Any]:
        depth = max(0, min(8, int(depth)))
        nodes = {(resource_type, resource_id)}; frontier = {(resource_type, resource_id)}; edges: list[dict[str, Any]] = []
        for _ in range(depth):
            next_frontier: set[tuple[str, str]] = set()
            for node_type, node_id in frontier:
                for edge in self.list_spatial_edges(world_id=world_id, branch_id=branch_id, resource_type=node_type, resource_id=node_id):
                    if edge["id"] not in {item["id"] for item in edges}: edges.append(edge)
                    for pair in ((edge["subject_type"], edge["subject_id"]), (edge["object_type"], edge["object_id"])):
                        if pair not in nodes: nodes.add(pair); next_frontier.add(pair)
            frontier = next_frontier
            if not frontier: break
        return {"root": {"type": resource_type, "id": resource_id}, "nodes": [{"type": t, "id": i} for t, i in sorted(nodes)], "edges": edges}

    def upsert_epistemic_interval(self, **values: Any) -> dict[str, Any]:
        interval_id = values.get("id") or make_id("EPI")
        with self._lock, self.connection() as con:
            con.execute(
                "INSERT INTO epistemic_intervals(id,world_id,branch_id,character_variant_id,topic_type,topic_id,state_type,value_json,confidence,"
                "valid_from_event_id,valid_to_event_id,story_order_from,story_order_to,source_type,source_id,status,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'accepted',?)",
                (interval_id, values["world_id"], values.get("branch_id"), values["character_variant_id"],
                 values["topic_type"], values["topic_id"], values["state_type"], dumps(values.get("value")),
                 float(values.get("confidence", 1.0)), values.get("valid_from_event_id"), values.get("valid_to_event_id"),
                 values.get("story_order_from"), values.get("story_order_to"), values.get("source_type", "manual"),
                 values.get("source_id"), utc_now()),
            )
        return self.get_epistemic_interval(interval_id)

    def get_epistemic_interval(self, interval_id: str) -> dict[str, Any]:
        with self.connection() as con:
            row = con.execute("SELECT * FROM epistemic_intervals WHERE id=?", (interval_id,)).fetchone()
        if not row: raise KeyError(interval_id)
        item = dict(row); item["value"] = loads(item.pop("value_json"), None); return item

    def query_epistemic(self, *, world_id: str, branch_id: str | None, character_variant_id: str,
                        topic_type: str | None = None, topic_id: str | None = None,
                        story_order: float | None = None) -> list[dict[str, Any]]:
        where = ["world_id=?", "(branch_id IS NULL OR branch_id IS ?)", "character_variant_id=?", "status='accepted'"]
        params: list[Any] = [world_id, branch_id, character_variant_id]
        if topic_type: where.append("topic_type=?"); params.append(topic_type)
        if topic_id: where.append("topic_id=?"); params.append(topic_id)
        if story_order is not None:
            where += ["(story_order_from IS NULL OR story_order_from<=?)", "(story_order_to IS NULL OR story_order_to>?)"]
            params += [story_order, story_order]
        with self.connection() as con:
            rows = con.execute(f"SELECT * FROM epistemic_intervals WHERE {' AND '.join(where)} ORDER BY created_at DESC", params).fetchall()
        return [self.get_epistemic_interval(row["id"]) for row in rows]

    def create_thread(self, *, world_id: str, thread_type: str, title: str,
                      project_id: str | None = None, branch_id: str | None = None,
                      description: str = "", status: str = "open", links: list[dict[str, Any]] | None = None,
                      source_type: str = "manual", source_id: str | None = None) -> dict[str, Any]:
        thread_id = make_id("THREAD"); now = utc_now()
        with self._lock, self.connection() as con:
            con.execute(
                "INSERT INTO story_threads(id,project_id,world_id,branch_id,thread_type,title,description,status,authority,confidence,source_type,source_id,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?, ?,?,?)",
                (thread_id, project_id, world_id, branch_id, thread_type, title.strip(), description.strip(), status,
                 Authority.USER_ACCEPTED_WORLD_CANON.value, 1.0, source_type, source_id, now, now),
            )
            for link in links or []:
                con.execute(
                    "INSERT OR IGNORE INTO story_thread_links(thread_id,resource_type,resource_id,relation) VALUES(?,?,?,?)",
                    (thread_id, link["resource_type"], link["resource_id"], link.get("relation", "related")),
                )
        return self.get_thread(thread_id)

    def get_thread(self, thread_id: str) -> dict[str, Any]:
        with self.connection() as con:
            row = con.execute("SELECT * FROM story_threads WHERE id=?", (thread_id,)).fetchone()
            if not row: raise KeyError(thread_id)
            links = con.execute("SELECT * FROM story_thread_links WHERE thread_id=?", (thread_id,)).fetchall()
        return {**dict(row), "links": [dict(link) for link in links]}

    def list_threads(self, *, world_id: str, branch_id: str | None = None,
                     status: str | None = None, resource_type: str | None = None,
                     resource_id: str | None = None) -> list[dict[str, Any]]:
        where = ["t.world_id=?", "(t.branch_id IS NULL OR t.branch_id IS ?)"]
        params: list[Any] = [world_id, branch_id]
        join = ""
        if status: where.append("t.status=?"); params.append(status)
        if resource_type and resource_id:
            join = " JOIN story_thread_links l ON l.thread_id=t.id "
            where += ["l.resource_type=?", "l.resource_id=?"]; params += [resource_type, resource_id]
        with self.connection() as con:
            rows = con.execute(f"SELECT DISTINCT t.* FROM story_threads t {join} WHERE {' AND '.join(where)} ORDER BY t.updated_at DESC", params).fetchall()
        return [self.get_thread(row["id"]) for row in rows]

    def update_thread(self, thread_id: str, **changes: Any) -> dict[str, Any]:
        allowed = {"title", "description", "status", "resolved_event_id"}; fields=[]; params=[]
        for key, value in changes.items():
            if key in allowed and value is not None: fields.append(f"{key}=?"); params.append(value)
        if fields:
            fields.append("updated_at=?"); params += [utc_now(), thread_id]
            with self._lock, self.connection() as con:
                cur = con.execute(f"UPDATE story_threads SET {','.join(fields)} WHERE id=?", params)
                if not cur.rowcount: raise KeyError(thread_id)
        return self.get_thread(thread_id)

    def record_retrieval_run(self, *, run_id: str, query_text: str, route: str, scope: dict[str, Any],
                             plan: dict[str, Any], selected: list[dict[str, Any]], excluded: list[dict[str, Any]],
                             diagnostics: list[str], latency_ms: float) -> None:
        with self._lock, self.connection() as con:
            con.execute(
                "INSERT OR REPLACE INTO retrieval_runs(id,query_text,route,scope_json,plan_json,selected_json,excluded_json,diagnostics_json,latency_ms,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (run_id, query_text, route, dumps(scope), dumps(plan), dumps(selected), dumps(excluded), dumps(diagnostics), float(latency_ms), utc_now()),
            )

    def get_retrieval_run(self, run_id: str) -> dict[str, Any]:
        with self.connection() as con:
            row = con.execute("SELECT * FROM retrieval_runs WHERE id=?", (run_id,)).fetchone()
        if not row: raise KeyError(run_id)
        item = dict(row)
        for key in ("scope", "plan", "selected", "excluded", "diagnostics"):
            item[key] = loads(item.pop(f"{key}_json"), [] if key in {"selected", "excluded", "diagnostics"} else {})
        return item

    def status(self) -> dict[str, Any]:
        with self.connection() as con:
            counts = {
                "chunks": con.execute("SELECT COUNT(*) FROM memory_chunks WHERE semantic_status='active'").fetchone()[0],
                "links": con.execute("SELECT COUNT(*) FROM memory_links").fetchone()[0],
                "threads": con.execute("SELECT COUNT(*) FROM story_threads WHERE status IN ('open','developing')").fetchone()[0],
                "spatial_edges": con.execute("SELECT COUNT(*) FROM spatial_edges WHERE status='accepted'").fetchone()[0],
                "state_intervals": con.execute("SELECT COUNT(*) FROM state_intervals WHERE status='accepted'").fetchone()[0],
                "epistemic_intervals": con.execute("SELECT COUNT(*) FROM epistemic_intervals WHERE status='accepted'").fetchone()[0],
            }
        return {"schema_version": self.SCHEMA_VERSION, "fts_available": self.fts_available,
                "active_generation": self.active_generation(), **counts}
