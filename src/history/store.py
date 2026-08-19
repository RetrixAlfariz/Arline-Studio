from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock
from typing import Any, Iterable

from src.storage_backup import backup_sqlite_before_migrations
from src.domain_events import emit_domain_event
from uuid import uuid4


SCHEMA_VERSION = 4
VALID_FEEDBACK = {"unreviewed", "accepted", "edited_accept", "rejected"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{prefix}-{stamp}-{uuid4().hex[:6].upper()}"


def make_session_title(prompt: str, max_chars: int = 58) -> str:
    """Create a useful local title without spending another model call.

    Dense Arline prompts often begin with generic directives ("very long",
    "focus on detail", dates, etc.). Prefer the first line that looks like
    actual story/context content, then fall back to the first non-empty line.
    """
    raw_lines = [line.strip() for line in prompt.splitlines() if line.strip()]
    if not raw_lines:
        return "Untitled chat"

    def clean(line: str) -> str:
        line = re.sub(r"^[\[\(\{\s]+|[\]\)\}\s]+$", "", line).strip()
        line = re.sub(r"\s+", " ", line)
        return line

    lines = [clean(line) for line in raw_lines]
    generic = re.compile(
        r"^(?:sebuah\s+cerita|cerita\s+sangat|fokus\b|tahun\b|addition\s+info\b|"
        r"sekarang\s+sedang\b|buat\s+cerita\b|write\b)",
        re.IGNORECASE,
    )
    chosen = next((line for line in lines if line and not generic.search(line)), None)
    chosen = chosen or next((line for line in lines if line), "Untitled chat")
    chosen = chosen.strip(" .,:;—-\t")
    if len(chosen) <= max_chars:
        return chosen or "Untitled chat"
    shortened = chosen[: max_chars + 1].rsplit(" ", 1)[0].rstrip(" .,:;—-")
    return (shortened or chosen[:max_chars]).rstrip() + "…"


@dataclass(slots=True)
class DatasetExport:
    kind: str
    path: Path
    rows: int


class HistoryStore:
    """SQLite-backed local session/turn history for Arline Studio.

    The database intentionally stores generation records separately from saved
    ZIP artifacts. History is optimized for reopening/searching/feedback;
    ArtifactStore remains the immutable diagnostic archive path.
    """

    def __init__(self, database_path: Path | str, *, backup_before_migration: bool = True):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.last_migration_backup = backup_sqlite_before_migrations(self.path, {"meta": SCHEMA_VERSION}) if backup_before_migration else None
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
            con.execute("PRAGMA journal_mode = WAL")
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0,
                    project TEXT,
                    project_id TEXT,
                    world_id TEXT,
                    branch_id TEXT,
                    folder_id TEXT,
                    session_kind TEXT NOT NULL DEFAULT 'chat',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    workspace_refs_json TEXT NOT NULL DEFAULT '[]',
                    parent_session_id TEXT,
                    forked_from_turn_id TEXT,
                    scratch_mode INTEGER NOT NULL DEFAULT 0,
                    world_fork_id TEXT,
                    last_model TEXT,
                    last_mode TEXT,
                    last_reasoning TEXT
                );

                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    run_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    user_prompt TEXT NOT NULL,
                    story TEXT NOT NULL,
                    model TEXT,
                    mode TEXT,
                    reasoning TEXT,
                    projection_mode TEXT,
                    reasoning_text TEXT NOT NULL DEFAULT '',
                    stats_json TEXT NOT NULL DEFAULT '{}',
                    wcf TEXT NOT NULL DEFAULT '',
                    aif_core TEXT NOT NULL DEFAULT '',
                    session_context TEXT NOT NULL DEFAULT '',
                    workspace_context TEXT NOT NULL DEFAULT '',
                    workspace_scope_json TEXT NOT NULL DEFAULT '{}',
                    workspace_refs_json TEXT NOT NULL DEFAULT '[]',
                    lineage_json TEXT NOT NULL DEFAULT '{}',
                    projections_json TEXT NOT NULL DEFAULT '[]',
                    post_validation_json TEXT NOT NULL DEFAULT '{}',
                    wcf_validation_json TEXT NOT NULL DEFAULT '{}',
                    feedback_status TEXT NOT NULL DEFAULT 'unreviewed',
                    feedback_issues_json TEXT NOT NULL DEFAULT '[]',
                    feedback_note TEXT NOT NULL DEFAULT '',
                    edited_story TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );
                """
            )
            session_columns = {row[1] for row in con.execute("PRAGMA table_info(sessions)").fetchall()}
            for name, definition in (
                ("title", "TEXT NOT NULL DEFAULT 'Untitled chat'"),
                ("created_at", "TEXT NOT NULL DEFAULT ''"),
                ("updated_at", "TEXT NOT NULL DEFAULT ''"),
                ("pinned", "INTEGER NOT NULL DEFAULT 0"),
                ("archived", "INTEGER NOT NULL DEFAULT 0"),
                ("project", "TEXT"),
                ("last_model", "TEXT"),
                ("last_mode", "TEXT"),
                ("last_reasoning", "TEXT"),
                ("project_id", "TEXT"),
                ("world_id", "TEXT"),
                ("branch_id", "TEXT"),
                ("folder_id", "TEXT"),
                ("session_kind", "TEXT NOT NULL DEFAULT 'chat'"),
                ("tags_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("workspace_refs_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("parent_session_id", "TEXT"),
                ("forked_from_turn_id", "TEXT"),
                ("scratch_mode", "INTEGER NOT NULL DEFAULT 0"),
                ("world_fork_id", "TEXT"),
            ):
                if name not in session_columns:
                    con.execute(f"ALTER TABLE sessions ADD COLUMN {name} {definition}")

            columns = {row[1] for row in con.execute("PRAGMA table_info(turns)").fetchall()}
            for name, definition in (
                ("session_id", "TEXT NOT NULL DEFAULT ''"),
                ("run_id", "TEXT"),
                ("created_at", "TEXT NOT NULL DEFAULT ''"),
                ("updated_at", "TEXT NOT NULL DEFAULT ''"),
                ("user_prompt", "TEXT NOT NULL DEFAULT ''"),
                ("story", "TEXT NOT NULL DEFAULT ''"),
                ("model", "TEXT"),
                ("mode", "TEXT"),
                ("reasoning", "TEXT"),
                ("projection_mode", "TEXT"),
                ("stats_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("wcf", "TEXT NOT NULL DEFAULT ''"),
                ("aif_core", "TEXT NOT NULL DEFAULT ''"),
                ("projections_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("post_validation_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("wcf_validation_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("feedback_status", "TEXT NOT NULL DEFAULT 'unreviewed'"),
                ("feedback_issues_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("feedback_note", "TEXT NOT NULL DEFAULT ''"),
                ("edited_story", "TEXT NOT NULL DEFAULT ''"),
                ("session_context", "TEXT NOT NULL DEFAULT ''"),
                ("reasoning_text", "TEXT NOT NULL DEFAULT ''"),
                ("workspace_context", "TEXT NOT NULL DEFAULT ''"),
                ("workspace_scope_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("workspace_refs_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("lineage_json", "TEXT NOT NULL DEFAULT '{}'"),
            ):
                if name not in columns:
                    con.execute(f"ALTER TABLE turns ADD COLUMN {name} {definition}")


            con.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_sessions_pinned ON sessions(pinned DESC, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, created_at ASC);
                CREATE INDEX IF NOT EXISTS idx_turns_feedback ON turns(feedback_status);
                """
            )

            con.execute(
                "INSERT INTO meta(key,value) VALUES('schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    @staticmethod
    def _loads(value: str | None, fallback: Any) -> Any:
        if not value:
            return fallback
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return fallback

    def create_session(
        self,
        *,
        title: str | None = None,
        prompt: str = "",
        project: str | None = None,
        project_id: str | None = None,
        world_id: str | None = None,
        branch_id: str | None = None,
        folder_id: str | None = None,
        session_kind: str = "chat",
        tags: list[str] | None = None,
        workspace_refs: list[dict[str, Any]] | None = None,
        parent_session_id: str | None = None,
        forked_from_turn_id: str | None = None,
        scratch_mode: bool = False,
        world_fork_id: str | None = None,
    ) -> dict[str, Any]:
        session_id = _id("CHAT")
        now = utc_now()
        title = (title or make_session_title(prompt)).strip() or "Untitled chat"
        with self._lock, self._connection() as con:
            con.execute(
                """
                INSERT INTO sessions(
                    id,title,created_at,updated_at,pinned,archived,project,
                    project_id,world_id,branch_id,folder_id,session_kind,tags_json,workspace_refs_json,
                    parent_session_id,forked_from_turn_id,scratch_mode,world_fork_id
                ) VALUES(?,?,?,?,0,0,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    session_id, title, now, now, project, project_id, world_id,
                    branch_id, folder_id, session_kind, json.dumps(tags or [], ensure_ascii=False),
                    json.dumps(workspace_refs or [], ensure_ascii=False),
                    parent_session_id, forked_from_turn_id, 1 if scratch_mode else 0, world_fork_id,
                ),
            )
        return self.get_session_meta(session_id)

    def get_session_meta(self, session_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute(
                """
                SELECT s.*,
                       (SELECT COUNT(*) FROM turns t WHERE t.session_id=s.id) AS turn_count,
                       (SELECT substr(t.user_prompt,1,160) FROM turns t
                        WHERE t.session_id=s.id ORDER BY t.created_at DESC LIMIT 1) AS prompt_preview
                FROM sessions s WHERE s.id=?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return self._session_row(row)

    def list_sessions(
        self,
        *,
        search: str = "",
        limit: int = 100,
        include_archived: bool = False,
        project_id: str | None = None,
        world_id: str | None = None,
        branch_id: str | None = None,
        folder_id: str | None = None,
        tag: str | None = None,
        session_kind: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        terms: list[Any] = []
        where = ["1=1"]
        if not include_archived:
            where.append("s.archived=0")
        for column, value in (
            ("project_id", project_id), ("world_id", world_id),
            ("branch_id", branch_id), ("folder_id", folder_id),
            ("session_kind", session_kind),
        ):
            if value is not None:
                where.append(f"s.{column}=?")
                terms.append(value)
        if tag:
            where.append("s.tags_json LIKE ? COLLATE NOCASE")
            terms.append(f'%"{tag}"%')
        search = search.strip()
        if search:
            like = f"%{search}%"
            where.append(
                "(s.title LIKE ? COLLATE NOCASE OR EXISTS ("
                "SELECT 1 FROM turns st WHERE st.session_id=s.id AND ("
                "st.user_prompt LIKE ? COLLATE NOCASE OR "
                "st.story LIKE ? COLLATE NOCASE OR "
                "st.edited_story LIKE ? COLLATE NOCASE)))"
            )
            terms.extend([like, like, like, like])
        terms.append(limit)
        query = f"""
            SELECT s.*,
                   (SELECT COUNT(*) FROM turns t WHERE t.session_id=s.id) AS turn_count,
                   (SELECT substr(t.user_prompt,1,160) FROM turns t
                    WHERE t.session_id=s.id ORDER BY t.created_at DESC LIMIT 1) AS prompt_preview
            FROM sessions s
            WHERE {' AND '.join(where)}
            ORDER BY s.pinned DESC, s.updated_at DESC
            LIMIT ?
        """
        with self._connection() as con:
            rows = con.execute(query, terms).fetchall()
        return [self._session_row(row) for row in rows]

    def get_session(self, session_id: str, *, include_context: bool = False) -> dict[str, Any]:
        meta = self.get_session_meta(session_id)
        columns = "*" if include_context else (
            "id,session_id,run_id,created_at,updated_at,user_prompt,story,model,mode,"
            "reasoning,projection_mode,reasoning_text,stats_json,post_validation_json,feedback_status,"
            "feedback_issues_json,feedback_note,edited_story"
        )
        with self._connection() as con:
            rows = con.execute(
                f"SELECT {columns} FROM turns WHERE session_id=? ORDER BY created_at ASC, rowid ASC",
                (session_id,),
            ).fetchall()
        meta["turns"] = [self._turn_row(row, include_context=include_context) for row in rows]
        return meta

    def get_turn(self, turn_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
        if row is None:
            raise KeyError(turn_id)
        return self._turn_row(row, include_context=True)

    def update_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
        pinned: bool | None = None,
        archived: bool | None = None,
        project: str | None = None,
        project_id: str | None = None,
        world_id: str | None = None,
        branch_id: str | None = None,
        folder_id: str | None = None,
        session_kind: str | None = None,
        tags: list[str] | None = None,
        workspace_refs: list[dict[str, Any]] | None = None,
        scratch_mode: bool | None = None,
        world_fork_id: str | None = None,
    ) -> dict[str, Any]:
        fields: list[str] = []
        params: list[Any] = []
        if title is not None:
            title = title.strip()
            if not title:
                raise ValueError("Session title cannot be blank")
            fields.append("title=?")
            params.append(title[:160])
        if pinned is not None:
            fields.append("pinned=?")
            params.append(1 if pinned else 0)
        if archived is not None:
            fields.append("archived=?")
            params.append(1 if archived else 0)
        if project is not None:
            fields.append("project=?")
            params.append(project.strip() or None)
        for key, value in (
            ("project_id", project_id), ("world_id", world_id),
            ("branch_id", branch_id), ("folder_id", folder_id),
            ("session_kind", session_kind),
        ):
            if value is not None:
                fields.append(f"{key}=?")
                params.append(value or None)
        if tags is not None:
            fields.append("tags_json=?")
            params.append(json.dumps(tags, ensure_ascii=False))
        if workspace_refs is not None:
            fields.append("workspace_refs_json=?")
            params.append(json.dumps(workspace_refs, ensure_ascii=False))
        if scratch_mode is not None:
            fields.append("scratch_mode=?")
            params.append(1 if scratch_mode else 0)
        if world_fork_id is not None:
            fields.append("world_fork_id=?")
            params.append(world_fork_id or None)
        if fields:
            fields.append("updated_at=?")
            params.append(utc_now())
            params.append(session_id)
            with self._lock, self._connection() as con:
                cur = con.execute(
                    f"UPDATE sessions SET {', '.join(fields)} WHERE id=?",
                    params,
                )
                if cur.rowcount == 0:
                    raise KeyError(session_id)
        return self.get_session_meta(session_id)

    def fork_session(
        self,
        session_id: str,
        *,
        through_turn_id: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Create an independent conversation branch without mutating the source.

        Turns are copied as historical surface records. Their generated prose
        remains reviewed/unreviewed exactly as in the source, while new IDs and
        a fork lineage marker prevent dataset collisions.
        """
        source = self.get_session(session_id, include_context=True)
        turns = source.get("turns", [])
        if through_turn_id:
            matched = False
            bounded = []
            for turn in turns:
                bounded.append(turn)
                if turn["id"] == through_turn_id:
                    matched = True
                    break
            if not matched:
                raise KeyError(through_turn_id)
            turns = bounded

        fork = self.create_session(
            prompt=(turns[0]["user_prompt"] if turns else source.get("prompt_preview", "")),
            title=(title or f"{source['title']} (fork)"),
            project=source.get("project"),
            project_id=source.get("project_id"),
            world_id=source.get("world_id"),
            branch_id=source.get("branch_id"),
            # Chat forks remain in the chat layer. Project folders are a
            # document/filesystem concern in v1.1, not conversation storage.
            folder_id=None,
            session_kind=source.get("session_kind") or "chat",
            tags=source.get("tags") or [],
            workspace_refs=source.get("workspace_refs") or [],
            parent_session_id=session_id,
            forked_from_turn_id=through_turn_id or (turns[-1]["id"] if turns else None),
            scratch_mode=bool(source.get("scratch_mode")),
            world_fork_id=source.get("world_fork_id"),
        )
        for index, turn in enumerate(turns, start=1):
            lineage = dict(turn.get("lineage") or {})
            lineage.update({
                "forked_from_session_id": session_id,
                "forked_from_turn_id": turn["id"],
                "fork_copy_index": index,
            })
            copied = self.add_turn(
                fork["id"],
                run_id=f"FORK-{turn['run_id']}-{index:02d}",
                user_prompt=turn["user_prompt"],
                story=turn["story"],
                model=turn["model"],
                mode=turn["mode"],
                reasoning=turn["reasoning"],
                projection_mode=turn["projection_mode"],
                reasoning_text=turn.get("reasoning_text", ""),
                stats=turn.get("stats") or {},
                wcf=turn.get("wcf", ""),
                aif_core=turn.get("aif_core", ""),
                session_context=turn.get("session_context", ""),
                workspace_context=turn.get("workspace_context", ""),
                workspace_scope=turn.get("workspace_scope") or {},
                workspace_refs=turn.get("workspace_refs") or [],
                lineage=lineage,
                projections=turn.get("projections") or [],
                post_validation=turn.get("post_validation") or {},
                wcf_validation=turn.get("wcf_validation") or {},
            )
            status = turn.get("feedback_status", "unreviewed")
            if status != "unreviewed":
                self.set_feedback(
                    copied["id"],
                    status=status,
                    issues=turn.get("feedback_issues") or [],
                    note=turn.get("feedback_note", ""),
                    edited_story=turn.get("edited_story", ""),
                )
        return self.get_session(fork["id"])

    def list_session_forks(self, session_id: str) -> dict[str, Any]:
        """Return the root/children graph for the conversation branch family."""
        source = self.get_session_meta(session_id)
        root_id = source.get("parent_session_id") or session_id
        # Walk upward because forks can fork forks.
        seen: set[str] = set()
        current = source
        while current.get("parent_session_id") and current["id"] not in seen:
            seen.add(current["id"])
            try:
                current = self.get_session_meta(current["parent_session_id"])
                root_id = current["id"]
            except KeyError:
                break
        with self._connection() as con:
            rows = con.execute(
                "SELECT id FROM sessions WHERE id=? OR parent_session_id IS NOT NULL ORDER BY created_at ASC",
                (root_id,),
            ).fetchall()
        all_rows = [self.get_session_meta(row["id"]) for row in rows]
        # Keep only descendants of the located root.
        by_parent: dict[str, list[dict[str, Any]]] = {}
        for item in all_rows:
            if item.get("parent_session_id"):
                by_parent.setdefault(item["parent_session_id"], []).append(item)
        descendants: list[dict[str, Any]] = []
        queue = [root_id]
        visited: set[str] = set()
        while queue:
            parent = queue.pop(0)
            if parent in visited:
                continue
            visited.add(parent)
            for child in by_parent.get(parent, []):
                descendants.append(child)
                queue.append(child["id"])
        root = self.get_session_meta(root_id)
        return {"root": root, "sessions": [root, *descendants], "active_id": session_id}

    def delete_session(self, session_id: str) -> None:
        with self._lock, self._connection() as con:
            cur = con.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            if cur.rowcount == 0:
                raise KeyError(session_id)
        emit_domain_event(
            self.path,
            "history.session_deleted",
            {"session_id": session_id},
        )

    def delete_sessions_by_scope(
        self, *, project_id: str | None = None, world_id: str | None = None,
        branch_id: str | None = None
    ) -> int:
        filters: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("project_id", project_id),
            ("world_id", world_id),
            ("branch_id", branch_id),
        ):
            if value is not None:
                filters.append(f"{column}=?")
                params.append(value)
        if not filters:
            raise ValueError("At least one scope id is required")

        with self._lock, self._connection() as con:
            rows = con.execute(
                f"SELECT id FROM sessions WHERE {' AND '.join(filters)}",
                params,
            ).fetchall()
            session_ids = [str(row["id"]) for row in rows]
            cur = con.execute(
                f"DELETE FROM sessions WHERE {' AND '.join(filters)}",
                params,
            )
            deleted = max(0, cur.rowcount)

        emit_domain_event(
            self.path,
            "history.scope_deleted",
            {
                "project_id": project_id,
                "world_id": world_id,
                "branch_id": branch_id,
                "session_ids": session_ids,
                "deleted_count": deleted,
            },
        )
        return deleted

    def clear_folder_reference(self, folder_id: str) -> int:
        """Keep chats when a folder is removed, but move them back to unfiled."""
        with self._lock, self._connection() as con:
            cur = con.execute(
                "UPDATE sessions SET folder_id=NULL,updated_at=? WHERE folder_id=?",
                (utc_now(), folder_id),
            )
            return max(0, cur.rowcount)

    def add_turn(
        self,
        session_id: str,
        *,
        run_id: str,
        user_prompt: str,
        story: str,
        model: str,
        mode: str,
        reasoning: str,
        projection_mode: str,
        reasoning_text: str = "",
        stats: dict[str, Any] | None = None,
        wcf: str = "",
        aif_core: str = "",
        session_context: str = "",
        workspace_context: str = "",
        workspace_scope: dict[str, Any] | None = None,
        workspace_refs: list[dict[str, Any]] | None = None,
        lineage: dict[str, Any] | None = None,
        projections: list[dict[str, Any]] | None = None,
        post_validation: dict[str, Any] | None = None,
        wcf_validation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Validate the session before doing any write.
        self.get_session_meta(session_id)
        turn_id = _id("TURN")
        now = utc_now()
        with self._lock, self._connection() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute(
                    """
                    INSERT INTO turns(
                        id,session_id,run_id,created_at,updated_at,user_prompt,story,
                        model,mode,reasoning,projection_mode,reasoning_text,stats_json,wcf,aif_core,
                        session_context,workspace_context,workspace_scope_json,workspace_refs_json,lineage_json,
                        projections_json,post_validation_json,wcf_validation_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        turn_id,
                        session_id,
                        run_id,
                        now,
                        now,
                        user_prompt,
                        story,
                        model,
                        mode,
                        reasoning,
                        projection_mode,
                        reasoning_text,
                        json.dumps(stats or {}, ensure_ascii=False),
                        wcf,
                        aif_core,
                        session_context,
                        workspace_context,
                        json.dumps(workspace_scope or {}, ensure_ascii=False),
                        json.dumps(workspace_refs or [], ensure_ascii=False),
                        json.dumps(lineage or {}, ensure_ascii=False),
                        json.dumps(projections or [], ensure_ascii=False),
                        json.dumps(post_validation or {}, ensure_ascii=False),
                        json.dumps(wcf_validation or {}, ensure_ascii=False),
                    ),
                )
                con.execute(
                    """
                    UPDATE sessions
                    SET updated_at=?, last_model=?, last_mode=?, last_reasoning=?
                    WHERE id=?
                    """,
                    (now, model, mode, reasoning, session_id),
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        result = self.get_turn(turn_id)
        emit_domain_event(self.path, "history.turn_created", {"turn": result})
        return result

    def set_feedback(
        self,
        turn_id: str,
        *,
        status: str,
        issues: Iterable[str] | None = None,
        note: str = "",
        edited_story: str = "",
    ) -> dict[str, Any]:
        if status not in VALID_FEEDBACK:
            raise ValueError(f"feedback status must be one of {sorted(VALID_FEEDBACK)}")
        issues_clean = sorted({str(x).strip() for x in (issues or []) if str(x).strip()})
        edited_story = edited_story.strip()
        if status == "edited_accept" and not edited_story:
            raise ValueError("edited_accept requires edited_story")
        now = utc_now()
        with self._lock, self._connection() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                row = con.execute("SELECT session_id FROM turns WHERE id=?", (turn_id,)).fetchone()
                if row is None:
                    raise KeyError(turn_id)
                con.execute(
                    """
                    UPDATE turns SET feedback_status=?,feedback_issues_json=?,feedback_note=?,
                                     edited_story=?,updated_at=?
                    WHERE id=?
                    """,
                    (
                        status,
                        json.dumps(issues_clean, ensure_ascii=False),
                        note.strip(),
                        edited_story,
                        now,
                        turn_id,
                    ),
                )
                con.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, row["session_id"]))
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        result = self.get_turn(turn_id)
        emit_domain_event(self.path, "history.feedback_changed", {"turn": result})
        return result

    def build_continuity_context(
        self,
        session_id: str,
        *,
        max_turns: int = 2,
        max_chars: int = 12000,
    ) -> str:
        """Build a bounded writer-only continuity reference.

        Earlier user messages are higher-authority source context. Generated
        prose is explicitly labelled non-canonical unless it was accepted or
        edited+accepted. This block is for Smart Hybrid continuity only; it is
        never promoted into AIF-Core/WCF automatically.
        """
        session = self.get_session(session_id)
        turns = (session.get("turns") or [])[-max(1, int(max_turns)):]
        if not turns:
            return ""
        blocks: list[str] = []
        for index, turn in enumerate(turns, start=1):
            prompt = (turn.get("user_prompt") or "").strip()
            if prompt:
                blocks.append(f"Earlier user turn {index}:\n{prompt}")
        last = turns[-1]
        story = (last.get("final_story") or last.get("story") or "").strip()
        if story:
            status = last.get("feedback_status") or "unreviewed"
            authority = "user-approved surface" if status in {"accepted", "edited_accept"} else "unreviewed model surface"
            blocks.append(
                "Most recent story surface "
                f"({authority}; continuity reference, not canonical WCF):\n{story}"
            )
        text = "\n\n".join(blocks)
        if len(text) > max_chars:
            # Keep the most recent material; prepend a marker so the model does
            # not assume it saw the entire session.
            text = "[Earlier session context truncated]\n" + text[-max_chars:]
        return text

    def dataset_stats(self) -> dict[str, int]:
        with self._connection() as con:
            rows = con.execute(
                "SELECT feedback_status,COUNT(*) AS n FROM turns GROUP BY feedback_status"
            ).fetchall()
            total = con.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        by = {row["feedback_status"]: int(row["n"]) for row in rows}
        return {
            "total": int(total),
            "unreviewed": by.get("unreviewed", 0),
            "accepted": by.get("accepted", 0),
            "edited_accept": by.get("edited_accept", 0),
            "rejected": by.get("rejected", 0),
            "sft_ready": by.get("accepted", 0) + by.get("edited_accept", 0),
            "preference_ready": by.get("edited_accept", 0),
        }

    def feedback_queue(self, *, status: str = "unreviewed", limit: int = 100, project_id: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        where = ["t.feedback_status=?", "s.archived=0"]
        params: list[Any] = [status]
        if project_id:
            where.append("s.project_id=?")
            params.append(project_id)
        params.append(limit)
        with self._connection() as con:
            rows = con.execute(
                f"""
                SELECT t.*, s.title AS session_title, s.project_id, s.world_id, s.branch_id,
                       s.parent_session_id, s.forked_from_turn_id
                FROM turns t JOIN sessions s ON s.id=t.session_id
                WHERE {' AND '.join(where)}
                ORDER BY t.updated_at DESC, t.created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        result = []
        for row in rows:
            item = self._turn_row(row, include_context=True)
            item.update({
                "session_title": row["session_title"],
                "project_id": row["project_id"],
                "world_id": row["world_id"],
                "branch_id": row["branch_id"],
                "parent_session_id": row["parent_session_id"],
                "forked_from_turn_id": row["forked_from_turn_id"],
            })
            result.append(item)
        return result

    def preference_opportunities(self, *, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Return sibling chat forks that can be reviewed as preference pairs.

        The pair is intentionally lineage-driven: two sessions only become a
        comparison when they forked from the same parent turn.  This avoids
        pretending unrelated generations are preference examples.
        """
        where = ["c.parent_session_id IS NOT NULL", "c.forked_from_turn_id IS NOT NULL", "c.archived=0"]
        params: list[Any] = []
        if project_id:
            where.append("c.project_id=?")
            params.append(project_id)
        params.append(max(1, min(int(limit), 300)))
        with self._connection() as con:
            children = con.execute(
                f"SELECT c.* FROM sessions c WHERE {' AND '.join(where)} ORDER BY c.updated_at DESC LIMIT ?",
                params,
            ).fetchall()
            grouped: dict[tuple[str, str], list[sqlite3.Row]] = {}
            for row in children:
                grouped.setdefault((row["parent_session_id"], row["forked_from_turn_id"]), []).append(row)
            opportunities = []
            for (parent_id, turn_id), siblings in grouped.items():
                parent_turn = con.execute("SELECT user_prompt,story FROM turns WHERE id=?", (turn_id,)).fetchone()
                candidates = []
                # Include the original parent continuation after the fork point, if any.
                parent_next = con.execute(
                    "SELECT * FROM turns WHERE session_id=? AND rowid>(SELECT rowid FROM turns WHERE id=?) ORDER BY rowid ASC LIMIT 1",
                    (parent_id, turn_id),
                ).fetchone()
                if parent_next:
                    candidates.append({"session_id": parent_id, "turn_id": parent_next["id"], "story": parent_next["story"], "label": "Original"})
                for sibling in siblings:
                    first = con.execute("SELECT * FROM turns WHERE session_id=? ORDER BY rowid ASC LIMIT 1", (sibling["id"],)).fetchone()
                    if first:
                        candidates.append({"session_id": sibling["id"], "turn_id": first["id"], "story": first["story"], "label": sibling["title"]})
                if len(candidates) >= 2:
                    opportunities.append({
                        "parent_session_id": parent_id,
                        "forked_from_turn_id": turn_id,
                        "prompt": parent_turn["user_prompt"] if parent_turn else "",
                        "context_story": parent_turn["story"] if parent_turn else "",
                        "candidates": candidates,
                    })
            return opportunities[:limit]

    def export_dataset(self, kind: str, output_dir: Path | str) -> DatasetExport:
        kind = kind.lower().strip()
        if kind not in {"master", "sft", "preference", "eval"}:
            raise ValueError("dataset kind must be master, sft, preference, or eval")
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = out / f"arline-{kind}-v0.1-{stamp}.jsonl"

        with self._connection() as con:
            rows = con.execute(
                """
                SELECT t.*, s.title AS session_title
                FROM turns t JOIN sessions s ON s.id=t.session_id
                ORDER BY t.created_at ASC, t.rowid ASC
                """
            ).fetchall()

        records: list[dict[str, Any]] = []
        for row in rows:
            turn = self._turn_row(row, include_context=True)
            status = turn["feedback_status"]
            base = {
                "dataset_schema": "arline-feedback-0.1",
                "session_id": turn["session_id"],
                "session_title": row["session_title"],
                "turn_id": turn["id"],
                "run_id": turn["run_id"],
                "created_at": turn["created_at"],
                "prompt": turn["user_prompt"],
                "wcf": turn.get("wcf", ""),
                "aif_core": turn.get("aif_core", ""),
                "session_context": turn.get("session_context", ""),
                "workspace_context": turn.get("workspace_context", ""),
                "workspace_scope": turn.get("workspace_scope", {}),
                "workspace_refs": turn.get("workspace_refs", []),
                "lineage": turn.get("lineage", {}),
                "model": turn["model"],
                "mode": turn["mode"],
                "reasoning": turn["reasoning"],
                "reasoning_trace": turn.get("reasoning_text", ""),
                "projection_mode": turn["projection_mode"],
                "generated": turn["story"],
                "feedback": {
                    "status": status,
                    "issues": turn["feedback_issues"],
                    "note": turn["feedback_note"],
                },
                "validator": turn["post_validation"],
                "stats": turn["stats"],
            }
            if kind == "master":
                base["final_text"] = turn["final_story"]
                records.append(base)
            elif kind == "sft" and status in {"accepted", "edited_accept"}:
                records.append({
                    **base,
                    "target": turn["final_story"],
                })
            elif kind == "preference" and status == "edited_accept" and turn["edited_story"]:
                records.append({
                    **base,
                    "chosen": turn["edited_story"],
                    "rejected": turn["story"],
                })
            elif kind == "eval" and (status == "rejected" or turn["feedback_issues"]):
                records.append({
                    **base,
                    "expected_status": status,
                })

        with path.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return DatasetExport(kind=kind, path=path, rows=len(records))

    def _session_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "pinned": bool(row["pinned"]),
            "archived": bool(row["archived"]),
            "project": row["project"],
            "project_id": row["project_id"] if "project_id" in row.keys() else None,
            "world_id": row["world_id"] if "world_id" in row.keys() else None,
            "branch_id": row["branch_id"] if "branch_id" in row.keys() else None,
            "folder_id": row["folder_id"] if "folder_id" in row.keys() else None,
            "session_kind": (row["session_kind"] if "session_kind" in row.keys() else "chat") or "chat",
            "tags": self._loads(row["tags_json"] if "tags_json" in row.keys() else "[]", []),
            "workspace_refs": self._loads(row["workspace_refs_json"] if "workspace_refs_json" in row.keys() else "[]", []),
            "parent_session_id": row["parent_session_id"] if "parent_session_id" in row.keys() else None,
            "forked_from_turn_id": row["forked_from_turn_id"] if "forked_from_turn_id" in row.keys() else None,
            "scratch_mode": bool(row["scratch_mode"]) if "scratch_mode" in row.keys() else False,
            "world_fork_id": row["world_fork_id"] if "world_fork_id" in row.keys() else None,
            "last_model": row["last_model"],
            "last_mode": row["last_mode"],
            "last_reasoning": row["last_reasoning"],
            "turn_count": int(row["turn_count"] or 0),
            "prompt_preview": row["prompt_preview"] or "",
        }

    def _turn_row(self, row: sqlite3.Row, *, include_context: bool) -> dict[str, Any]:
        keys = set(row.keys())
        edited = row["edited_story"] or ""
        status = row["feedback_status"] or "unreviewed"
        result: dict[str, Any] = {
            "id": row["id"],
            "session_id": row["session_id"],
            "run_id": row["run_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "user_prompt": row["user_prompt"],
            "story": row["story"],
            "final_story": edited if status == "edited_accept" and edited else row["story"],
            "model": row["model"],
            "mode": row["mode"],
            "reasoning": row["reasoning"],
            "projection_mode": row["projection_mode"],
            "reasoning_text": row["reasoning_text"] or "",
            "stats": self._loads(row["stats_json"], {}),
            "post_validation": self._loads(row["post_validation_json"], {}),
            "feedback_status": status,
            "feedback_issues": self._loads(row["feedback_issues_json"], []),
            "feedback_note": row["feedback_note"] or "",
            "edited_story": edited,
        }
        if include_context and "wcf" in keys:
            result.update({
                "wcf": row["wcf"] or "",
                "aif_core": row["aif_core"] or "",
                "session_context": row["session_context"] or "",
                "workspace_context": row["workspace_context"] if "workspace_context" in keys else "",
                "workspace_scope": self._loads(row["workspace_scope_json"] if "workspace_scope_json" in keys else "{}", {}),
                "workspace_refs": self._loads(row["workspace_refs_json"] if "workspace_refs_json" in keys else "[]", []),
                "lineage": self._loads(row["lineage_json"] if "lineage_json" in keys else "{}", {}),
                "projections": self._loads(row["projections_json"], []),
                "wcf_validation": self._loads(row["wcf_validation_json"], {}),
            })
        return result
