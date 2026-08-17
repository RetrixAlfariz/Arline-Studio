from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Callable
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{prefix}-{stamp}-{uuid4().hex[:8].upper()}"


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


class FoundationStore:
    """v1.1 foundation services that sit across Library, Project and Chat.

    These tables deliberately hold cross-cutting UX/application concepts rather
    than embedding them into every domain table.  A resource can therefore be
    archived/trashed, favorited, collected, aliased, inspected, or surfaced as
    an issue without changing the canonical schema that owns its content.
    """

    SCHEMA_VERSION = 7

    def __init__(self, database_path: Path | str):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA busy_timeout = 30000")
        return con

    @contextmanager
    def _connection(self):
        con = self._connect()
        try:
            yield con
        finally:
            con.close()

    def _init_db(self) -> None:
        with self._lock, self._connection() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS workspace_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS resource_lifecycle (
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    archived_at TEXT,
                    trashed_at TEXT,
                    previous_state_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(resource_type, resource_id)
                );

                CREATE TABLE IF NOT EXISTS resource_aliases (
                    id TEXT PRIMARY KEY,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(resource_type, resource_id, normalized_alias)
                );
                CREATE INDEX IF NOT EXISTS idx_alias_lookup
                    ON resource_aliases(normalized_alias, resource_type);

                CREATE TABLE IF NOT EXISTS resource_media (
                    id TEXT PRIMARY KEY,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    media_type TEXT NOT NULL DEFAULT 'image',
                    kind TEXT NOT NULL DEFAULT 'reference',
                    mime_type TEXT NOT NULL,
                    original_name TEXT NOT NULL DEFAULT '',
                    storage_path TEXT NOT NULL,
                    caption TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    description_source TEXT NOT NULL DEFAULT 'manual',
                    is_cover INTEGER NOT NULL DEFAULT 0,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_resource_media_owner
                    ON resource_media(resource_type, resource_id, sort_order, created_at);


                CREATE TABLE IF NOT EXISTS workspace_collections (
                    id TEXT PRIMARY KEY,
                    scope_type TEXT NOT NULL DEFAULT 'world_bible',
                    scope_id TEXT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    icon TEXT NOT NULL DEFAULT '◇',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workspace_collection_links (
                    collection_id TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY(collection_id, resource_type, resource_id),
                    FOREIGN KEY(collection_id) REFERENCES workspace_collections(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS saved_views (
                    id TEXT PRIMARY KEY,
                    scope_type TEXT NOT NULL DEFAULT 'world_bible',
                    scope_id TEXT,
                    name TEXT NOT NULL,
                    resource_type TEXT NOT NULL DEFAULT 'all',
                    query_json TEXT NOT NULL DEFAULT '{}',
                    builtin INTEGER NOT NULL DEFAULT 0,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS run_profiles (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    profile_json TEXT NOT NULL DEFAULT '{}',
                    builtin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, name)
                );

                CREATE TABLE IF NOT EXISTS workspace_favorites (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    label TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, resource_type, resource_id)
                );

                CREATE TABLE IF NOT EXISTS workspace_activity (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    event_type TEXT NOT NULL,
                    resource_type TEXT,
                    resource_id TEXT,
                    label TEXT NOT NULL DEFAULT '',
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_activity_project
                    ON workspace_activity(project_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS workspace_issues (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    world_id TEXT,
                    branch_id TEXT,
                    issue_type TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'warning',
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    resource_type TEXT,
                    resource_id TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_issues_scope
                    ON workspace_issues(project_id, status, severity, updated_at DESC);

                CREATE TABLE IF NOT EXISTS workspace_jobs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    progress REAL NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS context_stack (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    world_id TEXT,
                    branch_id TEXT,
                    scene_document_id TEXT,
                    session_id TEXT,
                    recipe_id TEXT,
                    run_profile_id TEXT,
                    references_json TEXT NOT NULL DEFAULT '[]',
                    overrides_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workspace_preferences (
                    scope_type TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(scope_type, scope_id, key)
                );
                """
            )
            self._seed_views(con)
            self._seed_run_profiles(con)
            con.execute(
                "INSERT INTO workspace_meta(key,value) VALUES('schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(self.SCHEMA_VERSION),),
            )

    @staticmethod
    def _seed_views(con: sqlite3.Connection) -> None:
        now = utc_now()
        views = [
            ("VIEW-WB-ALL", "All", "all", {}, 0),
            ("VIEW-WB-CHAR", "Characters", "character", {}, 10),
            ("VIEW-WB-LOC", "Locations", "location", {}, 20),
            ("VIEW-WB-ITEM", "Items", "item", {}, 30),
            ("VIEW-WB-ORG", "Organizations", "organization", {}, 40),
            ("VIEW-WB-LORE", "Lore", "lore", {}, 50),
            ("VIEW-WB-RECENT", "Recently changed", "all", {"sort": "updated_at", "direction": "desc"}, 60),
            ("VIEW-WB-DETAIL", "Needs details", "all", {"description_empty": True}, 70),
        ]
        for view_id, name, resource_type, query, order in views:
            con.execute(
                "INSERT OR IGNORE INTO saved_views(id,scope_type,scope_id,name,resource_type,query_json,builtin,sort_order,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,1,?,?,?)",
                (view_id, "world_bible", None, name, resource_type, _dumps(query), order, now, now),
            )

    @staticmethod
    def _seed_run_profiles(con: sqlite3.Connection) -> None:
        now = utc_now()
        profiles = [
            ("PROFILE-STORY", "Story Writing", "Balanced long-form prose with scene, canon, and recent continuity.", {
                "context_recipe_id": "RECIPE-STORY", "input_mode": "smart_hybrid", "reasoning": "off",
                "visible_output_tokens": 4096, "temperature": 0.8, "generation_mode": "single",
            }),
            ("PROFILE-DIALOGUE", "Dialogue", "Character voice and relationship-heavy dialogue.", {
                "context_recipe_id": "RECIPE-DIALOGUE", "input_mode": "smart_hybrid", "reasoning": "off",
                "visible_output_tokens": 2048, "temperature": 0.85, "generation_mode": "single",
            }),
            ("PROFILE-LORE", "Lore Analysis", "Deeper world-state and canon inspection.", {
                "context_recipe_id": "RECIPE-LORE", "input_mode": "smart_hybrid", "reasoning": "on",
                "visible_output_tokens": 4096, "temperature": 0.55, "generation_mode": "single",
            }),
            ("PROFILE-FAST", "Fast Brainstorm", "Cheap, short exploratory generation.", {
                "context_recipe_id": "RECIPE-STORY", "input_mode": "smart_hybrid", "reasoning": "off",
                "visible_output_tokens": 1024, "temperature": 1.0, "generation_mode": "single",
            }),
        ]
        profile_defaults = {
            "projection_mode": "balanced", "reasoning_reserve_tokens": 4096,
            "top_p": 0.95, "top_k": 40, "min_p": 0.0, "repeat_penalty": 1.05,
            "generation_mode": "single", "beat_count": 4, "beat_tokens": 2048,
            "total_story_target_tokens": 8192,
        }
        for profile_id, name, description, data in profiles:
            data = {**profile_defaults, **data}
            con.execute(
                "INSERT OR IGNORE INTO run_profiles(id,project_id,name,description,profile_json,builtin,created_at,updated_at) "
                "VALUES(?,NULL,?,?,?,1,?,?)",
                (profile_id, name, description, _dumps(data), now, now),
            )

    # ------------------------------------------------------------------
    # Lifecycle / safety
    # ------------------------------------------------------------------

    def lifecycle(self, resource_type: str, resource_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute(
                "SELECT * FROM resource_lifecycle WHERE resource_type=? AND resource_id=?",
                (resource_type, resource_id),
            ).fetchone()
        if not row:
            return {"resource_type": resource_type, "resource_id": resource_id, "archived_at": None, "trashed_at": None}
        result = dict(row)
        result["previous_state"] = _loads(result.pop("previous_state_json"), {})
        return result

    def set_lifecycle(self, resource_type: str, resource_id: str, *, archived: bool | None = None, trashed: bool | None = None, previous_state: dict[str, Any] | None = None) -> dict[str, Any]:
        now = utc_now()
        current = self.lifecycle(resource_type, resource_id)
        archived_at = current.get("archived_at")
        trashed_at = current.get("trashed_at")
        if archived is not None:
            archived_at = now if archived else None
        if trashed is not None:
            trashed_at = now if trashed else None
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT INTO resource_lifecycle(resource_type,resource_id,archived_at,trashed_at,previous_state_json,updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(resource_type,resource_id) DO UPDATE SET "
                "archived_at=excluded.archived_at,trashed_at=excluded.trashed_at,previous_state_json=excluded.previous_state_json,updated_at=excluded.updated_at",
                (resource_type, resource_id, archived_at, trashed_at, _dumps(previous_state or current.get("previous_state") or {}), now),
            )
        return self.lifecycle(resource_type, resource_id)

    def trash(self, resource_type: str, resource_id: str, *, previous_state: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.set_lifecycle(resource_type, resource_id, trashed=True, previous_state=previous_state)
        self.log_activity(None, "trashed", resource_type, resource_id)
        return result

    def restore(self, resource_type: str, resource_id: str) -> dict[str, Any]:
        result = self.set_lifecycle(resource_type, resource_id, trashed=False)
        self.log_activity(None, "restored", resource_type, resource_id)
        return result

    def archive(self, resource_type: str, resource_id: str, archived: bool = True) -> dict[str, Any]:
        result = self.set_lifecycle(resource_type, resource_id, archived=archived)
        self.log_activity(None, "archived" if archived else "unarchived", resource_type, resource_id)
        return result

    def is_hidden(self, resource_type: str, resource_id: str, *, include_archived: bool = False, include_trashed: bool = False) -> bool:
        state = self.lifecycle(resource_type, resource_id)
        return (bool(state.get("trashed_at")) and not include_trashed) or (bool(state.get("archived_at")) and not include_archived)

    def list_trash(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._connection() as con:
            rows = con.execute(
                "SELECT * FROM resource_lifecycle WHERE trashed_at IS NOT NULL ORDER BY trashed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._lifecycle_row(row) for row in rows]

    @staticmethod
    def _lifecycle_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["previous_state"] = _loads(item.pop("previous_state_json"), {})
        return item

    def filter_visible(self, resource_type: str, rows: list[dict[str, Any]], *, id_key: str = "id", include_archived: bool = False) -> list[dict[str, Any]]:
        if not rows:
            return rows
        ids = [str(item.get(id_key) or "") for item in rows if item.get(id_key)]
        if not ids:
            return rows
        marks: dict[str, tuple[str | None, str | None]] = {}
        with self._connection() as con:
            for start in range(0, len(ids), 800):
                chunk = ids[start:start + 800]
                placeholders = ",".join("?" for _ in chunk)
                found = con.execute(
                    f"SELECT resource_id,archived_at,trashed_at FROM resource_lifecycle WHERE resource_type=? AND resource_id IN ({placeholders})",
                    [resource_type, *chunk],
                ).fetchall()
                marks.update({row["resource_id"]: (row["archived_at"], row["trashed_at"]) for row in found})
        visible = []
        for item in rows:
            archived_at, trashed_at = marks.get(str(item.get(id_key)), (None, None))
            if trashed_at or (archived_at and not include_archived):
                continue
            item = dict(item)
            item["lifecycle"] = {"archived_at": archived_at, "trashed_at": trashed_at}
            visible.append(item)
        return visible

    def forget_resource(self, resource_type: str, resource_id: str) -> None:
        """Remove cross-cutting metadata after a permanent domain delete.

        Activity is intentionally retained as an audit trail; live pointers are
        removed so context/search/collections cannot retain zombie references.
        """
        with self._lock, self._connection() as con:
            media_rows = con.execute("SELECT storage_path FROM resource_media WHERE resource_type=? AND resource_id=?", (resource_type, resource_id)).fetchall()
            for media in media_rows:
                try:
                    Path(media["storage_path"]).unlink(missing_ok=True)
                except OSError:
                    pass
            con.execute("DELETE FROM resource_media WHERE resource_type=? AND resource_id=?", (resource_type, resource_id))
            con.execute("DELETE FROM resource_lifecycle WHERE resource_type=? AND resource_id=?", (resource_type, resource_id))
            con.execute("DELETE FROM resource_aliases WHERE resource_type=? AND resource_id=?", (resource_type, resource_id))
            con.execute("DELETE FROM workspace_collection_links WHERE resource_type=? AND resource_id=?", (resource_type, resource_id))
            con.execute("DELETE FROM workspace_favorites WHERE resource_type=? AND resource_id=?", (resource_type, resource_id))
            con.execute("DELETE FROM workspace_issues WHERE resource_type=? AND resource_id=?", (resource_type, resource_id))
            stacks = con.execute("SELECT id,references_json FROM context_stack").fetchall()
            for row in stacks:
                refs = _loads(row["references_json"], [])
                filtered = [ref for ref in refs if not (ref.get("type") == resource_type and ref.get("id") == resource_id)]
                if len(filtered) != len(refs):
                    con.execute("UPDATE context_stack SET references_json=?,updated_at=? WHERE id=?", (_dumps(filtered), utc_now(), row["id"]))

    def merge_resource_refs(self, resource_type: str, source_id: str, target_id: str) -> None:
        if source_id == target_id:
            return
        with self._lock, self._connection() as con:
            # aliases
            aliases = con.execute("SELECT alias,normalized_alias,created_at FROM resource_aliases WHERE resource_type=? AND resource_id=?", (resource_type, source_id)).fetchall()
            for row in aliases:
                con.execute("INSERT OR IGNORE INTO resource_aliases(id,resource_type,resource_id,alias,normalized_alias,created_at) VALUES(?,?,?,?,?,?)", (make_id("ALIAS"), resource_type, target_id, row["alias"], row["normalized_alias"], row["created_at"]))
            con.execute("DELETE FROM resource_aliases WHERE resource_type=? AND resource_id=?", (resource_type, source_id))
            target_cover = con.execute("SELECT id FROM resource_media WHERE resource_type=? AND resource_id=? AND is_cover=1 LIMIT 1", (resource_type, target_id)).fetchone()
            if target_cover:
                con.execute("UPDATE resource_media SET is_cover=0,updated_at=? WHERE resource_type=? AND resource_id=? AND is_cover=1", (utc_now(), resource_type, source_id))
            con.execute("UPDATE resource_media SET resource_id=?,updated_at=? WHERE resource_type=? AND resource_id=?", (target_id, utc_now(), resource_type, source_id))
            # collections
            links = con.execute("SELECT collection_id,sort_order,added_at FROM workspace_collection_links WHERE resource_type=? AND resource_id=?", (resource_type, source_id)).fetchall()
            for row in links:
                con.execute("INSERT OR IGNORE INTO workspace_collection_links(collection_id,resource_type,resource_id,sort_order,added_at) VALUES(?,?,?,?,?)", (row["collection_id"], resource_type, target_id, row["sort_order"], row["added_at"]))
            con.execute("DELETE FROM workspace_collection_links WHERE resource_type=? AND resource_id=?", (resource_type, source_id))
            # favorites/issues point to the surviving identity.
            favorites = con.execute("SELECT project_id,label,created_at FROM workspace_favorites WHERE resource_type=? AND resource_id=?", (resource_type, source_id)).fetchall()
            for row in favorites:
                con.execute("INSERT OR IGNORE INTO workspace_favorites(id,project_id,resource_type,resource_id,label,created_at) VALUES(?,?,?,?,?,?)", (make_id("FAV"), row["project_id"], resource_type, target_id, row["label"], row["created_at"]))
            con.execute("DELETE FROM workspace_favorites WHERE resource_type=? AND resource_id=?", (resource_type, source_id))
            con.execute("UPDATE workspace_issues SET resource_id=?,updated_at=? WHERE resource_type=? AND resource_id=?", (target_id, utc_now(), resource_type, source_id))
            # context stacks are JSON, so retarget and deduplicate explicit refs.
            rows = con.execute("SELECT id,references_json FROM context_stack").fetchall()
            for row in rows:
                refs = _loads(row["references_json"], [])
                changed = False; seen = set(); out = []
                for ref in refs:
                    item = dict(ref)
                    if item.get("type") == resource_type and item.get("id") == source_id:
                        item["id"] = target_id; changed = True
                    key = (item.get("type"), item.get("id"), item.get("mode"))
                    if key in seen: continue
                    seen.add(key); out.append(item)
                if changed:
                    con.execute("UPDATE context_stack SET references_json=?,updated_at=? WHERE id=?", (_dumps(out), utc_now(), row["id"]))
            con.execute("DELETE FROM resource_lifecycle WHERE resource_type=? AND resource_id=?", (resource_type, source_id))

    # ------------------------------------------------------------------
    # Identity / aliases
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_alias(alias: str) -> str:
        return " ".join(alias.casefold().strip().split())

    def add_alias(self, resource_type: str, resource_id: str, alias: str) -> dict[str, Any]:
        alias = alias.strip()
        if not alias:
            raise ValueError("Alias cannot be blank")
        normalized = self._normalize_alias(alias)
        alias_id = make_id("ALIAS")
        now = utc_now()
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT INTO resource_aliases(id,resource_type,resource_id,alias,normalized_alias,created_at) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(resource_type,resource_id,normalized_alias) DO UPDATE SET alias=excluded.alias",
                (alias_id, resource_type, resource_id, alias, normalized, now),
            )
            row = con.execute(
                "SELECT * FROM resource_aliases WHERE resource_type=? AND resource_id=? AND normalized_alias=?",
                (resource_type, resource_id, normalized),
            ).fetchone()
        return dict(row)

    def list_aliases(self, resource_type: str, resource_id: str) -> list[dict[str, Any]]:
        with self._connection() as con:
            rows = con.execute(
                "SELECT * FROM resource_aliases WHERE resource_type=? AND resource_id=? ORDER BY alias COLLATE NOCASE",
                (resource_type, resource_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_alias(self, alias_id: str) -> None:
        with self._lock, self._connection() as con:
            cur = con.execute("DELETE FROM resource_aliases WHERE id=?", (alias_id,))
            if not cur.rowcount:
                raise KeyError(alias_id)

    def alias_matches(self, query: str, limit: int = 30) -> list[dict[str, Any]]:
        q = self._normalize_alias(query)
        if not q:
            return []
        with self._connection() as con:
            rows = con.execute(
                "SELECT * FROM resource_aliases WHERE normalized_alias LIKE ? ORDER BY LENGTH(normalized_alias),alias COLLATE NOCASE LIMIT ?",
                (f"%{q}%", limit),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Collections / saved views
    # ------------------------------------------------------------------

    def create_collection(self, name: str, *, scope_type: str = "world_bible", scope_id: str | None = None, description: str = "", icon: str = "◇") -> dict[str, Any]:
        collection_id = make_id("COLL")
        now = utc_now()
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT INTO workspace_collections(id,scope_type,scope_id,name,description,icon,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (collection_id, scope_type, scope_id, name.strip(), description.strip(), icon or "◇", now, now),
            )
        return self.get_collection(collection_id)

    def get_collection(self, collection_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT * FROM workspace_collections WHERE id=?", (collection_id,)).fetchone()
            if row is None:
                raise KeyError(collection_id)
            links = con.execute(
                "SELECT * FROM workspace_collection_links WHERE collection_id=? ORDER BY sort_order,added_at",
                (collection_id,),
            ).fetchall()
        result = dict(row)
        result["links"] = [dict(item) for item in links]
        return result

    def list_collections(self, *, scope_type: str = "world_bible", scope_id: str | None = None) -> list[dict[str, Any]]:
        with self._connection() as con:
            rows = con.execute(
                "SELECT * FROM workspace_collections WHERE scope_type=? AND (scope_id IS ? OR scope_id=?) ORDER BY sort_order,name COLLATE NOCASE",
                (scope_type, scope_id, scope_id),
            ).fetchall()
            links = con.execute("SELECT * FROM workspace_collection_links").fetchall()
        by_collection: dict[str, list[dict[str, Any]]] = {}
        for link in links:
            by_collection.setdefault(link["collection_id"], []).append(dict(link))
        return [{**dict(row), "links": by_collection.get(row["id"], [])} for row in rows]

    def add_to_collection(self, collection_id: str, resource_type: str, resource_id: str, sort_order: int = 0) -> None:
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT OR REPLACE INTO workspace_collection_links(collection_id,resource_type,resource_id,sort_order,added_at) VALUES(?,?,?,?,?)",
                (collection_id, resource_type, resource_id, sort_order, utc_now()),
            )

    def remove_from_collection(self, collection_id: str, resource_type: str, resource_id: str) -> None:
        with self._lock, self._connection() as con:
            con.execute(
                "DELETE FROM workspace_collection_links WHERE collection_id=? AND resource_type=? AND resource_id=?",
                (collection_id, resource_type, resource_id),
            )

    def delete_collection(self, collection_id: str) -> None:
        with self._lock, self._connection() as con:
            cur = con.execute("DELETE FROM workspace_collections WHERE id=?", (collection_id,))
            if not cur.rowcount:
                raise KeyError(collection_id)

    def list_saved_views(self, *, scope_type: str = "world_bible", scope_id: str | None = None) -> list[dict[str, Any]]:
        with self._connection() as con:
            rows = con.execute(
                "SELECT * FROM saved_views WHERE scope_type=? AND (scope_id IS ? OR scope_id=?) ORDER BY sort_order,name COLLATE NOCASE",
                (scope_type, scope_id, scope_id),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["query"] = _loads(item.pop("query_json"), {})
            item["builtin"] = bool(item["builtin"])
            result.append(item)
        return result

    def save_view(self, name: str, *, scope_type: str = "world_bible", scope_id: str | None = None, resource_type: str = "all", query: dict[str, Any] | None = None) -> dict[str, Any]:
        view_id = make_id("VIEW")
        now = utc_now()
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT INTO saved_views(id,scope_type,scope_id,name,resource_type,query_json,builtin,created_at,updated_at) VALUES(?,?,?,?,?,?,0,?,?)",
                (view_id, scope_type, scope_id, name.strip(), resource_type, _dumps(query or {}), now, now),
            )
        return next(item for item in self.list_saved_views(scope_type=scope_type, scope_id=scope_id) if item["id"] == view_id)

    def delete_view(self, view_id: str) -> None:
        with self._lock, self._connection() as con:
            row = con.execute("SELECT builtin FROM saved_views WHERE id=?", (view_id,)).fetchone()
            if not row:
                raise KeyError(view_id)
            if row["builtin"]:
                raise ValueError("Built-in views are protected")
            con.execute("DELETE FROM saved_views WHERE id=?", (view_id,))


    # ------------------------------------------------------------------
    # Media / Gallery foundation
    # ------------------------------------------------------------------

    @staticmethod
    def _media_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["is_cover"] = bool(item.get("is_cover"))
        return item

    def create_media(
        self,
        resource_type: str,
        resource_id: str,
        *,
        storage_path: str,
        mime_type: str,
        original_name: str = "",
        media_type: str = "image",
        kind: str = "reference",
        caption: str = "",
        description: str = "",
        description_source: str = "manual",
        is_cover: bool = False,
        sort_order: int = 0,
    ) -> dict[str, Any]:
        media_id = make_id("MEDIA")
        now = utc_now()
        if not resource_type.strip() or not resource_id.strip():
            raise ValueError("Media must belong to a resource")
        with self._lock, self._connection() as con:
            if is_cover:
                con.execute(
                    "UPDATE resource_media SET is_cover=0,updated_at=? WHERE resource_type=? AND resource_id=?",
                    (now, resource_type, resource_id),
                )
            con.execute(
                "INSERT INTO resource_media(id,resource_type,resource_id,media_type,kind,mime_type,original_name,storage_path,caption,description,description_source,is_cover,sort_order,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    media_id, resource_type, resource_id, media_type, kind, mime_type,
                    original_name, storage_path, caption.strip(), description.strip(),
                    description_source.strip() or "manual", int(bool(is_cover)), int(sort_order), now, now,
                ),
            )
        return self.get_media(media_id)

    def get_media(self, media_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT * FROM resource_media WHERE id=?", (media_id,)).fetchone()
        if row is None:
            raise KeyError(media_id)
        return self._media_row(row)

    def list_media(
        self,
        *,
        resource_type: str | None = None,
        resource_id: str | None = None,
        cover_only: bool = False,
    ) -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []
        if resource_type:
            where.append("resource_type=?"); params.append(resource_type)
        if resource_id:
            where.append("resource_id=?"); params.append(resource_id)
        if cover_only:
            where.append("is_cover=1")
        with self._connection() as con:
            rows = con.execute(
                f"SELECT * FROM resource_media WHERE {' AND '.join(where)} ORDER BY is_cover DESC,sort_order ASC,created_at ASC",
                params,
            ).fetchall()
        return [self._media_row(row) for row in rows]

    def update_media(self, media_id: str, **changes: Any) -> dict[str, Any]:
        allowed = {"kind", "caption", "description", "description_source", "is_cover", "sort_order"}
        current = self.get_media(media_id)
        now = utc_now()
        with self._lock, self._connection() as con:
            if changes.get("is_cover") is True:
                con.execute(
                    "UPDATE resource_media SET is_cover=0,updated_at=? WHERE resource_type=? AND resource_id=?",
                    (now, current["resource_type"], current["resource_id"]),
                )
            fields: list[str] = []
            params: list[Any] = []
            for key, value in changes.items():
                if key not in allowed or value is None:
                    continue
                if key == "is_cover":
                    value = int(bool(value))
                elif key == "sort_order":
                    value = int(value)
                fields.append(f"{key}=?"); params.append(value)
            if fields:
                fields.append("updated_at=?"); params.extend([now, media_id])
                cur = con.execute(f"UPDATE resource_media SET {', '.join(fields)} WHERE id=?", params)
                if not cur.rowcount:
                    raise KeyError(media_id)
        return self.get_media(media_id)

    def delete_media(self, media_id: str) -> None:
        item = self.get_media(media_id)
        with self._lock, self._connection() as con:
            con.execute("DELETE FROM resource_media WHERE id=?", (media_id,))
        try:
            Path(item["storage_path"]).unlink(missing_ok=True)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Run profiles
    # ------------------------------------------------------------------

    def list_run_profiles(self, project_id: str | None = None) -> list[dict[str, Any]]:
        with self._connection() as con:
            rows = con.execute(
                "SELECT * FROM run_profiles WHERE project_id IS NULL OR project_id=? ORDER BY builtin DESC,name COLLATE NOCASE",
                (project_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["profile"] = _loads(item.pop("profile_json"), {})
            item["builtin"] = bool(item["builtin"])
            result.append(item)
        return result

    def save_run_profile(self, name: str, profile: dict[str, Any], *, project_id: str | None = None, description: str = "", profile_id: str | None = None) -> dict[str, Any]:
        now = utc_now()
        profile_id = profile_id or make_id("PROFILE")
        with self._lock, self._connection() as con:
            existing = con.execute("SELECT builtin FROM run_profiles WHERE id=?", (profile_id,)).fetchone()
            if existing and existing["builtin"]:
                raise ValueError("Built-in profiles cannot be overwritten")
            con.execute(
                "INSERT INTO run_profiles(id,project_id,name,description,profile_json,builtin,created_at,updated_at) VALUES(?,?,?,?,?,0,?,?) "
                "ON CONFLICT(id) DO UPDATE SET project_id=excluded.project_id,name=excluded.name,description=excluded.description,profile_json=excluded.profile_json,updated_at=excluded.updated_at",
                (profile_id, project_id, name.strip(), description.strip(), _dumps(profile), now, now),
            )
        return next(item for item in self.list_run_profiles(project_id) if item["id"] == profile_id)

    def delete_run_profile(self, profile_id: str) -> None:
        with self._lock, self._connection() as con:
            row = con.execute("SELECT builtin FROM run_profiles WHERE id=?", (profile_id,)).fetchone()
            if not row:
                raise KeyError(profile_id)
            if row["builtin"]:
                raise ValueError("Built-in profiles are protected")
            con.execute("DELETE FROM run_profiles WHERE id=?", (profile_id,))

    # ------------------------------------------------------------------
    # Favorites / activity / issues / jobs
    # ------------------------------------------------------------------

    def favorite(self, project_id: str | None, resource_type: str, resource_id: str, label: str = "") -> dict[str, Any]:
        favorite_id = make_id("FAV")
        now = utc_now()
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT INTO workspace_favorites(id,project_id,resource_type,resource_id,label,created_at) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(project_id,resource_type,resource_id) DO UPDATE SET label=excluded.label",
                (favorite_id, project_id, resource_type, resource_id, label, now),
            )
            row = con.execute(
                "SELECT * FROM workspace_favorites WHERE project_id IS ? AND resource_type=? AND resource_id=?",
                (project_id, resource_type, resource_id),
            ).fetchone()
        return dict(row)

    def unfavorite(self, project_id: str | None, resource_type: str, resource_id: str) -> None:
        with self._lock, self._connection() as con:
            con.execute(
                "DELETE FROM workspace_favorites WHERE project_id IS ? AND resource_type=? AND resource_id=?",
                (project_id, resource_type, resource_id),
            )

    def list_favorites(self, project_id: str | None = None) -> list[dict[str, Any]]:
        with self._connection() as con:
            rows = con.execute(
                "SELECT * FROM workspace_favorites WHERE project_id IS ? OR project_id IS NULL ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def log_activity(self, project_id: str | None, event_type: str, resource_type: str | None = None, resource_id: str | None = None, *, label: str = "", detail: dict[str, Any] | None = None) -> dict[str, Any]:
        activity_id = make_id("ACT")
        now = utc_now()
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT INTO workspace_activity(id,project_id,event_type,resource_type,resource_id,label,detail_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (activity_id, project_id, event_type, resource_type, resource_id, label, _dumps(detail or {}), now),
            )
        return {"id": activity_id, "project_id": project_id, "event_type": event_type, "resource_type": resource_type, "resource_id": resource_id, "label": label, "detail": detail or {}, "created_at": now}

    def list_activity(self, project_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._connection() as con:
            if project_id:
                rows = con.execute(
                    "SELECT * FROM workspace_activity WHERE project_id=? OR project_id IS NULL ORDER BY created_at DESC LIMIT ?",
                    (project_id, limit),
                ).fetchall()
            else:
                rows = con.execute("SELECT * FROM workspace_activity ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["detail"] = _loads(item.pop("detail_json"), {})
            result.append(item)
        return result

    def create_issue(self, issue_type: str, title: str, *, project_id: str | None = None, world_id: str | None = None, branch_id: str | None = None, severity: str = "warning", description: str = "", resource_type: str | None = None, resource_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        issue_id = make_id("ISSUE")
        now = utc_now()
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT INTO workspace_issues(id,project_id,world_id,branch_id,issue_type,severity,title,description,resource_type,resource_id,status,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?, 'open',?,?,?)",
                (issue_id, project_id, world_id, branch_id, issue_type, severity, title, description, resource_type, resource_id, _dumps(payload or {}), now, now),
            )
        return self.get_issue(issue_id)

    def get_issue(self, issue_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT * FROM workspace_issues WHERE id=?", (issue_id,)).fetchone()
        if not row:
            raise KeyError(issue_id)
        item = dict(row)
        item["payload"] = _loads(item.pop("payload_json"), {})
        return item

    def list_issues(self, *, project_id: str | None = None, world_id: str | None = None, branch_id: str | None = None, status: str | None = "open", limit: int = 200) -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []
        if project_id:
            where.append("project_id=?")
            params.append(project_id)
        if world_id:
            where.append("(world_id IS NULL OR world_id=?)")
            params.append(world_id)
        if branch_id:
            where.append("(branch_id IS NULL OR branch_id=?)")
            params.append(branch_id)
        if status:
            where.append("status=?")
            params.append(status)
        params.append(limit)
        with self._connection() as con:
            rows = con.execute(
                f"SELECT * FROM workspace_issues WHERE {' AND '.join(where)} ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = _loads(item.pop("payload_json"), {})
            result.append(item)
        return result

    def resolve_issue(self, issue_id: str, *, status: str = "resolved") -> dict[str, Any]:
        with self._lock, self._connection() as con:
            cur = con.execute("UPDATE workspace_issues SET status=?,updated_at=? WHERE id=?", (status, utc_now(), issue_id))
            if not cur.rowcount:
                raise KeyError(issue_id)
        return self.get_issue(issue_id)

    def create_job(self, job_type: str, *, project_id: str | None = None, payload: dict[str, Any] | None = None, message: str = "") -> dict[str, Any]:
        job_id = make_id("JOB")
        now = utc_now()
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT INTO workspace_jobs(id,project_id,job_type,status,progress,message,payload_json,result_json,created_at,updated_at) VALUES(?,?,?,'queued',0,?,?,'{}',?,?)",
                (job_id, project_id, job_type, message, _dumps(payload or {}), now, now),
            )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT * FROM workspace_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        item = dict(row)
        item["payload"] = _loads(item.pop("payload_json"), {})
        item["result"] = _loads(item.pop("result_json"), {})
        return item

    def update_job(self, job_id: str, *, status: str | None = None, progress: float | None = None, message: str | None = None, result: dict[str, Any] | None = None) -> dict[str, Any]:
        fields = []
        params: list[Any] = []
        if status is not None:
            fields.append("status=?"); params.append(status)
        if progress is not None:
            fields.append("progress=?"); params.append(max(0.0, min(1.0, float(progress))))
        if message is not None:
            fields.append("message=?"); params.append(message)
        if result is not None:
            fields.append("result_json=?"); params.append(_dumps(result))
        if fields:
            fields.append("updated_at=?"); params.extend([utc_now(), job_id])
            with self._lock, self._connection() as con:
                cur = con.execute(f"UPDATE workspace_jobs SET {', '.join(fields)} WHERE id=?", params)
                if not cur.rowcount:
                    raise KeyError(job_id)
        return self.get_job(job_id)

    def list_jobs(self, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._connection() as con:
            if project_id:
                rows = con.execute("SELECT id FROM workspace_jobs WHERE project_id=? ORDER BY updated_at DESC LIMIT ?", (project_id, limit)).fetchall()
            else:
                rows = con.execute("SELECT id FROM workspace_jobs ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [self.get_job(row["id"]) for row in rows]

    # ------------------------------------------------------------------
    # Canonical Context Stack / preferences
    # ------------------------------------------------------------------

    def get_context_stack(self, stack_id: str = "default") -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT * FROM context_stack WHERE id=?", (stack_id,)).fetchone()
        if not row:
            return {"id": stack_id, "project_id": None, "world_id": None, "branch_id": None, "scene_document_id": None, "session_id": None, "recipe_id": None, "run_profile_id": None, "references": [], "overrides": {}, "updated_at": None}
        item = dict(row)
        item["references"] = _loads(item.pop("references_json"), [])
        item["overrides"] = _loads(item.pop("overrides_json"), {})
        return item

    def set_context_stack(self, *, stack_id: str = "default", project_id: str | None = None, world_id: str | None = None, branch_id: str | None = None, scene_document_id: str | None = None, session_id: str | None = None, recipe_id: str | None = None, run_profile_id: str | None = None, references: list[dict[str, Any]] | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        now = utc_now()
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT INTO context_stack(id,project_id,world_id,branch_id,scene_document_id,session_id,recipe_id,run_profile_id,references_json,overrides_json,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET project_id=excluded.project_id,world_id=excluded.world_id,branch_id=excluded.branch_id,scene_document_id=excluded.scene_document_id,session_id=excluded.session_id,recipe_id=excluded.recipe_id,run_profile_id=excluded.run_profile_id,references_json=excluded.references_json,overrides_json=excluded.overrides_json,updated_at=excluded.updated_at",
                (stack_id, project_id, world_id, branch_id, scene_document_id, session_id, recipe_id, run_profile_id, _dumps(references or []), _dumps(overrides or {}), now),
            )
        return self.get_context_stack(stack_id)

    def get_preferences(self, scope_type: str, scope_id: str) -> dict[str, Any]:
        with self._connection() as con:
            rows = con.execute("SELECT key,value_json FROM workspace_preferences WHERE scope_type=? AND scope_id=?", (scope_type, scope_id)).fetchall()
        return {row["key"]: _loads(row["value_json"], None) for row in rows}

    def set_preference(self, scope_type: str, scope_id: str, key: str, value: Any) -> None:
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT INTO workspace_preferences(scope_type,scope_id,key,value_json,updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(scope_type,scope_id,key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
                (scope_type, scope_id, key, _dumps(value), utc_now()),
            )
