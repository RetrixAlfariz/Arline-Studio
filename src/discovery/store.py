from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any
from uuid import uuid4

from src.storage_backup import backup_sqlite_before_migrations


DISCOVERY_SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{prefix}-{stamp}-{uuid4().hex[:8].upper()}"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


def loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def proposition_key(*, project_id: str | None, world_id: str | None, subject_type: str,
                    subject_key: str, predicate: str, value: Any, object_key: str | None,
                    operation: str) -> str:
    payload = [
        project_id or "", world_id or "", subject_type.casefold(), subject_key.casefold(),
        predicate.casefold(), value, (object_key or "").casefold(), operation.casefold(),
    ]
    return hashlib.sha256(dumps(payload).encode("utf-8")).hexdigest()


class DiscoveryStore:
    """Persistent evidence-to-truth bridge for indirect Library capture.

    Propositions are stable semantic statements. Discovery instances are the
    individual source-backed observations supporting them. `reviewed` is not
    stored here because it is lineage-dependent and is derived at query time.
    Only explicit user decisions are persisted as canon/dismissed authority.
    """

    SCHEMA_VERSION = DISCOVERY_SCHEMA_VERSION

    def __init__(self, database_path: Path | str, *, backup_before_migration: bool = True):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        if backup_before_migration:
            backup_sqlite_before_migrations(self.path, {"discovery_meta": self.SCHEMA_VERSION})
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
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS discovery_meta(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS discovery_propositions(
                    id TEXT PRIMARY KEY,
                    proposition_key TEXT NOT NULL UNIQUE,
                    project_id TEXT,
                    world_id TEXT,
                    subject_type TEXT NOT NULL,
                    subject_key TEXT NOT NULL,
                    subject_label TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    value_json TEXT,
                    object_type TEXT,
                    object_key TEXT,
                    object_label TEXT,
                    operation TEXT NOT NULL,
                    authority_state TEXT NOT NULL DEFAULT 'observed',
                    temporal_state TEXT NOT NULL DEFAULT 'current_or_unspecified',
                    target_resource_type TEXT,
                    target_resource_id TEXT,
                    materialized_resource_type TEXT,
                    materialized_resource_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    promoted_at TEXT,
                    CHECK(authority_state IN ('observed','canon','dismissed'))
                );
                CREATE INDEX IF NOT EXISTS idx_discovery_prop_scope
                    ON discovery_propositions(project_id,world_id,authority_state,updated_at);
                CREATE INDEX IF NOT EXISTS idx_discovery_prop_subject
                    ON discovery_propositions(subject_type,subject_key,predicate);

                CREATE TABLE IF NOT EXISTS discovery_instances(
                    id TEXT PRIMARY KEY,
                    instance_key TEXT NOT NULL UNIQUE,
                    proposition_id TEXT NOT NULL REFERENCES discovery_propositions(id) ON DELETE CASCADE,
                    source_kind TEXT NOT NULL,
                    source_session_id TEXT,
                    source_turn_id TEXT,
                    origin_session_id TEXT,
                    origin_turn_id TEXT,
                    source_revision TEXT NOT NULL,
                    project_id TEXT,
                    world_id TEXT,
                    branch_id TEXT,
                    world_time_json TEXT,
                    story_order REAL,
                    source_segment TEXT,
                    span_start INTEGER,
                    span_end INTEGER,
                    span_text TEXT NOT NULL DEFAULT '',
                    extraction_confidence REAL NOT NULL DEFAULT 1.0,
                    explicitness TEXT NOT NULL DEFAULT 'explicit',
                    qualifies_review INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    invalidation_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_discovery_instance_prop
                    ON discovery_instances(proposition_id,active,qualifies_review,created_at);
                CREATE INDEX IF NOT EXISTS idx_discovery_instance_turn
                    ON discovery_instances(source_turn_id,source_kind,active);
                CREATE INDEX IF NOT EXISTS idx_discovery_instance_session
                    ON discovery_instances(source_session_id,active);

                CREATE TABLE IF NOT EXISTS discovery_decisions(
                    id TEXT PRIMARY KEY,
                    proposition_id TEXT NOT NULL REFERENCES discovery_propositions(id) ON DELETE CASCADE,
                    action TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    actor TEXT NOT NULL DEFAULT 'user',
                    created_at TEXT NOT NULL,
                    CHECK(action IN ('canon','dismiss','reset'))
                );

                CREATE TABLE IF NOT EXISTS discovery_subject_links(
                    project_id TEXT NOT NULL DEFAULT '',
                    world_id TEXT NOT NULL DEFAULT '',
                    subject_key TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(project_id,world_id,subject_key)
                );
                """
            )
            con.execute(
                "INSERT INTO discovery_meta(key,value) VALUES('schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(self.SCHEMA_VERSION),),
            )

    @staticmethod
    def _prop_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item["value"] = loads(item.pop("value_json", None), None)
        return item

    @staticmethod
    def _instance_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item["world_time"] = loads(item.pop("world_time_json", None), None)
        item["qualifies_review"] = bool(item.get("qualifies_review"))
        item["active"] = bool(item.get("active"))
        return item

    def upsert_proposition(self, *, project_id: str | None, world_id: str | None,
                           subject_type: str, subject_key: str, subject_label: str,
                           predicate: str, value: Any = None,
                           object_type: str | None = None, object_key: str | None = None,
                           object_label: str | None = None, operation: str = "update",
                           temporal_state: str = "current_or_unspecified",
                           target_resource_type: str | None = None,
                           target_resource_id: str | None = None) -> dict[str, Any]:
        key = proposition_key(
            project_id=project_id, world_id=world_id, subject_type=subject_type,
            subject_key=subject_key, predicate=predicate, value=value,
            object_key=object_key, operation=operation,
        )
        now = utc_now()
        with self._lock, self.connection() as con:
            row = con.execute("SELECT id FROM discovery_propositions WHERE proposition_key=?", (key,)).fetchone()
            if row:
                prop_id = row["id"]
                con.execute(
                    "UPDATE discovery_propositions SET subject_label=?,object_type=?,object_key=?,object_label=?,"
                    "temporal_state=?,target_resource_type=COALESCE(?,target_resource_type),"
                    "target_resource_id=COALESCE(?,target_resource_id),updated_at=? WHERE id=?",
                    (subject_label, object_type, object_key, object_label, temporal_state,
                     target_resource_type, target_resource_id, now, prop_id),
                )
            else:
                prop_id = make_id("PROP")
                con.execute(
                    "INSERT INTO discovery_propositions(id,proposition_key,project_id,world_id,subject_type,subject_key,"
                    "subject_label,predicate,value_json,object_type,object_key,object_label,operation,authority_state,"
                    "temporal_state,target_resource_type,target_resource_id,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'observed',?,?,?,?,?,?)",
                    (prop_id, key, project_id, world_id, subject_type, subject_key, subject_label,
                     predicate, dumps(value), object_type, object_key, object_label, operation,
                     temporal_state, target_resource_type, target_resource_id, now, now),
                )
        return self.get_proposition(prop_id)

    def get_proposition(self, proposition_id: str) -> dict[str, Any]:
        with self.connection() as con:
            row = con.execute("SELECT * FROM discovery_propositions WHERE id=?", (proposition_id,)).fetchone()
        if row is None:
            raise KeyError(proposition_id)
        return self._prop_row(row)

    def list_propositions(self, *, project_id: str | None = None, world_id: str | None = None,
                          include_dismissed: bool = False, limit: int = 500) -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []
        if project_id is not None:
            where.append("project_id IS ?")
            params.append(project_id)
        if world_id is not None:
            where.append("world_id IS ?")
            params.append(world_id)
        if not include_dismissed:
            where.append("authority_state!='dismissed'")
        params.append(max(1, min(int(limit), 5000)))
        with self.connection() as con:
            rows = con.execute(
                f"SELECT * FROM discovery_propositions WHERE {' AND '.join(where)} ORDER BY updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._prop_row(row) for row in rows]

    def find_subject_propositions(self, *, project_id: str | None, world_id: str | None,
                                  subject_key: str) -> list[dict[str, Any]]:
        with self.connection() as con:
            rows = con.execute(
                "SELECT * FROM discovery_propositions WHERE project_id IS ? AND world_id IS ? AND subject_key=? "
                "ORDER BY predicate,updated_at DESC",
                (project_id, world_id, subject_key),
            ).fetchall()
        return [self._prop_row(row) for row in rows]

    def prepare_source_revision(self, *, source_turn_id: str, source_kind: str,
                                source_revision: str) -> int:
        """Stale prior instances if the same logical source is recaptured after editing."""
        now = utc_now()
        with self._lock, self.connection() as con:
            cur = con.execute(
                "UPDATE discovery_instances SET active=0,invalidation_reason='source_revision_replaced',updated_at=? "
                "WHERE source_turn_id=? AND source_kind=? AND active=1 AND source_revision!=?",
                (now, source_turn_id, source_kind, source_revision),
            )
            return max(0, cur.rowcount)

    def add_instance(self, proposition_id: str, *, source_kind: str,
                     source_session_id: str | None, source_turn_id: str | None,
                     origin_session_id: str | None, origin_turn_id: str | None,
                     source_revision: str, project_id: str | None, world_id: str | None,
                     branch_id: str | None, world_time: Any = None, story_order: float | None = None,
                     source_segment: str | None = None, span_start: int | None = None,
                     span_end: int | None = None, span_text: str = "",
                     extraction_confidence: float = 1.0, explicitness: str = "explicit",
                     qualifies_review: bool = False) -> dict[str, Any]:
        seed = dumps([
            proposition_id, source_kind, origin_turn_id or source_turn_id or "",
            source_segment or "", span_start, span_end, source_revision,
        ])
        instance_key = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        now = utc_now()
        with self._lock, self.connection() as con:
            row = con.execute("SELECT id FROM discovery_instances WHERE instance_key=?", (instance_key,)).fetchone()
            if row:
                instance_id = row["id"]
                con.execute(
                    "UPDATE discovery_instances SET active=1,invalidation_reason=NULL,updated_at=? WHERE id=?",
                    (now, instance_id),
                )
            else:
                instance_id = make_id("DISC")
                con.execute(
                    "INSERT INTO discovery_instances(id,instance_key,proposition_id,source_kind,source_session_id,"
                    "source_turn_id,origin_session_id,origin_turn_id,source_revision,project_id,world_id,branch_id,"
                    "world_time_json,story_order,source_segment,span_start,span_end,span_text,extraction_confidence,"
                    "explicitness,qualifies_review,active,invalidation_reason,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,NULL,?,?)",
                    (instance_id, instance_key, proposition_id, source_kind, source_session_id, source_turn_id,
                     origin_session_id, origin_turn_id, source_revision, project_id, world_id, branch_id,
                     dumps(world_time) if world_time is not None else None, story_order, source_segment,
                     span_start, span_end, span_text, max(0.0, min(1.0, float(extraction_confidence))),
                     explicitness, int(bool(qualifies_review)), now, now),
                )
            con.execute("UPDATE discovery_propositions SET updated_at=? WHERE id=?", (now, proposition_id))
        return self.get_instance(instance_id)

    def get_instance(self, instance_id: str) -> dict[str, Any]:
        with self.connection() as con:
            row = con.execute("SELECT * FROM discovery_instances WHERE id=?", (instance_id,)).fetchone()
        if row is None:
            raise KeyError(instance_id)
        return self._instance_row(row)

    def list_instances(self, proposition_id: str, *, active: bool | None = None) -> list[dict[str, Any]]:
        where = ["proposition_id=?"]
        params: list[Any] = [proposition_id]
        if active is not None:
            where.append("active=?")
            params.append(int(active))
        with self.connection() as con:
            rows = con.execute(
                f"SELECT * FROM discovery_instances WHERE {' AND '.join(where)} ORDER BY created_at ASC,id ASC",
                params,
            ).fetchall()
        return [self._instance_row(row) for row in rows]

    def set_source_active(self, *, session_id: str | None = None, turn_id: str | None = None,
                          active: bool, reason: str | None = None) -> int:
        if not session_id and not turn_id:
            raise ValueError("session_id or turn_id is required")
        where = []
        params: list[Any] = []
        if session_id:
            where.append("source_session_id=?")
            params.append(session_id)
        if turn_id:
            where.append("source_turn_id=?")
            params.append(turn_id)
        now = utc_now()
        with self._lock, self.connection() as con:
            cur = con.execute(
                f"UPDATE discovery_instances SET active=?,invalidation_reason=?,updated_at=? WHERE {' AND '.join(where)}",
                [int(active), None if active else (reason or "source_inactive"), now, *params],
            )
            return max(0, cur.rowcount)

    def set_source_kind_active(self, turn_id: str, source_kind: str, *, active: bool,
                               reason: str | None = None) -> int:
        with self._lock, self.connection() as con:
            cur = con.execute(
                "UPDATE discovery_instances SET active=?,invalidation_reason=?,updated_at=? "
                "WHERE source_turn_id=? AND source_kind=?",
                (int(active), None if active else (reason or "source_inactive"), utc_now(), turn_id, source_kind),
            )
            return max(0, cur.rowcount)

    def set_authority(self, proposition_id: str, state: str, *, note: str = "") -> dict[str, Any]:
        if state not in {"observed", "canon", "dismissed"}:
            raise ValueError("Unsupported discovery authority state")
        action = {"observed": "reset", "canon": "canon", "dismissed": "dismiss"}[state]
        now = utc_now()
        with self._lock, self.connection() as con:
            cur = con.execute(
                "UPDATE discovery_propositions SET authority_state=?,promoted_at=?,updated_at=? WHERE id=?",
                (state, now if state == "canon" else None, now, proposition_id),
            )
            if cur.rowcount == 0:
                raise KeyError(proposition_id)
            con.execute(
                "INSERT INTO discovery_decisions(id,proposition_id,action,note,actor,created_at) VALUES(?,?,?,?,?,?)",
                (make_id("DISCDEC"), proposition_id, action, note.strip(), "user", now),
            )
        return self.get_proposition(proposition_id)

    def set_materialized(self, proposition_id: str, *, resource_type: str | None,
                         resource_id: str | None, target_resource_type: str | None = None,
                         target_resource_id: str | None = None) -> dict[str, Any]:
        with self._lock, self.connection() as con:
            cur = con.execute(
                "UPDATE discovery_propositions SET materialized_resource_type=?,materialized_resource_id=?,"
                "target_resource_type=COALESCE(?,target_resource_type),target_resource_id=COALESCE(?,target_resource_id),"
                "updated_at=? WHERE id=?",
                (resource_type, resource_id, target_resource_type, target_resource_id, utc_now(), proposition_id),
            )
            if cur.rowcount == 0:
                raise KeyError(proposition_id)
        return self.get_proposition(proposition_id)

    def upsert_subject_link(self, *, project_id: str | None, world_id: str | None,
                            subject_key: str, resource_type: str, resource_id: str) -> None:
        with self._lock, self.connection() as con:
            con.execute(
                "INSERT INTO discovery_subject_links(project_id,world_id,subject_key,resource_type,resource_id,updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(project_id,world_id,subject_key) DO UPDATE SET "
                "resource_type=excluded.resource_type,resource_id=excluded.resource_id,updated_at=excluded.updated_at",
                (project_id or "", world_id or "", subject_key, resource_type, resource_id, utc_now()),
            )

    def get_subject_link(self, *, project_id: str | None, world_id: str | None,
                         subject_key: str) -> dict[str, str] | None:
        with self.connection() as con:
            row = con.execute(
                "SELECT resource_type,resource_id FROM discovery_subject_links WHERE project_id=? AND world_id=? AND subject_key=?",
                (project_id or "", world_id or "", subject_key),
            ).fetchone()
        return dict(row) if row else None

    def status(self) -> dict[str, int]:
        with self.connection() as con:
            propositions = int(con.execute("SELECT COUNT(*) FROM discovery_propositions").fetchone()[0])
            instances = int(con.execute("SELECT COUNT(*) FROM discovery_instances").fetchone()[0])
            active = int(con.execute("SELECT COUNT(*) FROM discovery_instances WHERE active=1").fetchone()[0])
            canon = int(con.execute("SELECT COUNT(*) FROM discovery_propositions WHERE authority_state='canon'").fetchone()[0])
        return {"propositions": propositions, "instances": instances, "active_instances": active, "canon": canon}
