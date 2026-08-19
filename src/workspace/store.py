from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock
from typing import Any, Iterable
from uuid import uuid4
from src.domain_events import emit_domain_event


WORKSPACE_SCHEMA_VERSION = 7
WORLD_BIBLE_PROJECT_ID = "PROJ-WORLD-BIBLE"
WORLD_BIBLE_WORLD_ID = "WORLD-BIBLE-MAIN"
WORLD_BIBLE_BRANCH_ID = "BRANCH-BIBLE-MAIN"
CANON_STATUSES = {
    "canon", "draft", "provisional", "retconned", "deprecated", "what_if"
}
ENTITY_TYPES = {"character", "location", "item", "organization", "world_rule", "lore"}
BRANCH_KINDS = {"main", "sandbox", "what_if"}
DOCUMENT_TYPES = {"chapter", "scene", "lore", "note", "outline", "research"}
STAGED_CHANGE_STATUSES = {"pending", "accepted", "rejected"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{prefix}-{stamp}-{uuid4().hex[:8].upper()}"


def slugify(value: str) -> str:
    value = re.sub(r"[^\w\s-]", "", value.lower(), flags=re.UNICODE)
    value = re.sub(r"[-\s]+", "-", value).strip("-")
    return value or uuid4().hex[:8]


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


@dataclass(slots=True)
class SnapshotResult:
    snapshot_id: str
    branch_id: str | None
    mode: str


class WorkspaceStore:
    """Project/world/entity workspace persisted in SQLite.

    The store intentionally uses stable IDs rather than names. A character name
    can exist in many worlds; identity is resolved through:

        entity family -> world variant -> branch override -> scene state

    World and branch inheritance is explicit and never inferred from display
    names alone.
    """

    def __init__(self, database_path: Path | str, *, backup_before_migration: bool = True):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.last_migration_backup: Path | None = self._backup_before_schema_upgrade() if backup_before_migration else None
        self._init_db()

    def _existing_schema_version(self) -> int | None:
        """Return an existing workspace schema version without mutating the DB."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            return None
        try:
            con = sqlite3.connect(self.path, timeout=5)
            try:
                has_meta = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace_meta'"
                ).fetchone()
                if not has_meta:
                    has_tables = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1").fetchone()
                    return 0 if has_tables else None
                row = con.execute(
                    "SELECT value FROM workspace_meta WHERE key='schema_version'"
                ).fetchone()
                return int(row[0]) if row and str(row[0]).isdigit() else None
            finally:
                con.close()
        except sqlite3.DatabaseError:
            return None

    def _backup_before_schema_upgrade(self) -> Path | None:
        """Create a consistent SQLite backup before a destructive schema upgrade.

        This runs once at store startup *before* migrations. Fresh databases and
        databases already at the current schema do not create noise. SQLite's
        backup API is used instead of copying the file so WAL state is included
        consistently when present.
        """
        old_version = self._existing_schema_version()
        if old_version is None or old_version >= WORKSPACE_SCHEMA_VERSION:
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = self.path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        suffix = self.path.suffix or ".db"
        backup_path = backup_dir / (
            f"{self.path.stem}.schema-v{old_version}-before-v{WORKSPACE_SCHEMA_VERSION}-{stamp}{suffix}"
        )
        source = sqlite3.connect(self.path, timeout=30)
        target = sqlite3.connect(backup_path, timeout=30)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        return backup_path

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
                CREATE TABLE IF NOT EXISTS workspace_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    pinned INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0,
                    default_world_id TEXT,
                    settings_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS worlds (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    parent_world_id TEXT,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    canon_status TEXT NOT NULL DEFAULT 'draft',
                    inheritance_mode TEXT NOT NULL DEFAULT 'snapshot',
                    settings_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, slug),
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY(parent_world_id) REFERENCES worlds(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS world_branches (
                    id TEXT PRIMARY KEY,
                    world_id TEXT NOT NULL,
                    parent_branch_id TEXT,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL DEFAULT 'main',
                    canon_status TEXT NOT NULL DEFAULT 'canon',
                    base_snapshot_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(world_id, slug),
                    FOREIGN KEY(world_id) REFERENCES worlds(id) ON DELETE CASCADE,
                    FOREIGN KEY(parent_branch_id) REFERENCES world_branches(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS workspace_folders (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    world_id TEXT,
                    branch_id TEXT,
                    parent_id TEXT,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'mixed',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY(world_id) REFERENCES worlds(id) ON DELETE CASCADE,
                    FOREIGN KEY(branch_id) REFERENCES world_branches(id) ON DELETE CASCADE,
                    FOREIGN KEY(parent_id) REFERENCES workspace_folders(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS entity_families (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    folder_id TEXT,
                    entity_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    shared_core_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, entity_type, slug),
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY(folder_id) REFERENCES workspace_folders(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS entity_variants (
                    id TEXT PRIMARY KEY,
                    family_id TEXT NOT NULL,
                    world_id TEXT NOT NULL,
                    branch_id TEXT,
                    inherit_from_variant_id TEXT,
                    display_name TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    canon_status TEXT NOT NULL DEFAULT 'draft',
                    attributes_json TEXT NOT NULL DEFAULT '{}',
                    voice_json TEXT NOT NULL DEFAULT '{}',
                    knowledge_json TEXT NOT NULL DEFAULT '{}',
                    beliefs_json TEXT NOT NULL DEFAULT '{}',
                    current_state_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(family_id, world_id, branch_id),
                    FOREIGN KEY(family_id) REFERENCES entity_families(id) ON DELETE CASCADE,
                    FOREIGN KEY(world_id) REFERENCES worlds(id) ON DELETE CASCADE,
                    FOREIGN KEY(branch_id) REFERENCES world_branches(id) ON DELETE CASCADE,
                    FOREIGN KEY(inherit_from_variant_id) REFERENCES entity_variants(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS relationships (
                    id TEXT PRIMARY KEY,
                    world_id TEXT NOT NULL,
                    branch_id TEXT,
                    subject_variant_id TEXT NOT NULL,
                    object_variant_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'current',
                    canon_status TEXT NOT NULL DEFAULT 'draft',
                    attributes_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(world_id) REFERENCES worlds(id) ON DELETE CASCADE,
                    FOREIGN KEY(branch_id) REFERENCES world_branches(id) ON DELETE CASCADE,
                    FOREIGN KEY(subject_variant_id) REFERENCES entity_variants(id) ON DELETE CASCADE,
                    FOREIGN KEY(object_variant_id) REFERENCES entity_variants(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS workspace_tags (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    color TEXT NOT NULL DEFAULT '#6b7280',
                    kind TEXT NOT NULL DEFAULT 'organizational',
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, slug),
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS workspace_tag_links (
                    tag_id TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    PRIMARY KEY(tag_id, resource_type, resource_id),
                    FOREIGN KEY(tag_id) REFERENCES workspace_tags(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS workspace_documents (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    world_id TEXT,
                    branch_id TEXT,
                    folder_id TEXT,
                    document_type TEXT NOT NULL DEFAULT 'scene',
                    title TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'planned',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY(world_id) REFERENCES worlds(id) ON DELETE CASCADE,
                    FOREIGN KEY(branch_id) REFERENCES world_branches(id) ON DELETE CASCADE,
                    FOREIGN KEY(folder_id) REFERENCES workspace_folders(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS canon_facts (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    world_id TEXT,
                    branch_id TEXT,
                    owner_type TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    authority TEXT NOT NULL DEFAULT 'user_explicit',
                    source_type TEXT NOT NULL DEFAULT 'manual',
                    source_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY(world_id) REFERENCES worlds(id) ON DELETE CASCADE,
                    FOREIGN KEY(branch_id) REFERENCES world_branches(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS context_pins (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    world_id TEXT,
                    branch_id TEXT,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'world',
                    priority INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, world_id, branch_id, resource_type, resource_id, scope),
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY(world_id) REFERENCES worlds(id) ON DELETE CASCADE,
                    FOREIGN KEY(branch_id) REFERENCES world_branches(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS workspace_revisions (
                    id TEXT PRIMARY KEY,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    content_json TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(resource_type, resource_id, version)
                );

                CREATE TABLE IF NOT EXISTS world_snapshots (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    world_id TEXT NOT NULL,
                    branch_id TEXT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY(world_id) REFERENCES worlds(id) ON DELETE CASCADE,
                    FOREIGN KEY(branch_id) REFERENCES world_branches(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS entity_templates (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    template_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, entity_type, name),
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS scene_dependencies (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    world_id TEXT,
                    branch_id TEXT,
                    scene_document_id TEXT NOT NULL,
                    requirement_type TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    condition_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY(world_id) REFERENCES worlds(id) ON DELETE CASCADE,
                    FOREIGN KEY(branch_id) REFERENCES world_branches(id) ON DELETE CASCADE,
                    FOREIGN KEY(scene_document_id) REFERENCES workspace_documents(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS workspace_conflicts (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    world_id TEXT,
                    branch_id TEXT,
                    owner_type TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    left_json TEXT NOT NULL,
                    right_json TEXT NOT NULL,
                    conflict_class TEXT NOT NULL DEFAULT 'hard_contradiction',
                    status TEXT NOT NULL DEFAULT 'open',
                    resolution_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY(world_id) REFERENCES worlds(id) ON DELETE CASCADE,
                    FOREIGN KEY(branch_id) REFERENCES world_branches(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS project_world_links (
                    project_id TEXT NOT NULL,
                    world_id TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'reference',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, world_id),
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY(world_id) REFERENCES worlds(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS project_manifest_refs (
                    project_id TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    label TEXT NOT NULL DEFAULT '',
                    priority INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, resource_type, resource_id),
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS project_overlays (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    world_id TEXT,
                    branch_id TEXT,
                    owner_type TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, world_id, branch_id, owner_type, owner_id, path),
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY(world_id) REFERENCES worlds(id) ON DELETE CASCADE,
                    FOREIGN KEY(branch_id) REFERENCES world_branches(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS project_active_scenes (
                    project_id TEXT PRIMARY KEY,
                    document_id TEXT,
                    world_id TEXT,
                    branch_id TEXT,
                    pov_variant_id TEXT,
                    location_variant_id TEXT,
                    participants_json TEXT NOT NULL DEFAULT '[]',
                    narrative_time TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY(document_id) REFERENCES workspace_documents(id) ON DELETE SET NULL,
                    FOREIGN KEY(world_id) REFERENCES worlds(id) ON DELETE SET NULL,
                    FOREIGN KEY(branch_id) REFERENCES world_branches(id) ON DELETE SET NULL,
                    FOREIGN KEY(pov_variant_id) REFERENCES entity_variants(id) ON DELETE SET NULL,
                    FOREIGN KEY(location_variant_id) REFERENCES entity_variants(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS project_scene_cards (
                    document_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    world_id TEXT,
                    branch_id TEXT,
                    pov_variant_id TEXT,
                    location_variant_id TEXT,
                    participants_json TEXT NOT NULL DEFAULT '[]',
                    narrative_time TEXT NOT NULL DEFAULT '',
                    target_outcome TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'planned',
                    sort_order REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES workspace_documents(id) ON DELETE CASCADE,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY(world_id) REFERENCES worlds(id) ON DELETE SET NULL,
                    FOREIGN KEY(branch_id) REFERENCES world_branches(id) ON DELETE SET NULL,
                    FOREIGN KEY(pov_variant_id) REFERENCES entity_variants(id) ON DELETE SET NULL,
                    FOREIGN KEY(location_variant_id) REFERENCES entity_variants(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS staged_changes (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    world_id TEXT,
                    branch_id TEXT,
                    session_id TEXT,
                    turn_id TEXT,
                    owner_type TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    old_value_json TEXT,
                    proposed_value_json TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    status TEXT NOT NULL DEFAULT 'pending',
                    source_text TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY(world_id) REFERENCES worlds(id) ON DELETE CASCADE,
                    FOREIGN KEY(branch_id) REFERENCES world_branches(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS timeline_events (
                    id TEXT PRIMARY KEY,
                    world_id TEXT NOT NULL,
                    branch_id TEXT,
                    owner_type TEXT,
                    owner_id TEXT,
                    time_label TEXT NOT NULL DEFAULT '',
                    order_key REAL NOT NULL DEFAULT 0,
                    event_type TEXT NOT NULL DEFAULT 'event',
                    summary TEXT NOT NULL,
                    state_patch_json TEXT NOT NULL DEFAULT '{}',
                    source_type TEXT NOT NULL DEFAULT 'manual',
                    source_id TEXT,
                    status TEXT NOT NULL DEFAULT 'canon',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(world_id) REFERENCES worlds(id) ON DELETE CASCADE,
                    FOREIGN KEY(branch_id) REFERENCES world_branches(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS context_recipes (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    recipe_json TEXT NOT NULL DEFAULT '{}',
                    builtin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, name),
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_worlds_project ON worlds(project_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_branches_world ON world_branches(world_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_variants_scope ON entity_variants(world_id, branch_id, family_id);
                CREATE INDEX IF NOT EXISTS idx_relationships_scope ON relationships(world_id, branch_id);
                CREATE INDEX IF NOT EXISTS idx_documents_scope ON workspace_documents(project_id, world_id, branch_id);
                CREATE INDEX IF NOT EXISTS idx_facts_owner ON canon_facts(owner_type, owner_id, path);
                CREATE INDEX IF NOT EXISTS idx_templates_project ON entity_templates(project_id, entity_type, name);
                CREATE INDEX IF NOT EXISTS idx_dependencies_scene ON scene_dependencies(scene_document_id);
                CREATE INDEX IF NOT EXISTS idx_conflicts_scope ON workspace_conflicts(project_id, world_id, branch_id, status);
                CREATE INDEX IF NOT EXISTS idx_project_world_links_project ON project_world_links(project_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_manifest_refs_project ON project_manifest_refs(project_id, priority DESC);
                CREATE INDEX IF NOT EXISTS idx_overlays_scope ON project_overlays(project_id, world_id, branch_id);
                CREATE INDEX IF NOT EXISTS idx_scene_cards_project ON project_scene_cards(project_id, sort_order, updated_at);
                CREATE INDEX IF NOT EXISTS idx_staged_changes_scope ON staged_changes(project_id, world_id, branch_id, status);
                CREATE INDEX IF NOT EXISTS idx_timeline_scope ON timeline_events(world_id, branch_id, order_key, created_at);
                """
            )
            family_columns = {
                row[1] for row in con.execute("PRAGMA table_info(entity_families)").fetchall()
            }
            if "folder_id" not in family_columns:
                con.execute("ALTER TABLE entity_families ADD COLUMN folder_id TEXT")
            # v1.1 writing vocabulary: Draft is no longer an object class/status
            # exposed in the UI. Preserve document content while normalizing the
            # old broad states to Manuscript workflow states.
            con.execute("UPDATE workspace_documents SET document_type='scene' WHERE document_type='draft'")
            con.execute("UPDATE workspace_documents SET status='writing' WHERE status='draft'")
            con.execute("UPDATE workspace_documents SET status='revising' WHERE status='provisional'")
            con.execute("UPDATE workspace_documents SET status='final' WHERE status='canon'")
            self._seed_world_bible(con)
            self._seed_templates(con)
            self._seed_context_recipes(con)
            con.execute(
                "INSERT INTO workspace_meta(key,value) VALUES('schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(WORKSPACE_SCHEMA_VERSION),),
            )

    @staticmethod
    def _seed_templates(con: sqlite3.Connection) -> None:
        now = utc_now()
        templates = [
            ("TPL-GLOBAL-CHARACTER", None, "Character", "character", "Identity, personality, voice, knowledge, relationships, history, and current state.", {
                "shared_core": {"identity": {}, "appearance_baseline": {}},
                "attributes": {"personality": {}, "appearance": {}, "occupation": None},
                "voice": {"register": "follow_context", "rhythm": None, "terms_of_address": []},
                "knowledge": {}, "beliefs": {}, "current_state": {},
            }),
            ("TPL-GLOBAL-LOCATION", None, "Location", "location", "Spatial, sensory, social, and world-rule context.", {
                "shared_core": {"kind": None}, "attributes": {"geometry": {}, "atmosphere": {}, "access": {}},
                "current_state": {},
            }),
            ("TPL-GLOBAL-ITEM", None, "Item", "item", "Physical properties, ownership, affordances, and state.", {
                "shared_core": {"kind": None}, "attributes": {"material": None, "dimensions": {}, "affordances": []},
                "current_state": {},
            }),
            ("TPL-GLOBAL-ORGANIZATION", None, "Organization", "organization", "Members, structure, goals, knowledge, and relationships.", {
                "shared_core": {"kind": None}, "attributes": {"purpose": None, "hierarchy": {}, "members": []},
                "knowledge": {}, "current_state": {},
            }),
            ("TPL-GLOBAL-WORLD-RULE", None, "World Rule", "world_rule", "A bounded law, mechanism, exception, and consequence.", {
                "shared_core": {"domain": None}, "attributes": {"rule": None, "mechanism": None, "exceptions": [], "consequences": []},
            }),
        ]
        for template_id, project_id, name, entity_type, description, payload in templates:
            con.execute(
                "INSERT OR IGNORE INTO entity_templates(id,project_id,name,entity_type,description,template_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (template_id, project_id, name, entity_type, description, _dumps(payload), now, now),
            )

    @staticmethod
    def _seed_world_bible(con: sqlite3.Connection) -> None:
        """Create the internal backing scope for global Library objects.

        The backing project is deliberately archived and omitted from normal
        project lists. Projects reference worlds; they do not own the Bible.
        Keeping the existing FK shape lets v1 databases migrate without a
        destructive table rewrite.
        """
        now = utc_now()
        con.execute(
            "INSERT OR IGNORE INTO projects(id,name,slug,description,pinned,archived,default_world_id,settings_json,created_at,updated_at) "
            "VALUES(?,?,?,?,0,1,?,?,?,?)",
            (
                WORLD_BIBLE_PROJECT_ID,
                "Library",
                "__world-bible__",
                "Internal backing scope for global Arline canon.",
                WORLD_BIBLE_WORLD_ID,
                _dumps({"system": True, "role": "world_bible"}),
                now,
                now,
            ),
        )
        con.execute(
            "INSERT OR IGNORE INTO worlds(id,project_id,parent_world_id,name,slug,description,canon_status,inheritance_mode,settings_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                WORLD_BIBLE_WORLD_ID,
                WORLD_BIBLE_PROJECT_ID,
                None,
                "Main",
                "main",
                "Primary shared world.",
                "canon",
                "none",
                _dumps({"system_seed": True}),
                now,
                now,
            ),
        )
        con.execute(
            "INSERT OR IGNORE INTO world_branches(id,world_id,parent_branch_id,name,slug,description,kind,canon_status,base_snapshot_id,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                WORLD_BIBLE_BRANCH_ID,
                WORLD_BIBLE_WORLD_ID,
                None,
                "Main",
                "main",
                "Primary timeline",
                "main",
                "canon",
                None,
                now,
                now,
            ),
        )

    @staticmethod
    def _seed_context_recipes(con: sqlite3.Connection) -> None:
        now = utc_now()
        recipes = [
            (
                "RECIPE-STORY",
                "Story Writing",
                "Balanced long-form narrative context.",
                {"active_scene": True, "explicit_refs": True, "pins": True, "relationships": True, "recent_turns": 5, "world_canon": "relevant", "project_documents": "relevant"},
            ),
            (
                "RECIPE-DIALOGUE",
                "Dialogue",
                "Prioritize speaker voice, relationship state, and recent dialogue.",
                {"active_scene": True, "explicit_refs": True, "pins": True, "relationships": True, "recent_turns": 8, "voice": "deep", "world_canon": "compact"},
            ),
            (
                "RECIPE-LORE",
                "Lore Analysis",
                "Deep entity history, canon, relationships, and timeline.",
                {"active_scene": False, "explicit_refs": True, "pins": True, "relationships": True, "timeline": True, "world_canon": "deep", "project_documents": "relevant"},
            ),
            (
                "RECIPE-CONTINUITY",
                "Continuity Check",
                "Favor state, timeline, staged changes, and contradictions.",
                {"active_scene": True, "explicit_refs": True, "pins": True, "relationships": True, "timeline": True, "conflicts": True, "recent_turns": 10, "world_canon": "deep"},
            ),
        ]
        for recipe_id, name, description, payload in recipes:
            con.execute(
                "INSERT OR IGNORE INTO context_recipes(id,project_id,name,description,recipe_json,builtin,created_at,updated_at) "
                "VALUES(?,?,?,?,?,1,?,?)",
                (recipe_id, None, name, description, _dumps(payload), now, now),
            )

    # ------------------------------------------------------------------
    # Generic row helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _remove_variant_from_scene_participants_tx(
        con: sqlite3.Connection, variant_id: str
    ) -> None:
        """Remove a deleted variant from JSON participant lists.

        POV/location columns are real foreign keys and are handled by SQLite's
        ON DELETE SET NULL rules. Participant lists intentionally stay JSON so
        they can preserve ordering, therefore they need explicit cleanup.
        """
        now = utc_now()
        for table, key_column in (
            ("project_active_scenes", "project_id"),
            ("project_scene_cards", "document_id"),
        ):
            rows = con.execute(
                f"SELECT {key_column},participants_json FROM {table}"
            ).fetchall()
            for row in rows:
                participants = _loads(row["participants_json"], [])
                if not isinstance(participants, list) or variant_id not in participants:
                    continue
                cleaned = [item for item in participants if item != variant_id]
                con.execute(
                    f"UPDATE {table} SET participants_json=?,updated_at=? WHERE {key_column}=?",
                    (_dumps(cleaned), now, row[key_column]),
                )

    @staticmethod
    def _purge_resource_refs_tx(
        con: sqlite3.Connection, resource_type: str, resource_id: str, *, purge_owned_facts: bool = True
    ) -> None:
        """Remove polymorphic side-table references for a deleted resource.

        Several v1.1 tables deliberately use ``(resource_type, resource_id)``
        instead of hard foreign keys so the same feature can point at worlds,
        sheets, variants, documents, facts, and relationships. Deleting an
        object must therefore sweep those references explicitly to avoid
        ghost working-set entries, overlays, staged canon, or timeline state.
        """
        if purge_owned_facts:
            fact_rows = con.execute(
                "SELECT id FROM canon_facts WHERE owner_type=? AND owner_id=?",
                (resource_type, resource_id),
            ).fetchall()
            for row in fact_rows:
                WorkspaceStore._purge_resource_refs_tx(
                    con, "fact", row["id"], purge_owned_facts=False
                )
            con.execute(
                "DELETE FROM canon_facts WHERE owner_type=? AND owner_id=?",
                (resource_type, resource_id),
            )

        # Foundation/UX side tables use polymorphic references and cannot rely
        # on SQLite FK cascades. Keep Project manifests and narrative state free
        # of dangling IDs whenever their target disappears.
        con.execute(
            "DELETE FROM project_manifest_refs WHERE resource_type=? AND resource_id=?",
            (resource_type, resource_id),
        )
        con.execute(
            "DELETE FROM project_overlays WHERE owner_type=? AND owner_id=?",
            (resource_type, resource_id),
        )
        con.execute(
            "DELETE FROM staged_changes WHERE owner_type=? AND owner_id=?",
            (resource_type, resource_id),
        )
        con.execute(
            "DELETE FROM timeline_events WHERE owner_type=? AND owner_id=?",
            (resource_type, resource_id),
        )

        if resource_type == "entity_variant":
            WorkspaceStore._remove_variant_from_scene_participants_tx(con, resource_id)

        con.execute(
            "DELETE FROM workspace_tag_links WHERE resource_type=? AND resource_id=?",
            (resource_type, resource_id),
        )
        con.execute(
            "DELETE FROM context_pins WHERE resource_type=? AND resource_id=?",
            (resource_type, resource_id),
        )
        con.execute(
            "DELETE FROM workspace_revisions WHERE resource_type=? AND resource_id=?",
            (resource_type, resource_id),
        )
        con.execute(
            "DELETE FROM scene_dependencies WHERE target_type=? AND target_id=?",
            (resource_type, resource_id),
        )
        con.execute(
            "DELETE FROM workspace_conflicts WHERE owner_type=? AND owner_id=?",
            (resource_type, resource_id),
        )

    @staticmethod
    def _purge_resource_collection_tx(
        con: sqlite3.Connection, resource_type: str, resource_ids: Iterable[str]
    ) -> None:
        for resource_id in resource_ids:
            WorkspaceStore._purge_resource_refs_tx(con, resource_type, resource_id)

    @staticmethod
    def _project_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "name": row["name"], "slug": row["slug"],
            "description": row["description"], "pinned": bool(row["pinned"]),
            "archived": bool(row["archived"]), "default_world_id": row["default_world_id"],
            "settings": _loads(row["settings_json"], {}),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    @staticmethod
    def _world_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "project_id": row["project_id"],
            "parent_world_id": row["parent_world_id"], "name": row["name"],
            "slug": row["slug"], "description": row["description"],
            "canon_status": row["canon_status"], "inheritance_mode": row["inheritance_mode"],
            "settings": _loads(row["settings_json"], {}),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    @staticmethod
    def _branch_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "world_id": row["world_id"],
            "parent_branch_id": row["parent_branch_id"], "name": row["name"],
            "slug": row["slug"], "description": row["description"],
            "kind": row["kind"], "canon_status": row["canon_status"],
            "base_snapshot_id": row["base_snapshot_id"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    @staticmethod
    def _family_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "project_id": row["project_id"],
            "folder_id": row["folder_id"] if "folder_id" in row.keys() else None,
            "entity_type": row["entity_type"], "name": row["name"],
            "slug": row["slug"], "description": row["description"],
            "shared_core": _loads(row["shared_core_json"], {}),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    @staticmethod
    def _variant_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "family_id": row["family_id"],
            "world_id": row["world_id"], "branch_id": row["branch_id"],
            "inherit_from_variant_id": row["inherit_from_variant_id"],
            "display_name": row["display_name"], "summary": row["summary"],
            "canon_status": row["canon_status"],
            "attributes": _loads(row["attributes_json"], {}),
            "voice": _loads(row["voice_json"], {}),
            "knowledge": _loads(row["knowledge_json"], {}),
            "beliefs": _loads(row["beliefs_json"], {}),
            "current_state": _loads(row["current_state_json"], {}),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    @staticmethod
    def _relationship_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "world_id": row["world_id"], "branch_id": row["branch_id"],
            "subject_variant_id": row["subject_variant_id"],
            "object_variant_id": row["object_variant_id"],
            "relation_type": row["relation_type"], "status": row["status"],
            "canon_status": row["canon_status"],
            "attributes": _loads(row["attributes_json"], {}),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    @staticmethod
    def _document_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "project_id": row["project_id"],
            "world_id": row["world_id"], "branch_id": row["branch_id"],
            "folder_id": row["folder_id"], "document_type": row["document_type"],
            "title": row["title"], "content": row["content"], "status": row["status"],
            "sort_order": row["sort_order"], "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # ------------------------------------------------------------------
    # Projects and worlds
    # ------------------------------------------------------------------

    def create_project(
        self,
        name: str,
        *,
        description: str = "",
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValueError("Project name cannot be blank")
        project_id = make_id("PROJ")
        now = utc_now()
        base_slug = slugify(name)
        with self._lock, self._connection() as con:
            slug = self._unique_slug(con, "projects", base_slug)
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute(
                    "INSERT INTO projects(id,name,slug,description,settings_json,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (project_id, name, slug, description.strip(), _dumps(settings or {}), now, now),
                )
                con.execute(
                    "UPDATE projects SET default_world_id=? WHERE id=?",
                    (WORLD_BIBLE_WORLD_ID, project_id),
                )
                con.execute(
                    "INSERT OR IGNORE INTO project_world_links(project_id,world_id,role,created_at) VALUES(?,?,?,?)",
                    (project_id, WORLD_BIBLE_WORLD_ID, "primary", now),
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        result = self.get_project(project_id)
        result["default_branch_id"] = WORLD_BIBLE_BRANCH_ID
        return result

    def list_projects(self, *, search: str = "", include_archived: bool = False) -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []
        if not include_archived:
            where.append("archived=0")
        if search.strip():
            where.append("(name LIKE ? COLLATE NOCASE OR description LIKE ? COLLATE NOCASE)")
            like = f"%{search.strip()}%"
            params.extend([like, like])
        with self._connection() as con:
            rows = con.execute(
                f"SELECT * FROM projects WHERE {' AND '.join(where)} "
                "ORDER BY pinned DESC, updated_at DESC",
                params,
            ).fetchall()
        return [self._project_row(row) for row in rows]

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(project_id)
        result = self._project_row(row)
        result["worlds"] = self.list_worlds(project_id)
        return result

    def update_project(self, project_id: str, **changes: Any) -> dict[str, Any]:
        allowed = {"name", "description", "pinned", "archived", "default_world_id", "settings"}
        fields: list[str] = []
        params: list[Any] = []
        with self._lock, self._connection() as con:
            if "name" in changes and changes["name"] is not None:
                name = str(changes["name"]).strip()
                if not name:
                    raise ValueError("Project name cannot be blank")
                fields.append("name=?")
                params.append(name)
            for key in ("description", "default_world_id"):
                if key in changes and changes[key] is not None:
                    fields.append(f"{key}=?")
                    params.append(str(changes[key]).strip() or None)
            for key in ("pinned", "archived"):
                if key in changes and changes[key] is not None:
                    fields.append(f"{key}=?")
                    params.append(1 if changes[key] else 0)
            if "settings" in changes and changes["settings"] is not None:
                fields.append("settings_json=?")
                params.append(_dumps(changes["settings"]))
            if fields:
                fields.append("updated_at=?")
                params.extend([utc_now(), project_id])
                cur = con.execute(
                    f"UPDATE projects SET {', '.join(fields)} WHERE id=?",
                    params,
                )
                if cur.rowcount == 0:
                    raise KeyError(project_id)
                if changes.get("default_world_id"):
                    con.execute(
                        "INSERT OR IGNORE INTO project_world_links(project_id,world_id,role,created_at) VALUES(?,?,?,?)",
                        (project_id, changes["default_world_id"], "primary", utc_now()),
                    )
        return self.get_project(project_id)

    def delete_project(self, project_id: str) -> None:
        if project_id == WORLD_BIBLE_PROJECT_ID:
            raise ValueError("The Library backing scope is protected")
        with self._lock, self._connection() as con:
            exists = con.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone()
            if exists is None:
                raise KeyError(project_id)

            # v1.0/v1.1 stored Bible objects under projects. Preserve those
            # objects by detaching them into the hidden global backing scope
            # before deleting the project workspace itself.
            self._detach_legacy_bible_from_project_tx(con, project_id)

            documents = [row["id"] for row in con.execute(
                "SELECT id FROM workspace_documents WHERE project_id=?", (project_id,)
            ).fetchall()]
            templates = [row["id"] for row in con.execute(
                "SELECT id FROM entity_templates WHERE project_id=?", (project_id,)
            ).fetchall()]
            self._purge_resource_collection_tx(con, "document", documents)
            self._purge_resource_collection_tx(con, "template", templates)
            con.execute("DELETE FROM projects WHERE id=?", (project_id,))

    def _detach_legacy_bible_from_project_tx(self, con: sqlite3.Connection, project_id: str) -> None:
        worlds = con.execute(
            "SELECT id,slug FROM worlds WHERE project_id=?", (project_id,)
        ).fetchall()
        for row in worlds:
            slug = self._unique_slug(
                con, "worlds", row["slug"] or "world",
                scope_column="project_id", scope_value=WORLD_BIBLE_PROJECT_ID,
            )
            con.execute(
                "UPDATE worlds SET project_id=?,slug=?,updated_at=? WHERE id=?",
                (WORLD_BIBLE_PROJECT_ID, slug, utc_now(), row["id"]),
            )
            con.execute(
                "UPDATE world_snapshots SET project_id=? WHERE world_id=?",
                (WORLD_BIBLE_PROJECT_ID, row["id"]),
            )
            con.execute(
                "UPDATE canon_facts SET project_id=? WHERE world_id=?",
                (WORLD_BIBLE_PROJECT_ID, row["id"]),
            )
            con.execute(
                "UPDATE workspace_conflicts SET project_id=? WHERE world_id=?",
                (WORLD_BIBLE_PROJECT_ID, row["id"]),
            )

        families = con.execute(
            "SELECT id,entity_type,slug FROM entity_families WHERE project_id=?", (project_id,)
        ).fetchall()
        for row in families:
            slug = self._unique_slug(
                con, "entity_families", row["slug"] or "entity",
                scope_column="project_id", scope_value=WORLD_BIBLE_PROJECT_ID,
                extra_scope=("entity_type", row["entity_type"]),
            )
            con.execute(
                "UPDATE entity_families SET project_id=?,folder_id=NULL,slug=?,updated_at=? WHERE id=?",
                (WORLD_BIBLE_PROJECT_ID, slug, utc_now(), row["id"]),
            )
            variant_ids = [r["id"] for r in con.execute(
                "SELECT id FROM entity_variants WHERE family_id=?", (row["id"],)
            ).fetchall()]
            if variant_ids:
                placeholders = ",".join("?" for _ in variant_ids)
                con.execute(
                    f"UPDATE canon_facts SET project_id=? WHERE owner_type='entity_variant' AND owner_id IN ({placeholders})",
                    [WORLD_BIBLE_PROJECT_ID, *variant_ids],
                )
            con.execute(
                "UPDATE canon_facts SET project_id=? WHERE owner_type='entity_family' AND owner_id=?",
                (WORLD_BIBLE_PROJECT_ID, row["id"]),
            )

    def _create_world_tx(
        self,
        con: sqlite3.Connection,
        *,
        project_id: str,
        name: str,
        description: str,
        parent_world_id: str | None,
        canon_status: str,
        inheritance_mode: str,
        clone_parent: bool,
    ) -> tuple[str, str]:
        world_id = make_id("WORLD")
        branch_id = make_id("BRANCH")
        now = utc_now()
        world_slug = self._unique_slug(
            con, "worlds", slugify(name), scope_column="project_id", scope_value=project_id
        )
        con.execute(
            "INSERT INTO worlds(id,project_id,parent_world_id,name,slug,description,canon_status,"
            "inheritance_mode,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                world_id, project_id, parent_world_id, name.strip(), world_slug,
                description.strip(), canon_status, inheritance_mode, now, now,
            ),
        )
        con.execute(
            "INSERT INTO world_branches(id,world_id,name,slug,description,kind,canon_status,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                branch_id, world_id, "Main", "main", "Primary timeline",
                "main", "canon" if canon_status == "canon" else canon_status, now, now,
            ),
        )
        if parent_world_id and clone_parent:
            self._clone_world_content_tx(con, parent_world_id, world_id)
        return world_id, branch_id

    def create_world(
        self,
        project_id: str | None,
        name: str,
        *,
        description: str = "",
        parent_world_id: str | None = None,
        canon_status: str = "draft",
        inheritance_mode: str = "snapshot",
        clone_parent: bool = True,
    ) -> dict[str, Any]:
        if canon_status not in CANON_STATUSES:
            raise ValueError("Unsupported canon status")
        name = name.strip()
        if not name:
            raise ValueError("World name cannot be blank")
        linking_project_id = project_id if project_id and project_id != WORLD_BIBLE_PROJECT_ID else None
        owner_project_id = WORLD_BIBLE_PROJECT_ID
        with self._lock, self._connection() as con:
            if linking_project_id and con.execute("SELECT 1 FROM projects WHERE id=?", (linking_project_id,)).fetchone() is None:
                raise KeyError(linking_project_id)
            if parent_world_id:
                parent = con.execute("SELECT id FROM worlds WHERE id=?", (parent_world_id,)).fetchone()
                if parent is None:
                    raise ValueError("Parent world does not exist")
            con.execute("BEGIN IMMEDIATE")
            try:
                world_id, branch_id = self._create_world_tx(
                    con,
                    project_id=owner_project_id,
                    name=name,
                    description=description,
                    parent_world_id=parent_world_id,
                    canon_status=canon_status,
                    inheritance_mode=inheritance_mode,
                    clone_parent=clone_parent,
                )
                if linking_project_id:
                    con.execute(
                        "INSERT OR IGNORE INTO project_world_links(project_id,world_id,role,created_at) VALUES(?,?,?,?)",
                        (linking_project_id, world_id, "reference", utc_now()),
                    )
                    con.execute("UPDATE projects SET updated_at=? WHERE id=?", (utc_now(), linking_project_id))
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        result = self.get_world(world_id)
        result["default_branch_id"] = branch_id
        return result

    def fork_world(
        self,
        parent_world_id: str,
        name: str,
        *,
        description: str = "",
        canon_status: str = "what_if",
    ) -> dict[str, Any]:
        return self.create_world(
            None, name, description=description,
            parent_world_id=parent_world_id, canon_status=canon_status,
            inheritance_mode="snapshot", clone_parent=True,
        )

    def _clone_world_content_tx(
        self, con: sqlite3.Connection, source_world_id: str, target_world_id: str
    ) -> None:
        mapping: dict[str, str] = {}
        variants = con.execute(
            "SELECT * FROM entity_variants WHERE world_id=? AND branch_id IS NULL",
            (source_world_id,),
        ).fetchall()
        now = utc_now()
        for row in variants:
            new_id = make_id("VAR")
            mapping[row["id"]] = new_id
            con.execute(
                """
                INSERT INTO entity_variants(
                    id,family_id,world_id,branch_id,inherit_from_variant_id,display_name,summary,
                    canon_status,attributes_json,voice_json,knowledge_json,beliefs_json,current_state_json,
                    created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    new_id, row["family_id"], target_world_id, None, row["id"],
                    row["display_name"], row["summary"], row["canon_status"],
                    row["attributes_json"], row["voice_json"], row["knowledge_json"],
                    row["beliefs_json"], row["current_state_json"], now, now,
                ),
            )
        relationships = con.execute(
            "SELECT * FROM relationships WHERE world_id=? AND branch_id IS NULL",
            (source_world_id,),
        ).fetchall()
        for row in relationships:
            sub = mapping.get(row["subject_variant_id"])
            obj = mapping.get(row["object_variant_id"])
            if not sub or not obj:
                continue
            con.execute(
                "INSERT INTO relationships(id,world_id,branch_id,subject_variant_id,object_variant_id,"
                "relation_type,status,canon_status,attributes_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    make_id("REL"), target_world_id, None, sub, obj,
                    row["relation_type"], row["status"], row["canon_status"],
                    row["attributes_json"], now, now,
                ),
            )
        facts = con.execute(
            "SELECT * FROM canon_facts WHERE world_id=? AND branch_id IS NULL",
            (source_world_id,),
        ).fetchall()
        for row in facts:
            owner_id = mapping.get(row["owner_id"], row["owner_id"])
            con.execute(
                "INSERT INTO canon_facts(id,project_id,world_id,branch_id,owner_type,owner_id,path,value_json,"
                "status,authority,source_type,source_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    make_id("FACT"), row["project_id"], target_world_id, None,
                    row["owner_type"], owner_id, row["path"], row["value_json"],
                    row["status"], row["authority"], "world_inheritance", row["id"], now, now,
                ),
            )

    def list_worlds(self, project_id: str | None = None) -> list[dict[str, Any]]:
        with self._connection() as con:
            if project_id:
                rows = con.execute(
                    "SELECT DISTINCT w.* FROM worlds w LEFT JOIN project_world_links l ON l.world_id=w.id "
                    "WHERE w.project_id=? OR l.project_id=? ORDER BY w.created_at ASC",
                    (project_id, project_id),
                ).fetchall()
            else:
                rows = con.execute("SELECT * FROM worlds ORDER BY created_at ASC").fetchall()
        return [self._world_row(row) for row in rows]

    def link_project_world(self, project_id: str, world_id: str, *, role: str = "reference") -> dict[str, Any]:
        with self._lock, self._connection() as con:
            if con.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is None:
                raise KeyError(project_id)
            if con.execute("SELECT 1 FROM worlds WHERE id=?", (world_id,)).fetchone() is None:
                raise KeyError(world_id)
            con.execute(
                "INSERT INTO project_world_links(project_id,world_id,role,created_at) VALUES(?,?,?,?) "
                "ON CONFLICT(project_id,world_id) DO UPDATE SET role=excluded.role",
                (project_id, world_id, role, utc_now()),
            )
        return {"project_id": project_id, "world_id": world_id, "role": role}

    def get_world(self, world_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT * FROM worlds WHERE id=?", (world_id,)).fetchone()
        if row is None:
            raise KeyError(world_id)
        result = self._world_row(row)
        result["branches"] = self.list_branches(world_id)
        result["lineage"] = self.world_lineage(world_id)
        return result

    def update_world(self, world_id: str, **changes: Any) -> dict[str, Any]:
        fields: list[str] = []
        params: list[Any] = []
        for key in ("name", "description", "canon_status", "inheritance_mode"):
            if key in changes and changes[key] is not None:
                value = str(changes[key]).strip()
                if key == "canon_status" and value not in CANON_STATUSES:
                    raise ValueError("Unsupported canon status")
                fields.append(f"{key}=?")
                params.append(value)
        if "settings" in changes and changes["settings"] is not None:
            fields.append("settings_json=?")
            params.append(_dumps(changes["settings"]))
        if fields:
            fields.append("updated_at=?")
            params.extend([utc_now(), world_id])
            with self._lock, self._connection() as con:
                cur = con.execute(
                    f"UPDATE worlds SET {', '.join(fields)} WHERE id=?", params
                )
                if cur.rowcount == 0:
                    raise KeyError(world_id)
        return self.get_world(world_id)

    def world_lineage(self, world_id: str) -> list[dict[str, Any]]:
        lineage: list[dict[str, Any]] = []
        seen: set[str] = set()
        current = world_id
        with self._connection() as con:
            while current and current not in seen:
                seen.add(current)
                row = con.execute("SELECT * FROM worlds WHERE id=?", (current,)).fetchone()
                if row is None:
                    break
                lineage.append(self._world_row(row))
                current = row["parent_world_id"]
        lineage.reverse()
        return lineage

    def delete_world(self, world_id: str) -> None:
        if world_id == WORLD_BIBLE_WORLD_ID:
            raise ValueError("The shared Library main world is protected")
        with self._lock, self._connection() as con:
            row = con.execute(
                "SELECT id,project_id FROM worlds WHERE id=?", (world_id,)
            ).fetchone()
            if row is None:
                raise KeyError(world_id)
            project_id = row["project_id"]

            variants = [r["id"] for r in con.execute(
                "SELECT id FROM entity_variants WHERE world_id=?", (world_id,)
            ).fetchall()]
            relationships = [r["id"] for r in con.execute(
                "SELECT id FROM relationships WHERE world_id=?", (world_id,)
            ).fetchall()]
            branches = [r["id"] for r in con.execute(
                "SELECT id FROM world_branches WHERE world_id=?", (world_id,)
            ).fetchall()]

            # Project files are workspace artifacts, not owned by Library
            # canon. Detach their optional semantic scope before deleting a
            # world so a canon cleanup never destroys chapters/notes/folders.
            branch_placeholders = ",".join("?" for _ in branches)
            now = utc_now()
            if branches:
                con.execute(
                    f"UPDATE workspace_documents SET world_id=NULL,branch_id=NULL,updated_at=? "
                    f"WHERE world_id=? OR branch_id IN ({branch_placeholders})",
                    [now, world_id, *branches],
                )
                con.execute(
                    f"UPDATE workspace_folders SET world_id=NULL,branch_id=NULL,updated_at=? "
                    f"WHERE world_id=? OR branch_id IN ({branch_placeholders})",
                    [now, world_id, *branches],
                )
            else:
                con.execute(
                    "UPDATE workspace_documents SET world_id=NULL,branch_id=NULL,updated_at=? WHERE world_id=?",
                    (now, world_id),
                )
                con.execute(
                    "UPDATE workspace_folders SET world_id=NULL,branch_id=NULL,updated_at=? WHERE world_id=?",
                    (now, world_id),
                )
            facts = [r["id"] for r in con.execute(
                "SELECT id FROM canon_facts WHERE world_id=?", (world_id,)
            ).fetchall()]

            self._purge_resource_collection_tx(con, "relationship", relationships)
            self._purge_resource_collection_tx(con, "entity_variant", variants)
            self._purge_resource_collection_tx(con, "branch", branches)
            self._purge_resource_refs_tx(con, "world", world_id)
            for fact_id in facts:
                self._purge_resource_refs_tx(con, "fact", fact_id, purge_owned_facts=False)

            con.execute("DELETE FROM worlds WHERE id=?", (world_id,))

            # A Project only links to worlds. If a linked world was selected as
            # its default, fall back to the protected shared Main world instead
            # of leaving a dangling semantic pointer.
            con.execute(
                "UPDATE projects SET default_world_id=?,updated_at=? WHERE default_world_id=?",
                (WORLD_BIBLE_WORLD_ID, utc_now(), world_id),
            )

    def compare_worlds(self, left_world_id: str, right_world_id: str) -> dict[str, Any]:
        left = self.get_world(left_world_id)
        right = self.get_world(right_world_id)
        if left["project_id"] != right["project_id"]:
            raise ValueError("World comparison requires the same project")
        with self._connection() as con:
            left_rows = con.execute(
                "SELECT v.*,f.name AS family_name,f.entity_type FROM entity_variants v "
                "JOIN entity_families f ON f.id=v.family_id "
                "WHERE v.world_id=? AND v.branch_id IS NULL",
                (left_world_id,),
            ).fetchall()
            right_rows = con.execute(
                "SELECT v.*,f.name AS family_name,f.entity_type FROM entity_variants v "
                "JOIN entity_families f ON f.id=v.family_id "
                "WHERE v.world_id=? AND v.branch_id IS NULL",
                (right_world_id,),
            ).fetchall()
        lmap = {row["family_id"]: row for row in left_rows}
        rmap = {row["family_id"]: row for row in right_rows}
        rows = []
        for family_id in sorted(set(lmap) | set(rmap), key=lambda fid: (lmap.get(fid) or rmap[fid])["family_name"].lower()):
            lrow = lmap.get(family_id)
            rrow = rmap.get(family_id)
            left_data = self._variant_row(lrow) if lrow else None
            right_data = self._variant_row(rrow) if rrow else None
            rows.append({
                "family_id": family_id,
                "name": (lrow or rrow)["family_name"],
                "entity_type": (lrow or rrow)["entity_type"],
                "left": left_data,
                "right": right_data,
                "difference": self._variant_diff(left_data, right_data),
            })
        return {"left": left, "right": right, "entities": rows}

    @staticmethod
    def _variant_diff(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
        if left is None:
            return {"kind": "right_only"}
        if right is None:
            return {"kind": "left_only"}
        fields = {}
        for key in ("summary", "canon_status", "attributes", "voice", "knowledge", "beliefs", "current_state"):
            if left.get(key) != right.get(key):
                fields[key] = {"left": left.get(key), "right": right.get(key)}
        return {"kind": "changed" if fields else "same", "fields": fields}

    # ------------------------------------------------------------------
    # Branches and sandbox mode
    # ------------------------------------------------------------------

    def create_branch(
        self,
        world_id: str,
        name: str,
        *,
        parent_branch_id: str | None = None,
        kind: str = "sandbox",
        canon_status: str = "what_if",
        description: str = "",
    ) -> dict[str, Any]:
        if kind not in BRANCH_KINDS:
            raise ValueError("Unsupported branch kind")
        if canon_status not in CANON_STATUSES:
            raise ValueError("Unsupported canon status")
        name = name.strip()
        if not name:
            raise ValueError("Branch name cannot be blank")
        now = utc_now()
        branch_id = make_id("BRANCH")
        with self._lock, self._connection() as con:
            if con.execute("SELECT 1 FROM worlds WHERE id=?", (world_id,)).fetchone() is None:
                raise KeyError(world_id)
            slug = self._unique_slug(
                con, "world_branches", slugify(name), scope_column="world_id", scope_value=world_id
            )
            con.execute(
                "INSERT INTO world_branches(id,world_id,parent_branch_id,name,slug,description,kind,"
                "canon_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (branch_id, world_id, parent_branch_id, name, slug, description.strip(), kind, canon_status, now, now),
            )
        return self.get_branch(branch_id)

    def create_sandbox(self, world_id: str, *, name: str = "Sandbox") -> dict[str, Any]:
        main = next((b for b in self.list_branches(world_id) if b["kind"] == "main"), None)
        return self.create_branch(
            world_id, name, parent_branch_id=main["id"] if main else None,
            kind="sandbox", canon_status="what_if",
            description="Temporary what-if branch. Changes do not affect canon until promoted.",
        )

    def list_branches(self, world_id: str) -> list[dict[str, Any]]:
        with self._connection() as con:
            rows = con.execute(
                "SELECT * FROM world_branches WHERE world_id=? "
                "ORDER BY CASE kind WHEN 'main' THEN 0 WHEN 'sandbox' THEN 1 ELSE 2 END, created_at ASC",
                (world_id,),
            ).fetchall()
        return [self._branch_row(row) for row in rows]

    def get_branch(self, branch_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT * FROM world_branches WHERE id=?", (branch_id,)).fetchone()
        if row is None:
            raise KeyError(branch_id)
        result = self._branch_row(row)
        result["lineage"] = self.branch_lineage(branch_id)
        return result

    def update_branch(self, branch_id: str, **changes: Any) -> dict[str, Any]:
        fields: list[str] = []
        params: list[Any] = []
        for key in ("name", "description", "kind", "canon_status"):
            if key in changes and changes[key] is not None:
                value = str(changes[key]).strip()
                if key == "kind" and value not in BRANCH_KINDS:
                    raise ValueError("Unsupported branch kind")
                if key == "canon_status" and value not in CANON_STATUSES:
                    raise ValueError("Unsupported canon status")
                fields.append(f"{key}=?")
                params.append(value)
        if fields:
            fields.append("updated_at=?")
            params.extend([utc_now(), branch_id])
            with self._lock, self._connection() as con:
                cur = con.execute(
                    f"UPDATE world_branches SET {', '.join(fields)} WHERE id=?", params
                )
                if cur.rowcount == 0:
                    raise KeyError(branch_id)
        return self.get_branch(branch_id)

    def branch_lineage(self, branch_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        current = branch_id
        with self._connection() as con:
            while current and current not in seen:
                seen.add(current)
                row = con.execute("SELECT * FROM world_branches WHERE id=?", (current,)).fetchone()
                if row is None:
                    break
                result.append(self._branch_row(row))
                current = row["parent_branch_id"]
        result.reverse()
        return result

    # ------------------------------------------------------------------
    # Folders and documents
    # ------------------------------------------------------------------

    def delete_branch(self, branch_id: str) -> None:
        with self._lock, self._connection() as con:
            row = con.execute(
                "SELECT id,world_id,kind FROM world_branches WHERE id=?", (branch_id,)
            ).fetchone()
            if row is None:
                raise KeyError(branch_id)
            if row["kind"] == "main":
                raise ValueError("The main branch cannot be deleted. Delete the world instead.")

            variants = [r["id"] for r in con.execute(
                "SELECT id FROM entity_variants WHERE branch_id=?", (branch_id,)
            ).fetchall()]
            relationships = [r["id"] for r in con.execute(
                "SELECT id FROM relationships WHERE branch_id=?", (branch_id,)
            ).fetchall()]
            facts = [r["id"] for r in con.execute(
                "SELECT id FROM canon_facts WHERE branch_id=?", (branch_id,)
            ).fetchall()]

            # Chat/world branches are semantic state; Project documents/folders
            # are independent work files. Keep the files and simply detach the
            # deleted branch scope.
            now = utc_now()
            con.execute(
                "UPDATE workspace_documents SET branch_id=NULL,updated_at=? WHERE branch_id=?",
                (now, branch_id),
            )
            con.execute(
                "UPDATE workspace_folders SET branch_id=NULL,updated_at=? WHERE branch_id=?",
                (now, branch_id),
            )

            self._purge_resource_collection_tx(con, "relationship", relationships)
            self._purge_resource_collection_tx(con, "entity_variant", variants)
            self._purge_resource_refs_tx(con, "branch", branch_id)
            for fact_id in facts:
                self._purge_resource_refs_tx(con, "fact", fact_id, purge_owned_facts=False)

            con.execute("DELETE FROM world_branches WHERE id=?", (branch_id,))

    @staticmethod
    def _branch_storage_id(branch: dict[str, Any]) -> str | None:
        """Main is stored as NULL; alternate/sandbox branches use their ID."""
        return None if branch.get("kind") == "main" else branch.get("id")

    def compare_branches(self, left_branch_id: str, right_branch_id: str) -> dict[str, Any]:
        """Compare the *effective* state of two branches in the same world.

        Main state is represented by NULL branch rows. A non-main branch inherits
        main rows and replaces them with branch-specific variants/relationships.
        The returned change keys are stable enough for the Studio selective-merge UI.
        """
        left = self.get_branch(left_branch_id)
        right = self.get_branch(right_branch_id)
        if left["world_id"] != right["world_id"]:
            raise ValueError("Branch comparison requires branches from the same world")
        world_id = left["world_id"]
        left_sid = self._branch_storage_id(left)
        right_sid = self._branch_storage_id(right)

        def effective_variants(storage_id: str | None) -> dict[str, dict[str, Any]]:
            rows = self.list_variants(world_id=world_id, branch_id=storage_id)
            result: dict[str, dict[str, Any]] = {}
            # list_variants returns base and branch-specific rows; base first is not
            # guaranteed, so explicitly prefer the requested branch row.
            for item in rows:
                if item.get("branch_id") is None:
                    result[item["family_id"]] = item
            if storage_id:
                for item in rows:
                    if item.get("branch_id") == storage_id:
                        result[item["family_id"]] = item
            return result

        lmap = effective_variants(left_sid)
        rmap = effective_variants(right_sid)
        families = {item["id"]: item for item in self.list_entity_families(None)}
        entities: list[dict[str, Any]] = []
        for family_id in sorted(set(lmap) | set(rmap), key=lambda fid: (families.get(fid, {}).get("name") or fid).lower()):
            lv = lmap.get(family_id)
            rv = rmap.get(family_id)
            diff = self._variant_diff(lv, rv)
            if diff.get("kind") == "same":
                continue
            entities.append({
                "change_key": f"entity:{family_id}",
                "kind": "entity",
                "family_id": family_id,
                "name": families.get(family_id, {}).get("name") or (lv or rv or {}).get("display_name") or family_id,
                "entity_type": families.get(family_id, {}).get("entity_type") or (lv or rv or {}).get("entity_type"),
                "left": lv, "right": rv, "difference": diff,
            })

        def effective_relationships(storage_id: str | None) -> dict[tuple[str, str, str], dict[str, Any]]:
            with self._connection() as con:
                if storage_id:
                    rows = con.execute(
                        "SELECT r.*,sv.family_id AS subject_family_id,ov.family_id AS object_family_id,"
                        "sv.display_name AS subject_name,ov.display_name AS object_name "
                        "FROM relationships r JOIN entity_variants sv ON sv.id=r.subject_variant_id "
                        "JOIN entity_variants ov ON ov.id=r.object_variant_id "
                        "WHERE r.world_id=? AND (r.branch_id IS NULL OR r.branch_id=?) "
                        "ORDER BY r.branch_id IS NULL DESC,r.updated_at",
                        (world_id, storage_id),
                    ).fetchall()
                else:
                    rows = con.execute(
                        "SELECT r.*,sv.family_id AS subject_family_id,ov.family_id AS object_family_id,"
                        "sv.display_name AS subject_name,ov.display_name AS object_name "
                        "FROM relationships r JOIN entity_variants sv ON sv.id=r.subject_variant_id "
                        "JOIN entity_variants ov ON ov.id=r.object_variant_id "
                        "WHERE r.world_id=? AND r.branch_id IS NULL ORDER BY r.updated_at",
                        (world_id,),
                    ).fetchall()
            out: dict[tuple[str, str, str], dict[str, Any]] = {}
            for row in rows:
                key = (row["subject_family_id"], row["relation_type"], row["object_family_id"])
                item = self._relationship_row(row)
                item.update({
                    "subject_family_id": row["subject_family_id"],
                    "object_family_id": row["object_family_id"],
                    "subject_name": row["subject_name"], "object_name": row["object_name"],
                })
                out[key] = item
            return out

        lrels, rrels = effective_relationships(left_sid), effective_relationships(right_sid)
        relationships: list[dict[str, Any]] = []
        for key in sorted(set(lrels) | set(rrels), key=lambda x: (x[0], x[1], x[2])):
            lr, rr = lrels.get(key), rrels.get(key)
            fields: dict[str, Any] = {}
            if lr is None or rr is None:
                change_kind = "right_only" if lr is None else "left_only"
            else:
                for field in ("status", "canon_status", "attributes"):
                    if lr.get(field) != rr.get(field):
                        fields[field] = {"left": lr.get(field), "right": rr.get(field)}
                change_kind = "changed" if fields else "same"
            if change_kind == "same":
                continue
            relationships.append({
                "change_key": "relationship:" + "|".join(key),
                "kind": "relationship",
                "subject_family_id": key[0], "relation_type": key[1], "object_family_id": key[2],
                "left": lr, "right": rr,
                "difference": {"kind": change_kind, "fields": fields},
            })

        def direct_facts(storage_id: str | None) -> list[dict[str, Any]]:
            with self._connection() as con:
                rows = con.execute(
                    "SELECT * FROM canon_facts WHERE world_id=? AND branch_id IS ? "
                    "AND status NOT IN ('retconned','deprecated') ORDER BY owner_type,owner_id,path,updated_at",
                    (world_id, storage_id),
                ).fetchall()
            output = []
            for row in rows:
                item = dict(row); item["value"] = _loads(item.pop("value_json"), None)
                item["change_key"] = f"fact:{item['id']}"
                output.append(item)
            return output

        return {
            "world": self.get_world(world_id), "left": left, "right": right,
            "entities": entities, "relationships": relationships,
            "facts": {"left": direct_facts(left_sid), "right": direct_facts(right_sid)},
            "summary": {
                "entities_changed": len(entities),
                "relationships_changed": len(relationships),
                "left_direct_facts": len(direct_facts(left_sid)),
                "right_direct_facts": len(direct_facts(right_sid)),
            },
        }

    def merge_branch_changes(
        self, source_branch_id: str, target_branch_id: str,
        changes: list[dict[str, Any]], *, note: str = "selective branch merge",
    ) -> dict[str, Any]:
        """Selectively copy entity, relationship, and fact changes between branches.

        This deliberately merges semantic state rather than transcript text. Existing
        target facts with a different value are preserved and produce a normal canon
        conflict, so a merge never silently destroys provenance.
        """
        source = self.get_branch(source_branch_id)
        target = self.get_branch(target_branch_id)
        if source["world_id"] != target["world_id"]:
            raise ValueError("Branch merge requires branches from the same world")
        world_id = source["world_id"]
        source_sid = self._branch_storage_id(source)
        target_sid = self._branch_storage_id(target)
        allowed_fields = {"summary", "canon_status", "attributes", "voice", "knowledge", "beliefs", "current_state"}
        merged: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        def exact_variant(family_id: str, storage_id: str | None) -> dict[str, Any] | None:
            candidates = self.list_variants(family_id=family_id, world_id=world_id)
            return next((v for v in candidates if (v.get("branch_id") or None) == storage_id), None)

        def ensure_target_variant(family_id: str, source_variant: dict[str, Any]) -> dict[str, Any]:
            current = exact_variant(family_id, target_sid)
            if current:
                return current
            return self.create_variant(
                family_id, world_id, branch_id=target_sid, display_name=source_variant.get("display_name"),
                summary=source_variant.get("summary", ""), canon_status=source_variant.get("canon_status", "draft"),
                attributes=source_variant.get("attributes", {}), voice=source_variant.get("voice", {}),
                knowledge=source_variant.get("knowledge", {}), beliefs=source_variant.get("beliefs", {}),
                current_state=source_variant.get("current_state", {}),
            )

        for change in changes:
            kind = str(change.get("kind") or "").strip()
            if kind == "entity":
                family_id = str(change.get("family_id") or "")
                src = self.resolve_variant(family_id, world_id, source_sid)
                if not src:
                    skipped.append({"change": change, "reason": "source variant missing"}); continue
                dst = ensure_target_variant(family_id, src)
                fields = [f for f in (change.get("fields") or allowed_fields) if f in allowed_fields]
                values = {field: src.get(field) for field in fields}
                dst = self.update_variant(dst["id"], note=note, **values) if values else dst
                merged.append({"kind": kind, "family_id": family_id, "target_id": dst["id"], "fields": fields})
                continue

            if kind == "relationship":
                rel_id = change.get("relationship_id")
                src_rel = self.get_relationship(rel_id) if rel_id else None
                if src_rel is None:
                    # Accept compare rows without leaking source IDs into UI assumptions.
                    subject_family_id = change.get("subject_family_id")
                    object_family_id = change.get("object_family_id")
                    relation_type = change.get("relation_type")
                    candidates = self.list_relationships(world_id=world_id, branch_id=source_sid)
                    for candidate in candidates:
                        sv = self.get_variant(candidate["subject_variant_id"]); ov = self.get_variant(candidate["object_variant_id"])
                        if sv["family_id"] == subject_family_id and ov["family_id"] == object_family_id and candidate["relation_type"] == relation_type:
                            if (candidate.get("branch_id") or None) == source_sid or src_rel is None:
                                src_rel = candidate
                if not src_rel:
                    skipped.append({"change": change, "reason": "source relationship missing"}); continue
                src_sv = self.get_variant(src_rel["subject_variant_id"]); src_ov = self.get_variant(src_rel["object_variant_id"])
                target_sv = self.resolve_variant(src_sv["family_id"], world_id, target_sid)
                target_ov = self.resolve_variant(src_ov["family_id"], world_id, target_sid)
                if not target_sv or not target_ov:
                    skipped.append({"change": change, "reason": "target entity variant missing"}); continue
                exact = [r for r in self.list_relationships(world_id=world_id, branch_id=target_sid)
                         if (r.get("branch_id") or None) == target_sid and r["subject_variant_id"] == target_sv["id"]
                         and r["object_variant_id"] == target_ov["id"] and r["relation_type"] == src_rel["relation_type"]]
                if exact:
                    dst_rel = self.update_relationship(exact[0]["id"], status=src_rel["status"], canon_status=src_rel["canon_status"], attributes=src_rel["attributes"], note=note)
                else:
                    dst_rel = self.create_relationship(world_id, target_sv["id"], target_ov["id"], src_rel["relation_type"], branch_id=target_sid, status=src_rel["status"], canon_status=src_rel["canon_status"], attributes=src_rel["attributes"])
                merged.append({"kind": kind, "source_id": src_rel["id"], "target_id": dst_rel["id"]})
                continue

            if kind == "fact":
                fact_id = str(change.get("fact_id") or "")
                try:
                    fact = self.get_fact(fact_id)
                except KeyError:
                    skipped.append({"change": change, "reason": "source fact missing"}); continue
                if (fact.get("branch_id") or None) != source_sid or fact.get("world_id") != world_id:
                    skipped.append({"change": change, "reason": "fact is outside source branch"}); continue
                owner_type, owner_id = fact["owner_type"], fact["owner_id"]
                if owner_type == "entity_variant":
                    src_owner = self.get_variant(owner_id)
                    target_owner = self.resolve_variant(src_owner["family_id"], world_id, target_sid)
                    if not target_owner:
                        skipped.append({"change": change, "reason": "target fact owner missing"}); continue
                    owner_id = target_owner["id"]
                elif owner_type == "world":
                    owner_id = world_id
                elif owner_type not in {"entity_family", "project"}:
                    skipped.append({"change": change, "reason": f"fact owner {owner_type} needs manual merge"}); continue
                new_fact = self.add_fact(
                    WORLD_BIBLE_PROJECT_ID, owner_type, owner_id, fact["path"], fact["value"],
                    world_id=world_id, branch_id=target_sid, status=fact["status"],
                    authority="branch_merge", source_type="branch_merge", source_id=fact_id,
                )
                merged.append({"kind": kind, "source_id": fact_id, "target_id": new_fact["id"], "conflicts_created": new_fact.get("conflicts_created", 0)})
                continue

            skipped.append({"change": change, "reason": "unsupported merge kind"})

        return {"source": source, "target": target, "merged": merged, "skipped": skipped}

    def create_folder(
        self,
        project_id: str,
        name: str,
        *,
        world_id: str | None = None,
        branch_id: str | None = None,
        parent_id: str | None = None,
        kind: str = "mixed",
    ) -> dict[str, Any]:
        folder_id = make_id("FOLDER")
        now = utc_now()
        name = name.strip()
        if not name:
            raise ValueError("Folder name cannot be blank")
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT INTO workspace_folders(id,project_id,world_id,branch_id,parent_id,name,kind,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (folder_id, project_id, None, None, parent_id, name, kind, now, now),
            )
        return self.get_folder(folder_id)

    def get_folder(self, folder_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT * FROM workspace_folders WHERE id=?", (folder_id,)).fetchone()
        if row is None:
            raise KeyError(folder_id)
        return dict(row)

    def list_folders(
        self, project_id: str, *, world_id: str | None = None, branch_id: str | None = None
    ) -> list[dict[str, Any]]:
        where = ["project_id=?"]
        params: list[Any] = [project_id]
        if world_id is not None:
            where.append("(world_id IS NULL OR world_id=?)")
            params.append(world_id)
        if branch_id is not None:
            where.append("(branch_id IS NULL OR branch_id=?)")
            params.append(branch_id)
        with self._connection() as con:
            rows = con.execute(
                f"SELECT * FROM workspace_folders WHERE {' AND '.join(where)} "
                "ORDER BY sort_order ASC, name COLLATE NOCASE ASC",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def folder_tree(self, project_id: str, *, world_id: str | None = None, branch_id: str | None = None) -> list[dict[str, Any]]:
        rows = self.list_folders(project_id, world_id=world_id, branch_id=branch_id)
        by_parent: dict[str | None, list[dict[str, Any]]] = {}
        for row in rows:
            by_parent.setdefault(row.get("parent_id"), []).append(row)
        def build(parent: str | None):
            return [
                {**row, "children": build(row["id"])}
                for row in by_parent.get(parent, [])
            ]
        return build(None)

    def update_folder(self, folder_id: str, **changes: Any) -> dict[str, Any]:
        fields: list[str] = []
        params: list[Any] = []
        for key in ("name", "parent_id", "world_id", "branch_id", "kind", "sort_order"):
            if key in changes:
                fields.append(f"{key}=?")
                params.append(changes[key])
        if fields:
            fields.append("updated_at=?")
            params.extend([utc_now(), folder_id])
            with self._lock, self._connection() as con:
                cur = con.execute(
                    f"UPDATE workspace_folders SET {', '.join(fields)} WHERE id=?", params
                )
                if cur.rowcount == 0:
                    raise KeyError(folder_id)
        return self.get_folder(folder_id)

    def delete_folder(self, folder_id: str) -> list[str]:
        with self._lock, self._connection() as con:
            descendants = [folder_id]
            pending = [folder_id]
            while pending:
                child_rows = con.execute(
                    f"SELECT id FROM workspace_folders WHERE parent_id IN ({','.join('?' for _ in pending)})",
                    pending,
                ).fetchall()
                pending = [row["id"] for row in child_rows]
                descendants.extend(pending)
            placeholders = ",".join("?" for _ in descendants)
            con.execute(
                f"UPDATE entity_families SET folder_id=NULL WHERE folder_id IN ({placeholders})",
                descendants,
            )
            cur = con.execute("DELETE FROM workspace_folders WHERE id=?", (folder_id,))
            if cur.rowcount == 0:
                raise KeyError(folder_id)
            return descendants

    def create_document(
        self,
        project_id: str,
        title: str,
        *,
        document_type: str = "scene",
        content: str = "",
        world_id: str | None = None,
        branch_id: str | None = None,
        folder_id: str | None = None,
        status: str = "planned",
    ) -> dict[str, Any]:
        # v1.0 called generic prose documents `draft`; v1.1 treats Drafting as
        # workflow state and Scene as the generic manuscript object.
        if document_type == "draft":
            document_type = "scene"
        status = {"draft": "writing", "provisional": "revising", "canon": "final"}.get(status, status)
        if document_type not in DOCUMENT_TYPES:
            raise ValueError("Unsupported document type")
        document_id = make_id("DOC")
        now = utc_now()
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT INTO workspace_documents(id,project_id,world_id,branch_id,folder_id,document_type,title,"
                "content,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    document_id, project_id, world_id, branch_id, folder_id,
                    document_type, title.strip() or "Untitled", content, status, now, now,
                ),
            )
            self._add_revision_tx(con, "document", document_id, self._document_payload(con, document_id), "created")
        return self.get_document(document_id)

    def _document_payload(self, con: sqlite3.Connection, document_id: str) -> dict[str, Any]:
        row = con.execute("SELECT * FROM workspace_documents WHERE id=?", (document_id,)).fetchone()
        if row is None:
            raise KeyError(document_id)
        return self._document_row(row)

    def get_document(self, document_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT * FROM workspace_documents WHERE id=?", (document_id,)).fetchone()
        if row is None:
            raise KeyError(document_id)
        result = self._document_row(row)
        result["tags"] = self.tags_for("document", document_id)
        return result

    def list_documents(
        self,
        project_id: str,
        *,
        world_id: str | None = None,
        branch_id: str | None = None,
        folder_id: str | None = None,
        document_type: str | None = None,
    ) -> list[dict[str, Any]]:
        where = ["project_id=?"]
        params: list[Any] = [project_id]
        for key, value in (("world_id", world_id), ("branch_id", branch_id), ("folder_id", folder_id), ("document_type", document_type)):
            if value is not None:
                where.append(f"{key}=?")
                params.append(value)
        with self._connection() as con:
            rows = con.execute(
                f"SELECT * FROM workspace_documents WHERE {' AND '.join(where)} "
                "ORDER BY sort_order ASC, updated_at DESC",
                params,
            ).fetchall()
        return [self._document_row(row) for row in rows]

    def update_document(self, document_id: str, *, note: str = "updated", **changes: Any) -> dict[str, Any]:
        allowed = {"title", "content", "status", "folder_id", "world_id", "branch_id", "sort_order"}
        fields: list[str] = []
        params: list[Any] = []
        for key, value in changes.items():
            if key in allowed and value is not None:
                if key == "status":
                    value = {"draft": "writing", "provisional": "revising", "canon": "final"}.get(value, value)
                fields.append(f"{key}=?")
                params.append(value)
        with self._lock, self._connection() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                if fields:
                    fields.append("updated_at=?")
                    params.extend([utc_now(), document_id])
                    cur = con.execute(
                        f"UPDATE workspace_documents SET {', '.join(fields)} WHERE id=?", params
                    )
                    if cur.rowcount == 0:
                        raise KeyError(document_id)
                # Autosave snapshots are recovery state, not meaningful revisions.
                # This keeps the History panel readable while explicit checkpoints,
                # canon changes and restores still create durable revisions.
                if not str(note or "").lower().startswith("autosave"):
                    self._add_revision_tx(con, "document", document_id, self._document_payload(con, document_id), note)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        return self.get_document(document_id)

    def delete_document(self, document_id: str) -> None:
        with self._lock, self._connection() as con:
            exists = con.execute(
                "SELECT id FROM workspace_documents WHERE id=?", (document_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(document_id)
            self._purge_resource_refs_tx(con, "document", document_id)
            con.execute("DELETE FROM workspace_documents WHERE id=?", (document_id,))

    # ------------------------------------------------------------------
    # Entity families, world variants, relationship sheets
    # ------------------------------------------------------------------

    def create_entity_family(
        self,
        project_id: str | None,
        name: str,
        *,
        entity_type: str = "character",
        description: str = "",
        shared_core: dict[str, Any] | None = None,
        folder_id: str | None = None,
        create_variant_in_world: str | None = None,
        branch_id: str | None = None,
    ) -> dict[str, Any]:
        if entity_type not in ENTITY_TYPES:
            raise ValueError("Unsupported entity type")
        family_id = make_id("FAM")
        now = utc_now()
        name = name.strip()
        if not name:
            raise ValueError("Entity name cannot be blank")
        # Sheets belong to the Library, not to a story project. The
        # project_id argument is retained for v1 API compatibility but is
        # intentionally ignored for new sheets.
        owner_project_id = WORLD_BIBLE_PROJECT_ID
        # Library folders are organizational only; they do not make a sheet
        # project-owned.  v1.1 keeps the global ownership boundary while allowing
        # a family to live in the Bible folder tree.
        if folder_id:
            with self._connection() as check_con:
                folder = check_con.execute("SELECT project_id FROM workspace_folders WHERE id=?", (folder_id,)).fetchone()
            if folder is None or folder["project_id"] != WORLD_BIBLE_PROJECT_ID:
                raise ValueError("Library entity folders must belong to the Library")
        with self._lock, self._connection() as con:
            slug = self._unique_slug(
                con, "entity_families", slugify(name),
                scope_column="project_id", scope_value=owner_project_id,
                extra_scope=("entity_type", entity_type),
            )
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute(
                    "INSERT INTO entity_families(id,project_id,folder_id,entity_type,name,slug,description,shared_core_json,"
                    "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        family_id, owner_project_id, folder_id, entity_type, name, slug,
                        description.strip(), _dumps(shared_core or {}), now, now,
                    ),
                )
                if create_variant_in_world:
                    self._create_variant_tx(
                        con,
                        family_id=family_id,
                        world_id=create_variant_in_world,
                        branch_id=branch_id,
                        display_name=name,
                        summary=description,
                        canon_status="draft",
                        inherit_from_variant_id=None,
                        attributes={}, voice={}, knowledge={}, beliefs={}, current_state={},
                    )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        return self.get_entity_family(family_id)

    def list_entity_families(
        self, project_id: str | None = None, *, entity_type: str | None = None, search: str = ""
    ) -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []
        if project_id:
            where.append("project_id=?")
            params.append(project_id)
        if entity_type:
            where.append("entity_type=?")
            params.append(entity_type)
        if search.strip():
            where.append("(name LIKE ? COLLATE NOCASE OR description LIKE ? COLLATE NOCASE)")
            like = f"%{search.strip()}%"
            params.extend([like, like])
        with self._connection() as con:
            rows = con.execute(
                f"SELECT * FROM entity_families WHERE {' AND '.join(where)} ORDER BY name COLLATE NOCASE",
                params,
            ).fetchall()
        return [self._family_row(row) for row in rows]

    def get_entity_family(self, family_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT * FROM entity_families WHERE id=?", (family_id,)).fetchone()
        if row is None:
            raise KeyError(family_id)
        result = self._family_row(row)
        result["variants"] = self.list_variants(family_id=family_id)
        result["tags"] = self.tags_for("entity_family", family_id)
        return result

    def update_entity_family(self, family_id: str, *, note: str = "updated", **changes: Any) -> dict[str, Any]:
        before = self.get_entity_family(family_id)
        fields: list[str] = []
        params: list[Any] = []
        for key in ("name", "description", "folder_id"):
            if key in changes and changes[key] is not None:
                fields.append(f"{key}=?")
                value = str(changes[key]).strip()
                params.append((value or None) if key == "folder_id" else value)
        if "shared_core" in changes and changes["shared_core"] is not None:
            fields.append("shared_core_json=?")
            params.append(_dumps(changes["shared_core"]))
        with self._lock, self._connection() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                if fields:
                    fields.append("updated_at=?")
                    params.extend([utc_now(), family_id])
                    cur = con.execute(
                        f"UPDATE entity_families SET {', '.join(fields)} WHERE id=?", params
                    )
                    if cur.rowcount == 0:
                        raise KeyError(family_id)
                row = con.execute("SELECT * FROM entity_families WHERE id=?", (family_id,)).fetchone()
                self._add_revision_tx(con, "entity_family", family_id, self._family_row(row), note)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        result = self.get_entity_family(family_id)
        emit_domain_event(
            self.path,
            "workspace.entity_family_updated",
            {
                "before": before,
                "after": result,
                "changes": dict(changes),
                "note": note,
            },
        )
        return result

    def preview_entity_family_merge(self, source_family_id: str, target_family_id: str) -> dict[str, Any]:
        if source_family_id == target_family_id:
            raise ValueError("Source and target identity must be different")
        source = self.get_entity_family(source_family_id)
        target = self.get_entity_family(target_family_id)
        if source["entity_type"] != target["entity_type"]:
            raise ValueError("Only entity families of the same type can be merged")
        source_scopes = {(v["world_id"], v.get("branch_id")): v for v in source.get("variants", [])}
        target_scopes = {(v["world_id"], v.get("branch_id")): v for v in target.get("variants", [])}
        collisions = []
        for scope, left in source_scopes.items():
            right = target_scopes.get(scope)
            if right:
                collisions.append({"world_id": scope[0], "branch_id": scope[1], "source_variant_id": left["id"], "target_variant_id": right["id"]})
        return {
            "source": source,
            "target": target,
            "collisions": collisions,
            "safe": not collisions,
            "moved_variants": len(source_scopes),
        }

    def merge_entity_families(self, source_family_id: str, target_family_id: str) -> dict[str, Any]:
        preview = self.preview_entity_family_merge(source_family_id, target_family_id)
        if preview["collisions"]:
            raise ValueError("Automatic merge blocked: both identities have a variant in the same world/branch. Compare those variants explicitly before merging.")
        source, target = preview["source"], preview["target"]
        now = utc_now()
        with self._lock, self._connection() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                source_core = dict(source.get("shared_core") or {})
                target_core = dict(target.get("shared_core") or {})
                merged_core = {**source_core, **target_core}
                description = target.get("description") or source.get("description") or ""
                con.execute("UPDATE entity_families SET description=?,shared_core_json=?,updated_at=? WHERE id=?", (description, _dumps(merged_core), now, target_family_id))
                con.execute("UPDATE entity_variants SET family_id=?,updated_at=? WHERE family_id=?", (target_family_id, now, source_family_id))

                # Polymorphic references that can be retargeted without semantic arbitration.
                for table, type_col, id_col in (
                    ("canon_facts", "owner_type", "owner_id"),
                    ("project_overlays", "owner_type", "owner_id"),
                    ("staged_changes", "owner_type", "owner_id"),
                    ("timeline_events", "owner_type", "owner_id"),
                    ("workspace_conflicts", "owner_type", "owner_id"),
                ):
                    con.execute(f"UPDATE {table} SET {id_col}=? WHERE {type_col}='entity_family' AND {id_col}=?", (target_family_id, source_family_id))
                con.execute("UPDATE scene_dependencies SET target_id=? WHERE target_type='entity_family' AND target_id=?", (target_family_id, source_family_id))

                # Many-to-many references: copy, then discard the source link.
                con.execute("INSERT OR IGNORE INTO workspace_tag_links(tag_id,resource_type,resource_id) SELECT tag_id,'entity_family',? FROM workspace_tag_links WHERE resource_type='entity_family' AND resource_id=?", (target_family_id, source_family_id))
                con.execute("DELETE FROM workspace_tag_links WHERE resource_type='entity_family' AND resource_id=?", (source_family_id,))
                con.execute("INSERT OR IGNORE INTO context_pins(id,project_id,world_id,branch_id,resource_type,resource_id,scope,priority,created_at) SELECT id||'-MERGED',project_id,world_id,branch_id,'entity_family',?,scope,priority,created_at FROM context_pins WHERE resource_type='entity_family' AND resource_id=?", (target_family_id, source_family_id))
                con.execute("DELETE FROM context_pins WHERE resource_type='entity_family' AND resource_id=?", (source_family_id,))

                manifest_rows = con.execute("SELECT project_id,label,priority,created_at FROM project_manifest_refs WHERE resource_type='entity_family' AND resource_id=?", (source_family_id,)).fetchall()
                for row in manifest_rows:
                    existing = con.execute("SELECT priority FROM project_manifest_refs WHERE project_id=? AND resource_type='entity_family' AND resource_id=?", (row["project_id"], target_family_id)).fetchone()
                    if existing:
                        con.execute("UPDATE project_manifest_refs SET priority=? WHERE project_id=? AND resource_type='entity_family' AND resource_id=?", (max(int(existing["priority"]), int(row["priority"])), row["project_id"], target_family_id))
                    else:
                        con.execute("INSERT INTO project_manifest_refs(project_id,resource_type,resource_id,label,priority,created_at) VALUES(?, 'entity_family', ?, ?, ?, ?)", (row["project_id"], target_family_id, target["name"], row["priority"], row["created_at"]))
                con.execute("DELETE FROM project_manifest_refs WHERE resource_type='entity_family' AND resource_id=?", (source_family_id,))

                self._purge_resource_refs_tx(con, "entity_family", source_family_id, purge_owned_facts=False)
                con.execute("DELETE FROM entity_families WHERE id=?", (source_family_id,))
                row = con.execute("SELECT * FROM entity_families WHERE id=?", (target_family_id,)).fetchone()
                self._add_revision_tx(con, "entity_family", target_family_id, self._family_row(row), f"merged identity {source.get('name')}")
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        result = self.get_entity_family(target_family_id)
        result["merged_from"] = {"id": source_family_id, "name": source.get("name")}
        return result

    def _create_variant_tx(
        self,
        con: sqlite3.Connection,
        *,
        family_id: str,
        world_id: str,
        branch_id: str | None,
        display_name: str,
        summary: str,
        canon_status: str,
        inherit_from_variant_id: str | None,
        attributes: dict[str, Any],
        voice: dict[str, Any],
        knowledge: dict[str, Any],
        beliefs: dict[str, Any],
        current_state: dict[str, Any],
    ) -> str:
        variant_id = make_id("VAR")
        now = utc_now()
        con.execute(
            """
            INSERT INTO entity_variants(
                id,family_id,world_id,branch_id,inherit_from_variant_id,display_name,summary,
                canon_status,attributes_json,voice_json,knowledge_json,beliefs_json,current_state_json,
                created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                variant_id, family_id, world_id, branch_id, inherit_from_variant_id,
                display_name.strip(), summary.strip(), canon_status,
                _dumps(attributes), _dumps(voice), _dumps(knowledge), _dumps(beliefs),
                _dumps(current_state), now, now,
            ),
        )
        return variant_id

    def delete_entity_family(self, family_id: str) -> None:
        with self._lock, self._connection() as con:
            exists = con.execute(
                "SELECT id FROM entity_families WHERE id=?", (family_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(family_id)
            variants = [r["id"] for r in con.execute(
                "SELECT id FROM entity_variants WHERE family_id=?", (family_id,)
            ).fetchall()]
            relationships: list[str] = []
            if variants:
                placeholders = ",".join("?" for _ in variants)
                relationships = [r["id"] for r in con.execute(
                    f"SELECT id FROM relationships WHERE subject_variant_id IN ({placeholders}) OR object_variant_id IN ({placeholders})",
                    variants + variants,
                ).fetchall()]
            self._purge_resource_collection_tx(con, "relationship", relationships)
            self._purge_resource_collection_tx(con, "entity_variant", variants)
            self._purge_resource_refs_tx(con, "entity_family", family_id)
            con.execute("DELETE FROM entity_families WHERE id=?", (family_id,))

    def create_variant(
        self,
        family_id: str,
        world_id: str,
        *,
        branch_id: str | None = None,
        display_name: str | None = None,
        summary: str = "",
        canon_status: str = "draft",
        inherit_from_variant_id: str | None = None,
        inherit_sections: Iterable[str] | None = None,
        attributes: dict[str, Any] | None = None,
        voice: dict[str, Any] | None = None,
        knowledge: dict[str, Any] | None = None,
        beliefs: dict[str, Any] | None = None,
        current_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        family = self.get_entity_family(family_id)
        inherited: dict[str, Any] = {}
        if inherit_from_variant_id:
            parent = self.get_variant(inherit_from_variant_id)
            sections = set(inherit_sections or {"attributes", "voice"})
            for section in ("attributes", "voice", "knowledge", "beliefs", "current_state"):
                if section in sections:
                    inherited[section] = dict(parent.get(section) or {})
        values = {
            "attributes": {**inherited.get("attributes", {}), **(attributes or {})},
            "voice": {**inherited.get("voice", {}), **(voice or {})},
            "knowledge": {**inherited.get("knowledge", {}), **(knowledge or {})},
            "beliefs": {**inherited.get("beliefs", {}), **(beliefs or {})},
            "current_state": {**inherited.get("current_state", {}), **(current_state or {})},
        }
        with self._lock, self._connection() as con:
            variant_id = self._create_variant_tx(
                con,
                family_id=family_id, world_id=world_id, branch_id=branch_id,
                display_name=display_name or family["name"], summary=summary,
                canon_status=canon_status, inherit_from_variant_id=inherit_from_variant_id,
                **values,
            )
            row = con.execute("SELECT * FROM entity_variants WHERE id=?", (variant_id,)).fetchone()
            self._add_revision_tx(con, "entity_variant", variant_id, self._variant_row(row), "created")
        return self.get_variant(variant_id)

    def list_variants(
        self,
        *,
        family_id: str | None = None,
        world_id: str | None = None,
        branch_id: str | None = None,
        project_id: str | None = None,
        entity_type: str | None = None,
    ) -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []
        if family_id:
            where.append("v.family_id=?")
            params.append(family_id)
        if world_id:
            where.append("v.world_id=?")
            params.append(world_id)
        if branch_id is not None:
            where.append("(v.branch_id IS NULL OR v.branch_id=?)")
            params.append(branch_id)
        if project_id:
            # Library entities are global. Project filtering remains compatible
            # with legacy project-owned families while always exposing the shared Bible.
            where.append("(f.project_id=? OR f.project_id=?)")
            params.extend([project_id, WORLD_BIBLE_PROJECT_ID])
        if entity_type:
            where.append("f.entity_type=?")
            params.append(entity_type)
        with self._connection() as con:
            rows = con.execute(
                "SELECT v.*,f.name AS family_name,f.entity_type,f.shared_core_json "
                "FROM entity_variants v JOIN entity_families f ON f.id=v.family_id "
                f"WHERE {' AND '.join(where)} ORDER BY f.name COLLATE NOCASE, v.branch_id IS NULL DESC",
                params,
            ).fetchall()
        results = []
        for row in rows:
            item = self._variant_row(row)
            item["family_name"] = row["family_name"]
            item["entity_type"] = row["entity_type"]
            item["shared_core"] = _loads(row["shared_core_json"], {})
            results.append(item)
        return results

    def resolve_variant(self, family_id: str, world_id: str, branch_id: str | None = None) -> dict[str, Any] | None:
        variants = self.list_variants(family_id=family_id, world_id=world_id, branch_id=branch_id)
        if branch_id:
            branch_specific = next((v for v in variants if v["branch_id"] == branch_id), None)
            if branch_specific:
                return branch_specific
        return next((v for v in variants if v["branch_id"] is None), None)

    def get_variant(self, variant_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute(
                "SELECT v.*,f.name AS family_name,f.entity_type,f.shared_core_json,f.project_id "
                "FROM entity_variants v JOIN entity_families f ON f.id=v.family_id WHERE v.id=?",
                (variant_id,),
            ).fetchone()
        if row is None:
            raise KeyError(variant_id)
        result = self._variant_row(row)
        result.update({
            "family_name": row["family_name"], "entity_type": row["entity_type"],
            "shared_core": _loads(row["shared_core_json"], {}), "project_id": row["project_id"],
        })
        result["facts"] = self.list_facts(owner_type="entity_variant", owner_id=variant_id)
        result["relationships"] = self.list_relationships(
            world_id=result["world_id"], branch_id=result["branch_id"], variant_id=variant_id
        )
        result["tags"] = self.tags_for("entity_variant", variant_id)
        result["revisions"] = self.list_revisions("entity_variant", variant_id)
        return result

    def update_variant(self, variant_id: str, *, note: str = "updated", **changes: Any) -> dict[str, Any]:
        before = self.get_variant(variant_id)
        fields: list[str] = []
        params: list[Any] = []
        for key in ("display_name", "summary", "canon_status"):
            if key in changes and changes[key] is not None:
                value = str(changes[key]).strip()
                if key == "canon_status" and value not in CANON_STATUSES:
                    raise ValueError("Unsupported canon status")
                fields.append(f"{key}=?")
                params.append(value)
        mapping = {
            "attributes": "attributes_json", "voice": "voice_json",
            "knowledge": "knowledge_json", "beliefs": "beliefs_json",
            "current_state": "current_state_json",
        }
        for key, column in mapping.items():
            if key in changes and changes[key] is not None:
                fields.append(f"{column}=?")
                params.append(_dumps(changes[key]))
        with self._lock, self._connection() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                if fields:
                    fields.append("updated_at=?")
                    params.extend([utc_now(), variant_id])
                    cur = con.execute(
                        f"UPDATE entity_variants SET {', '.join(fields)} WHERE id=?", params
                    )
                    if cur.rowcount == 0:
                        raise KeyError(variant_id)
                row = con.execute("SELECT * FROM entity_variants WHERE id=?", (variant_id,)).fetchone()
                self._add_revision_tx(con, "entity_variant", variant_id, self._variant_row(row), note)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        result = self.get_variant(variant_id)
        emit_domain_event(
            self.path,
            "workspace.variant_updated",
            {
                "before": before,
                "after": result,
                "changes": dict(changes),
                "note": note,
            },
        )
        return result

    def delete_variant(self, variant_id: str) -> None:
        with self._lock, self._connection() as con:
            exists = con.execute(
                "SELECT id FROM entity_variants WHERE id=?", (variant_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(variant_id)
            relationships = [r["id"] for r in con.execute(
                "SELECT id FROM relationships WHERE subject_variant_id=? OR object_variant_id=?",
                (variant_id, variant_id),
            ).fetchall()]
            self._purge_resource_collection_tx(con, "relationship", relationships)
            self._purge_resource_refs_tx(con, "entity_variant", variant_id)
            con.execute("DELETE FROM entity_variants WHERE id=?", (variant_id,))

    def compare_variants(self, left_variant_id: str, right_variant_id: str) -> dict[str, Any]:
        left = self.get_variant(left_variant_id)
        right = self.get_variant(right_variant_id)
        if left["family_id"] != right["family_id"]:
            raise ValueError("Variant comparison requires the same entity family")
        return {"left": left, "right": right, "difference": self._variant_diff(left, right)}

    def create_relationship(
        self,
        world_id: str,
        subject_variant_id: str,
        object_variant_id: str,
        relation_type: str,
        *,
        branch_id: str | None = None,
        status: str = "current",
        canon_status: str = "draft",
        attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        relationship_id = make_id("REL")
        now = utc_now()
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT INTO relationships(id,world_id,branch_id,subject_variant_id,object_variant_id,"
                "relation_type,status,canon_status,attributes_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    relationship_id, world_id, branch_id, subject_variant_id,
                    object_variant_id, relation_type.strip(), status, canon_status,
                    _dumps(attributes or {}), now, now,
                ),
            )
            row = con.execute("SELECT * FROM relationships WHERE id=?", (relationship_id,)).fetchone()
            self._add_revision_tx(con, "relationship", relationship_id, self._relationship_row(row), "created")
        return self.get_relationship(relationship_id)

    def list_relationships(
        self,
        *,
        world_id: str,
        branch_id: str | None = None,
        variant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        where = ["r.world_id=?", "(r.branch_id IS NULL" + (" OR r.branch_id=?" if branch_id else "") + ")"]
        params: list[Any] = [world_id]
        if branch_id:
            params.append(branch_id)
        if variant_id:
            where.append("(r.subject_variant_id=? OR r.object_variant_id=?)")
            params.extend([variant_id, variant_id])
        with self._connection() as con:
            rows = con.execute(
                "SELECT r.*,sv.display_name AS subject_name,ov.display_name AS object_name "
                "FROM relationships r "
                "JOIN entity_variants sv ON sv.id=r.subject_variant_id "
                "JOIN entity_variants ov ON ov.id=r.object_variant_id "
                f"WHERE {' AND '.join(where)} ORDER BY r.updated_at DESC",
                params,
            ).fetchall()
        output = []
        for row in rows:
            item = self._relationship_row(row)
            item["subject_name"] = row["subject_name"]
            item["object_name"] = row["object_name"]
            output.append(item)
        return output

    def get_relationship(self, relationship_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute(
                "SELECT r.*,sv.display_name AS subject_name,ov.display_name AS object_name "
                "FROM relationships r JOIN entity_variants sv ON sv.id=r.subject_variant_id "
                "JOIN entity_variants ov ON ov.id=r.object_variant_id WHERE r.id=?",
                (relationship_id,),
            ).fetchone()
        if row is None:
            raise KeyError(relationship_id)
        result = self._relationship_row(row)
        result["subject_name"] = row["subject_name"]
        result["object_name"] = row["object_name"]
        result["facts"] = self.list_facts(owner_type="relationship", owner_id=relationship_id)
        result["tags"] = self.tags_for("relationship", relationship_id)
        result["revisions"] = self.list_revisions("relationship", relationship_id)
        return result

    def update_relationship(self, relationship_id: str, *, note: str = "updated", **changes: Any) -> dict[str, Any]:
        fields: list[str] = []
        params: list[Any] = []
        for key in ("relation_type", "status", "canon_status"):
            if key in changes and changes[key] is not None:
                fields.append(f"{key}=?")
                params.append(str(changes[key]).strip())
        if "attributes" in changes and changes["attributes"] is not None:
            fields.append("attributes_json=?")
            params.append(_dumps(changes["attributes"]))
        with self._lock, self._connection() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                if fields:
                    fields.append("updated_at=?")
                    params.extend([utc_now(), relationship_id])
                    cur = con.execute(
                        f"UPDATE relationships SET {', '.join(fields)} WHERE id=?", params
                    )
                    if cur.rowcount == 0:
                        raise KeyError(relationship_id)
                row = con.execute("SELECT * FROM relationships WHERE id=?", (relationship_id,)).fetchone()
                self._add_revision_tx(con, "relationship", relationship_id, self._relationship_row(row), note)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        return self.get_relationship(relationship_id)

    # ------------------------------------------------------------------
    # Templates, scene dependencies, and conflict resolution
    # ------------------------------------------------------------------

    def delete_relationship(self, relationship_id: str) -> None:
        with self._lock, self._connection() as con:
            exists = con.execute(
                "SELECT id FROM relationships WHERE id=?", (relationship_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(relationship_id)
            self._purge_resource_refs_tx(con, "relationship", relationship_id)
            con.execute("DELETE FROM relationships WHERE id=?", (relationship_id,))

    def create_template(
        self,
        name: str,
        entity_type: str,
        template: dict[str, Any],
        *,
        project_id: str | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        if entity_type not in ENTITY_TYPES:
            raise ValueError("Unsupported entity type")
        template_id = make_id("TPL")
        now = utc_now()
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT INTO entity_templates(id,project_id,name,entity_type,description,template_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (template_id, project_id, name.strip(), entity_type, description.strip(), _dumps(template), now, now),
            )
        return self.get_template(template_id)

    def get_template(self, template_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT * FROM entity_templates WHERE id=?", (template_id,)).fetchone()
        if row is None:
            raise KeyError(template_id)
        item = dict(row)
        item["template"] = _loads(item.pop("template_json"), {})
        return item

    def list_templates(self, *, project_id: str | None = None, entity_type: str | None = None) -> list[dict[str, Any]]:
        where = ["(project_id IS NULL" + (" OR project_id=?" if project_id else "") + ")"]
        params: list[Any] = [project_id] if project_id else []
        if entity_type:
            where.append("entity_type=?")
            params.append(entity_type)
        with self._connection() as con:
            rows = con.execute(
                f"SELECT * FROM entity_templates WHERE {' AND '.join(where)} ORDER BY project_id IS NULL DESC,name COLLATE NOCASE",
                params,
            ).fetchall()
        output=[]
        for row in rows:
            item=dict(row); item["template"]=_loads(item.pop("template_json"),{}); output.append(item)
        return output

    def delete_template(self, template_id: str) -> None:
        with self._lock, self._connection() as con:
            row = con.execute(
                "SELECT id,project_id FROM entity_templates WHERE id=?", (template_id,)
            ).fetchone()
            if row is None:
                raise KeyError(template_id)
            if row["project_id"] is None:
                raise ValueError("Built-in templates cannot be deleted")
            self._purge_resource_refs_tx(con, "template", template_id)
            con.execute("DELETE FROM entity_templates WHERE id=?", (template_id,))

    def create_scene_dependency(
        self,
        project_id: str,
        scene_document_id: str,
        requirement_type: str,
        target_type: str,
        target_id: str,
        *,
        world_id: str | None = None,
        branch_id: str | None = None,
        condition: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dependency_id=make_id("DEP")
        now=utc_now()
        with self._lock,self._connection() as con:
            con.execute(
                "INSERT INTO scene_dependencies(id,project_id,world_id,branch_id,scene_document_id,requirement_type,target_type,target_id,condition_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (dependency_id,project_id,world_id,branch_id,scene_document_id,requirement_type,target_type,target_id,_dumps(condition or {}),now),
            )
        return self.get_scene_dependency(dependency_id)

    def get_scene_dependency(self, dependency_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row=con.execute("SELECT * FROM scene_dependencies WHERE id=?",(dependency_id,)).fetchone()
        if row is None: raise KeyError(dependency_id)
        item=dict(row); item["condition"]=_loads(item.pop("condition_json"),{}); return item

    def list_scene_dependencies(self, scene_document_id: str) -> list[dict[str, Any]]:
        with self._connection() as con:
            rows=con.execute("SELECT * FROM scene_dependencies WHERE scene_document_id=? ORDER BY created_at",(scene_document_id,)).fetchall()
        output=[]
        for row in rows:
            item=dict(row); item["condition"]=_loads(item.pop("condition_json"),{}); output.append(item)
        return output

    def delete_scene_dependency(self, dependency_id: str) -> None:
        with self._lock,self._connection() as con:
            cur=con.execute("DELETE FROM scene_dependencies WHERE id=?",(dependency_id,))
            if cur.rowcount==0: raise KeyError(dependency_id)

    def validate_scene_dependencies(self, scene_document_id: str) -> dict[str, Any]:
        dependencies=self.list_scene_dependencies(scene_document_id)
        results=[]
        with self._connection() as con:
            for dep in dependencies:
                target_type=dep["target_type"]; target_id=dep["target_id"]
                satisfied=False; detail="unsupported requirement"
                if target_type=="document":
                    row=con.execute("SELECT status,title FROM workspace_documents WHERE id=?",(target_id,)).fetchone()
                    satisfied=bool(row and (dep["requirement_type"]!="completed" or row["status"] in {"canon","complete","completed"}))
                    detail=row["title"] if row else "document missing"
                elif target_type=="entity_variant":
                    row=con.execute("SELECT display_name FROM entity_variants WHERE id=?",(target_id,)).fetchone(); satisfied=bool(row); detail=row["display_name"] if row else "entity missing"
                elif target_type=="relationship":
                    row=con.execute("SELECT relation_type FROM relationships WHERE id=?",(target_id,)).fetchone(); satisfied=bool(row); detail=row["relation_type"] if row else "relationship missing"
                elif target_type=="fact":
                    row=con.execute("SELECT path FROM canon_facts WHERE id=?",(target_id,)).fetchone(); satisfied=bool(row); detail=row["path"] if row else "fact missing"
                results.append({**dep,"satisfied":satisfied,"detail":detail})
        return {"scene_document_id":scene_document_id,"valid":all(x["satisfied"] for x in results),"dependencies":results}

    def create_conflict(
        self,
        project_id: str,
        owner_type: str,
        owner_id: str,
        path: str,
        left: Any,
        right: Any,
        *,
        world_id: str | None = None,
        branch_id: str | None = None,
        conflict_class: str = "hard_contradiction",
    ) -> dict[str, Any]:
        conflict_id=make_id("CONFLICT"); now=utc_now()
        with self._lock,self._connection() as con:
            con.execute(
                "INSERT INTO workspace_conflicts(id,project_id,world_id,branch_id,owner_type,owner_id,path,left_json,right_json,conflict_class,status,resolution_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (conflict_id,project_id,world_id,branch_id,owner_type,owner_id,path,_dumps(left),_dumps(right),conflict_class,"open","{}",now,now),
            )
        return self.get_conflict(conflict_id)

    def get_conflict(self, conflict_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row=con.execute("SELECT * FROM workspace_conflicts WHERE id=?",(conflict_id,)).fetchone()
        if row is None: raise KeyError(conflict_id)
        item=dict(row); item["left"]=_loads(item.pop("left_json"),None); item["right"]=_loads(item.pop("right_json"),None); item["resolution"]=_loads(item.pop("resolution_json"),{}); return item

    def list_conflicts(self, *, project_id: str, world_id: str | None = None, branch_id: str | None = None, status: str | None = "open") -> list[dict[str, Any]]:
        where=["project_id=?"]; params: list[Any] = [project_id]
        if world_id is not None: where.append("world_id=?"); params.append(world_id)
        if branch_id is not None: where.append("(branch_id IS NULL OR branch_id=?)"); params.append(branch_id)
        if status is not None: where.append("status=?"); params.append(status)
        with self._connection() as con:
            rows=con.execute(f"SELECT id FROM workspace_conflicts WHERE {' AND '.join(where)} ORDER BY updated_at DESC",params).fetchall()
        return [self.get_conflict(row["id"]) for row in rows]

    def resolve_conflict(self, conflict_id: str, resolution_type: str, *, chosen_value: Any = None, note: str = "") -> dict[str, Any]:
        conflict=self.get_conflict(conflict_id)
        allowed={"temporal_transition","world_variant","retcon_left","retcon_right","keep_unresolved","mark_source_wrong"}
        if resolution_type not in allowed: raise ValueError("Unsupported conflict resolution")
        status="open" if resolution_type=="keep_unresolved" else "resolved"
        resolution={"type":resolution_type,"chosen_value":chosen_value,"note":note,"resolved_at":utc_now()}
        with self._lock,self._connection() as con:
            con.execute("UPDATE workspace_conflicts SET status=?,resolution_json=?,updated_at=? WHERE id=?",(status,_dumps(resolution),utc_now(),conflict_id))
        return self.get_conflict(conflict_id)

    # ------------------------------------------------------------------
    # Tags, canon facts, context pins, revisions
    # ------------------------------------------------------------------

    def create_tag(
        self, project_id: str, name: str, *, color: str = "#6b7280", kind: str = "organizational"
    ) -> dict[str, Any]:
        tag_id = make_id("TAG")
        now = utc_now()
        with self._lock, self._connection() as con:
            slug = self._unique_slug(
                con, "workspace_tags", slugify(name), scope_column="project_id", scope_value=project_id
            )
            con.execute(
                "INSERT INTO workspace_tags(id,project_id,name,slug,color,kind,created_at) VALUES(?,?,?,?,?,?,?)",
                (tag_id, project_id, name.strip(), slug, color, kind, now),
            )
        return self.get_tag(tag_id)

    def get_tag(self, tag_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT * FROM workspace_tags WHERE id=?", (tag_id,)).fetchone()
        if row is None:
            raise KeyError(tag_id)
        return dict(row)

    def list_tags(self, project_id: str) -> list[dict[str, Any]]:
        with self._connection() as con:
            rows = con.execute(
                "SELECT * FROM workspace_tags WHERE project_id=? ORDER BY name COLLATE NOCASE",
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_tag(self, tag_id: str) -> None:
        with self._lock, self._connection() as con:
            cur = con.execute("DELETE FROM workspace_tags WHERE id=?", (tag_id,))
            if cur.rowcount == 0:
                raise KeyError(tag_id)

    def tag_resource(self, tag_id: str, resource_type: str, resource_id: str) -> None:
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT OR IGNORE INTO workspace_tag_links(tag_id,resource_type,resource_id) VALUES(?,?,?)",
                (tag_id, resource_type, resource_id),
            )

    def untag_resource(self, tag_id: str, resource_type: str, resource_id: str) -> None:
        with self._lock, self._connection() as con:
            con.execute(
                "DELETE FROM workspace_tag_links WHERE tag_id=? AND resource_type=? AND resource_id=?",
                (tag_id, resource_type, resource_id),
            )

    def tags_for(self, resource_type: str, resource_id: str) -> list[dict[str, Any]]:
        with self._connection() as con:
            rows = con.execute(
                "SELECT t.* FROM workspace_tags t JOIN workspace_tag_links l ON l.tag_id=t.id "
                "WHERE l.resource_type=? AND l.resource_id=? ORDER BY t.name COLLATE NOCASE",
                (resource_type, resource_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_fact(
        self,
        project_id: str,
        owner_type: str,
        owner_id: str,
        path: str,
        value: Any,
        *,
        world_id: str | None = None,
        branch_id: str | None = None,
        status: str = "draft",
        authority: str = "user_explicit",
        source_type: str = "manual",
        source_id: str | None = None,
    ) -> dict[str, Any]:
        if status not in CANON_STATUSES:
            raise ValueError("Unsupported canon status")
        fact_id = make_id("FACT")
        now = utc_now()
        conflicting: list[tuple[str, Any]] = []
        with self._lock, self._connection() as con:
            existing = con.execute(
                "SELECT id,value_json FROM canon_facts WHERE project_id=? AND owner_type=? AND owner_id=? AND path=? "
                "AND world_id IS ? AND branch_id IS ? AND status NOT IN ('retconned','deprecated')",
                (project_id, owner_type, owner_id, path.strip(), world_id, branch_id),
            ).fetchall()
            conflicting = [(row["id"], _loads(row["value_json"], None)) for row in existing if _loads(row["value_json"], None) != value]
            con.execute(
                "INSERT INTO canon_facts(id,project_id,world_id,branch_id,owner_type,owner_id,path,value_json,"
                "status,authority,source_type,source_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    fact_id, project_id, world_id, branch_id, owner_type, owner_id,
                    path.strip(), _dumps(value), status, authority, source_type, source_id, now, now,
                ),
            )
            for old_id, old_value in conflicting:
                conflict_id=make_id("CONFLICT")
                con.execute(
                    "INSERT INTO workspace_conflicts(id,project_id,world_id,branch_id,owner_type,owner_id,path,left_json,right_json,conflict_class,status,resolution_json,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (conflict_id,project_id,world_id,branch_id,owner_type,owner_id,path.strip(),_dumps({"fact_id":old_id,"value":old_value}),_dumps({"fact_id":fact_id,"value":value}),"same_scope_value_conflict","open","{}",now,now),
                )
        result=self.get_fact(fact_id)
        result["conflicts_created"]=len(conflicting)
        return result

    def get_fact(self, fact_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT * FROM canon_facts WHERE id=?", (fact_id,)).fetchone()
        if row is None:
            raise KeyError(fact_id)
        result = dict(row)
        result["value"] = _loads(result.pop("value_json"), None)
        return result

    def list_facts(
        self,
        *,
        project_id: str | None = None,
        world_id: str | None = None,
        branch_id: str | None = None,
        owner_type: str | None = None,
        owner_id: str | None = None,
    ) -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []
        for key, value in (
            ("project_id", project_id), ("world_id", world_id), ("owner_type", owner_type), ("owner_id", owner_id)
        ):
            if value is not None:
                where.append(f"{key}=?")
                params.append(value)
        if branch_id is not None:
            where.append("(branch_id IS NULL OR branch_id=?)")
            params.append(branch_id)
        with self._connection() as con:
            rows = con.execute(
                f"SELECT * FROM canon_facts WHERE {' AND '.join(where)} ORDER BY path COLLATE NOCASE, updated_at DESC",
                params,
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["value"] = _loads(item.pop("value_json"), None)
            out.append(item)
        return out

    def delete_fact(self, fact_id: str) -> None:
        with self._lock, self._connection() as con:
            exists = con.execute("SELECT id FROM canon_facts WHERE id=?", (fact_id,)).fetchone()
            if exists is None:
                raise KeyError(fact_id)
            self._purge_resource_refs_tx(con, "fact", fact_id, purge_owned_facts=False)
            con.execute("DELETE FROM canon_facts WHERE id=?", (fact_id,))

    def promote_to_canon(
        self,
        *,
        project_id: str,
        world_id: str,
        branch_id: str | None,
        owner_type: str,
        owner_id: str,
        path: str,
        value: Any,
        source_turn_id: str | None = None,
    ) -> dict[str, Any]:
        return self.add_fact(
            project_id, owner_type, owner_id, path, value,
            world_id=world_id, branch_id=branch_id, status="canon",
            authority="user_promoted", source_type="accepted_generated_prose",
            source_id=source_turn_id,
        )

    def pin_context(
        self,
        project_id: str,
        resource_type: str,
        resource_id: str,
        *,
        world_id: str | None = None,
        branch_id: str | None = None,
        scope: str = "world",
        priority: int = 1,
    ) -> dict[str, Any]:
        pin_id = make_id("PIN")
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT OR REPLACE INTO context_pins(id,project_id,world_id,branch_id,resource_type,resource_id,"
                "scope,priority,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (pin_id, project_id, world_id, branch_id, resource_type, resource_id, scope, priority, utc_now()),
            )
        return {
            "id": pin_id, "project_id": project_id, "world_id": world_id,
            "branch_id": branch_id, "resource_type": resource_type,
            "resource_id": resource_id, "scope": scope, "priority": priority,
        }

    def list_pins(
        self, project_id: str, *, world_id: str | None = None, branch_id: str | None = None
    ) -> list[dict[str, Any]]:
        where = ["project_id=?"]
        params: list[Any] = [project_id]
        if world_id:
            where.append("(world_id IS NULL OR world_id=?)")
            params.append(world_id)
        if branch_id:
            where.append("(branch_id IS NULL OR branch_id=?)")
            params.append(branch_id)
        with self._connection() as con:
            rows = con.execute(
                f"SELECT * FROM context_pins WHERE {' AND '.join(where)} ORDER BY priority ASC, created_at ASC",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def unpin_context(self, pin_id: str) -> None:
        with self._lock, self._connection() as con:
            con.execute("DELETE FROM context_pins WHERE id=?", (pin_id,))

    def _add_revision_tx(
        self, con: sqlite3.Connection, resource_type: str, resource_id: str, content: Any, note: str
    ) -> str:
        version = con.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM workspace_revisions WHERE resource_type=? AND resource_id=?",
            (resource_type, resource_id),
        ).fetchone()[0]
        revision_id = make_id("REV")
        con.execute(
            "INSERT INTO workspace_revisions(id,resource_type,resource_id,version,content_json,note,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (revision_id, resource_type, resource_id, version, _dumps(content), note, utc_now()),
        )
        return revision_id

    def list_revisions(self, resource_type: str, resource_id: str) -> list[dict[str, Any]]:
        with self._connection() as con:
            rows = con.execute(
                "SELECT * FROM workspace_revisions WHERE resource_type=? AND resource_id=? ORDER BY version DESC",
                (resource_type, resource_id),
            ).fetchall()
        return [
            {
                "id": row["id"], "resource_type": row["resource_type"],
                "resource_id": row["resource_id"], "version": row["version"],
                "content": _loads(row["content_json"], {}), "note": row["note"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def get_revision(self, revision_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute(
                "SELECT * FROM workspace_revisions WHERE id=?", (revision_id,)
            ).fetchone()
        if row is None:
            raise KeyError(revision_id)
        return {
            "id": row["id"], "resource_type": row["resource_type"],
            "resource_id": row["resource_id"], "version": row["version"],
            "content": _loads(row["content_json"], {}), "note": row["note"],
            "created_at": row["created_at"],
        }

    def restore_revision(self, revision_id: str, *, note: str = "revision restored") -> dict[str, Any]:
        """Restore a resource non-destructively by creating a new revision."""
        revision = self.get_revision(revision_id)
        resource_type = revision["resource_type"]
        resource_id = revision["resource_id"]
        content = dict(revision.get("content") or {})
        restore_note = f"{note} from v{revision['version']}"
        if resource_type == "document":
            return self.update_document(
                resource_id, note=restore_note,
                title=content.get("title"), content=content.get("content"),
                status=content.get("status"), folder_id=content.get("folder_id"),
                world_id=content.get("world_id"), branch_id=content.get("branch_id"),
                sort_order=content.get("sort_order"),
            )
        if resource_type == "entity_variant":
            return self.update_variant(
                resource_id, note=restore_note,
                display_name=content.get("display_name"), summary=content.get("summary"),
                canon_status=content.get("canon_status"), attributes=content.get("attributes"),
                voice=content.get("voice"), knowledge=content.get("knowledge"),
                beliefs=content.get("beliefs"), current_state=content.get("current_state"),
            )
        if resource_type == "entity_family":
            return self.update_entity_family(
                resource_id, note=restore_note,
                name=content.get("name"), description=content.get("description"),
                shared_core=content.get("shared_core"),
            )
        if resource_type == "relationship":
            return self.update_relationship(
                resource_id, note=restore_note,
                relation_type=content.get("relation_type"), status=content.get("status"),
                canon_status=content.get("canon_status"), attributes=content.get("attributes"),
            )
        raise ValueError(f"Revision restore is not supported for {resource_type}")

    # ------------------------------------------------------------------
    # Snapshots, retcon impact, mention search
    # ------------------------------------------------------------------

    def create_snapshot(
        self,
        project_id: str,
        world_id: str,
        *,
        branch_id: str | None = None,
        name: str = "Snapshot",
        description: str = "",
    ) -> dict[str, Any]:
        payload = self._snapshot_payload(project_id, world_id, branch_id)
        snapshot_id = make_id("SNAP")
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT INTO world_snapshots(id,project_id,world_id,branch_id,name,description,payload_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (snapshot_id, project_id, world_id, branch_id, name.strip(), description.strip(), _dumps(payload), utc_now()),
            )
        return self.get_snapshot(snapshot_id)

    def _snapshot_payload(self, project_id: str, world_id: str, branch_id: str | None) -> dict[str, Any]:
        return {
            "schema": "arline-world-snapshot-0.1",
            "project": self.get_project(project_id),
            "world": self.get_world(world_id),
            "branch": self.get_branch(branch_id) if branch_id else None,
            "variants": self.list_variants(world_id=world_id, branch_id=branch_id),
            "relationships": self.list_relationships(world_id=world_id, branch_id=branch_id),
            "facts": self.list_facts(project_id=project_id, world_id=world_id, branch_id=branch_id),
            "documents": self.list_documents(project_id, world_id=world_id, branch_id=branch_id),
            "pins": self.list_pins(project_id, world_id=world_id, branch_id=branch_id),
        }

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT * FROM world_snapshots WHERE id=?", (snapshot_id,)).fetchone()
        if row is None:
            raise KeyError(snapshot_id)
        result = dict(row)
        result["payload"] = _loads(result.pop("payload_json"), {})
        return result

    def list_snapshots(self, world_id: str) -> list[dict[str, Any]]:
        with self._connection() as con:
            rows = con.execute(
                "SELECT id,project_id,world_id,branch_id,name,description,created_at "
                "FROM world_snapshots WHERE world_id=? ORDER BY created_at DESC",
                (world_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_snapshot(self, snapshot_id: str) -> None:
        with self._lock, self._connection() as con:
            cur = con.execute("DELETE FROM world_snapshots WHERE id=?", (snapshot_id,))
            if cur.rowcount == 0:
                raise KeyError(snapshot_id)

    def restore_snapshot(self, snapshot_id: str, *, branch_name: str | None = None) -> SnapshotResult:
        snap = self.get_snapshot(snapshot_id)
        payload = snap["payload"]
        world_id = snap["world_id"]
        branch = self.create_branch(
            world_id,
            branch_name or f"Restore · {snap['name']}",
            kind="sandbox",
            canon_status="what_if",
            description=f"Restored non-destructively from snapshot {snapshot_id}",
        )
        new_branch_id = branch["id"]
        variant_map: dict[str, str] = {}
        with self._lock, self._connection() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                for variant in payload.get("variants", []):
                    new_id = self._create_variant_tx(
                        con,
                        family_id=variant["family_id"], world_id=world_id,
                        branch_id=new_branch_id, display_name=variant["display_name"],
                        summary=variant.get("summary", ""), canon_status="what_if",
                        inherit_from_variant_id=variant.get("id"),
                        attributes=variant.get("attributes", {}), voice=variant.get("voice", {}),
                        knowledge=variant.get("knowledge", {}), beliefs=variant.get("beliefs", {}),
                        current_state=variant.get("current_state", {}),
                    )
                    variant_map[variant["id"]] = new_id
                for rel in payload.get("relationships", []):
                    sub = variant_map.get(rel["subject_variant_id"])
                    obj = variant_map.get(rel["object_variant_id"])
                    if sub and obj:
                        con.execute(
                            "INSERT INTO relationships(id,world_id,branch_id,subject_variant_id,object_variant_id,"
                            "relation_type,status,canon_status,attributes_json,created_at,updated_at) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                make_id("REL"), world_id, new_branch_id, sub, obj,
                                rel["relation_type"], rel.get("status", "current"), "what_if",
                                _dumps(rel.get("attributes", {})), utc_now(), utc_now(),
                            ),
                        )
                for fact in payload.get("facts", []):
                    owner_id = variant_map.get(fact["owner_id"], fact["owner_id"])
                    con.execute(
                        "INSERT INTO canon_facts(id,project_id,world_id,branch_id,owner_type,owner_id,path,value_json,"
                        "status,authority,source_type,source_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            make_id("FACT"), snap["project_id"], world_id, new_branch_id,
                            fact["owner_type"], owner_id, fact["path"], _dumps(fact.get("value")),
                            "what_if", fact.get("authority", "user_explicit"),
                            "snapshot_restore", snapshot_id, utc_now(), utc_now(),
                        ),
                    )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        return SnapshotResult(snapshot_id=snapshot_id, branch_id=new_branch_id, mode="new_sandbox_branch")

    def retcon_preview(
        self,
        *,
        project_id: str,
        world_id: str,
        owner_type: str,
        owner_id: str,
        path: str,
        new_value: Any,
    ) -> dict[str, Any]:
        facts = self.list_facts(owner_type=owner_type, owner_id=owner_id)
        current = [f for f in facts if f["path"] == path and f["status"] not in {"retconned", "deprecated"}]
        owner_label = owner_id
        if owner_type == "entity_variant":
            try:
                owner_label = self.get_variant(owner_id)["display_name"]
            except KeyError:
                pass
        with self._connection() as con:
            document_hits = con.execute(
                "SELECT id,title,document_type FROM workspace_documents WHERE project_id=? AND "
                "(content LIKE ? COLLATE NOCASE OR content LIKE ? COLLATE NOCASE)",
                (project_id, f"%{owner_label}%", f"%{path}%"),
            ).fetchall()
            turn_hits = []
            if self._table_exists(con, "turns"):
                turn_hits = con.execute(
                    "SELECT id,session_id,run_id FROM turns WHERE "
                    "story LIKE ? COLLATE NOCASE OR edited_story LIKE ? COLLATE NOCASE LIMIT 100",
                    (f"%{owner_label}%", f"%{owner_label}%"),
                ).fetchall()
        relationships = []
        if owner_type == "entity_variant":
            relationships = self.list_relationships(world_id=world_id, variant_id=owner_id)
        return {
            "owner": {"type": owner_type, "id": owner_id, "label": owner_label},
            "path": path,
            "current_facts": current,
            "new_value": new_value,
            "impact": {
                "relationships": relationships,
                "documents": [dict(row) for row in document_hits],
                "turns": [dict(row) for row in turn_hits],
                "dataset_samples_may_require_review": len(turn_hits),
            },
            "options": ["apply_retcon", "create_world_fork", "keep_unresolved"],
        }

    def apply_retcon(
        self,
        *,
        project_id: str,
        world_id: str,
        branch_id: str | None,
        owner_type: str,
        owner_id: str,
        path: str,
        new_value: Any,
        note: str = "",
    ) -> dict[str, Any]:
        now = utc_now()
        with self._lock, self._connection() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute(
                    "UPDATE canon_facts SET status='retconned',updated_at=? "
                    "WHERE owner_type=? AND owner_id=? AND path=? AND status NOT IN ('retconned','deprecated')",
                    (now, owner_type, owner_id, path),
                )
                fact_id = make_id("FACT")
                con.execute(
                    "INSERT INTO canon_facts(id,project_id,world_id,branch_id,owner_type,owner_id,path,value_json,"
                    "status,authority,source_type,source_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        fact_id, project_id, world_id, branch_id, owner_type, owner_id,
                        path, _dumps(new_value), "canon", "latest_user_correction",
                        "retcon", note or None, now, now,
                    ),
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        return self.get_fact(fact_id)

    def search_mentions(
        self,
        query: str,
        *,
        project_id: str | None = None,
        world_id: str | None = None,
        branch_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        q = query.strip()
        like = f"%{q}%"
        results: list[dict[str, Any]] = []
        with self._connection() as con:
            variant_rows = con.execute(
                "SELECT v.*,f.name AS family_name,f.entity_type,f.folder_id,w.name AS world_name "
                "FROM entity_variants v JOIN entity_families f ON f.id=v.family_id "
                "JOIN worlds w ON w.id=v.world_id WHERE "
                "(v.display_name LIKE ? COLLATE NOCASE OR f.name LIKE ? COLLATE NOCASE OR v.summary LIKE ? COLLATE NOCASE) "
                "ORDER BY CASE WHEN v.world_id=? THEN 0 ELSE 1 END, "
                "CASE WHEN v.branch_id=? THEN 0 WHEN v.branch_id IS NULL THEN 1 ELSE 2 END, f.name COLLATE NOCASE LIMIT ?",
                (like, like, like, world_id or "", branch_id or "", limit),
            ).fetchall()
            doc_rows = []
            if project_id:
                doc_rows = con.execute(
                    "SELECT d.*,w.name AS world_name FROM workspace_documents d LEFT JOIN worlds w ON w.id=d.world_id "
                    "WHERE d.project_id=? AND (d.title LIKE ? COLLATE NOCASE OR d.content LIKE ? COLLATE NOCASE) "
                    "ORDER BY CASE WHEN d.world_id=? THEN 0 ELSE 1 END,d.updated_at DESC LIMIT ?",
                    (project_id, like, like, world_id or "", limit),
                ).fetchall()
            rel_rows = con.execute(
                "SELECT r.*,sv.display_name AS subject_name,ov.display_name AS object_name,w.name AS world_name "
                "FROM relationships r JOIN entity_variants sv ON sv.id=r.subject_variant_id "
                "JOIN entity_variants ov ON ov.id=r.object_variant_id JOIN worlds w ON w.id=r.world_id "
                "WHERE (sv.display_name LIKE ? COLLATE NOCASE OR ov.display_name LIKE ? COLLATE NOCASE "
                "OR r.relation_type LIKE ? COLLATE NOCASE) ORDER BY CASE WHEN r.world_id=? THEN 0 ELSE 1 END LIMIT ?",
                (like, like, like, world_id or "", limit),
            ).fetchall()
            world_rows = con.execute(
                "SELECT * FROM worlds WHERE name LIKE ? COLLATE NOCASE OR description LIKE ? COLLATE NOCASE "
                "ORDER BY CASE WHEN id=? THEN 0 ELSE 1 END,name COLLATE NOCASE LIMIT ?",
                (like, like, world_id or "", limit),
            ).fetchall()
        for row in variant_rows:
            results.append({
                "type": "entity_variant", "id": row["id"], "family_id": row["family_id"],
                "label": row["display_name"], "subtitle": f"{row['entity_type']} · {row['world_name']}",
                "world_id": row["world_id"], "branch_id": row["branch_id"], "folder_id": row["folder_id"],
                "current_world": row["world_id"] == world_id,
            })
        for row in doc_rows:
            results.append({
                "type": "document", "id": row["id"], "label": row["title"],
                "subtitle": f"{row['document_type']} · {row['world_name'] or 'project'}",
                "world_id": row["world_id"], "branch_id": row["branch_id"], "folder_id": row["folder_id"],
                "current_world": row["world_id"] == world_id,
            })
        for row in rel_rows:
            results.append({
                "type": "relationship", "id": row["id"],
                "label": f"{row['subject_name']} ↔ {row['object_name']}",
                "subtitle": f"{row['relation_type']} · {row['world_name']}",
                "world_id": row["world_id"], "branch_id": row["branch_id"],
                "current_world": row["world_id"] == world_id,
            })
        for row in world_rows:
            results.append({
                "type": "world", "id": row["id"], "label": row["name"],
                "subtitle": f"world · {row['canon_status']}", "world_id": row["id"],
                "branch_id": None, "current_world": row["id"] == world_id,
            })
        results.sort(key=lambda item: (not item.get("current_world", False), item["label"].lower()))
        return results[:limit]

    def command_search(self, query: str, *, project_id: str | None = None) -> list[dict[str, Any]]:
        q = query.strip().lower()
        commands = [
            ("new_chat", "New chat", "Create a new writing chat"),
            ("new_project", "New project", "Create a story workspace"),
            ("new_world", "New world", "Create or fork a world"),
            ("new_character", "New character", "Create a character family/variant"),
            ("new_draft", "New manuscript item", "Create a scene, chapter, note, or research document"),
            ("sandbox", "Open sandbox", "Create a non-canonical what-if branch"),
            ("snapshot", "Save world snapshot", "Checkpoint current world state"),
            ("compare_worlds", "Compare worlds", "Open canon diff"),
            ("dataset", "Open Feedback Lab", "Review prose feedback, comparisons, and exports"),
            ("runtime", "Model runtime", "Open LM Studio controls"),
        ]
        out = [
            {"type": "command", "id": cid, "label": label, "subtitle": subtitle}
            for cid, label, subtitle in commands
            if not q or q in label.lower() or q in subtitle.lower()
        ]
        if q:
            out.extend(self.search_mentions(q, project_id=project_id, limit=12))
        return out[:30]

    # ------------------------------------------------------------------
    # v1.1 foundation: project manifest, overlays, scene cursor, staging,
    # timeline, recipes, backlinks, and continuity inspection.
    # ------------------------------------------------------------------

    def list_project_manifest_refs(self, project_id: str) -> list[dict[str, Any]]:
        with self._connection() as con:
            rows = con.execute(
                "SELECT * FROM project_manifest_refs WHERE project_id=? ORDER BY priority DESC,created_at ASC",
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_project_manifest_ref(
        self, project_id: str, resource_type: str, resource_id: str,
        *, label: str = "", priority: int = 1,
    ) -> dict[str, Any]:
        with self._lock, self._connection() as con:
            if con.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is None:
                raise KeyError(project_id)
            con.execute(
                "INSERT INTO project_manifest_refs(project_id,resource_type,resource_id,label,priority,created_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(project_id,resource_type,resource_id) DO UPDATE SET "
                "label=excluded.label,priority=excluded.priority",
                (project_id, resource_type, resource_id, label.strip(), int(priority), utc_now()),
            )
        return {
            "project_id": project_id, "resource_type": resource_type,
            "resource_id": resource_id, "label": label, "priority": int(priority),
        }

    def remove_project_manifest_ref(self, project_id: str, resource_type: str, resource_id: str) -> None:
        with self._lock, self._connection() as con:
            con.execute(
                "DELETE FROM project_manifest_refs WHERE project_id=? AND resource_type=? AND resource_id=?",
                (project_id, resource_type, resource_id),
            )

    def list_project_overlays(
        self, project_id: str, *, world_id: str | None = None,
        branch_id: str | None = None, owner_type: str | None = None,
        owner_id: str | None = None,
    ) -> list[dict[str, Any]]:
        where = ["project_id=?", "status='active'"]
        params: list[Any] = [project_id]
        for column, value in (("world_id", world_id), ("branch_id", branch_id), ("owner_type", owner_type), ("owner_id", owner_id)):
            if value is not None:
                if column == "branch_id" and value == "":
                    where.append("branch_id IS NULL")
                else:
                    where.append(f"{column}=?")
                    params.append(value)
        with self._connection() as con:
            rows = con.execute(
                f"SELECT * FROM project_overlays WHERE {' AND '.join(where)} ORDER BY updated_at DESC",
                params,
            ).fetchall()
        return [{**dict(row), "value": _loads(row["value_json"], None)} for row in rows]

    def upsert_project_overlay(
        self, project_id: str, *, owner_type: str, owner_id: str, path: str,
        value: Any, world_id: str | None = None, branch_id: str | None = None,
    ) -> dict[str, Any]:
        if not path.strip():
            raise ValueError("Overlay path cannot be blank")
        now = utc_now()
        with self._lock, self._connection() as con:
            row = con.execute(
                "SELECT id FROM project_overlays WHERE project_id=? AND world_id IS ? AND branch_id IS ? "
                "AND owner_type=? AND owner_id=? AND path=?",
                (project_id, world_id, branch_id, owner_type, owner_id, path.strip()),
            ).fetchone()
            overlay_id = row["id"] if row else make_id("OVERLAY")
            if row:
                con.execute(
                    "UPDATE project_overlays SET value_json=?,status='active',updated_at=? WHERE id=?",
                    (_dumps(value), now, overlay_id),
                )
            else:
                con.execute(
                    "INSERT INTO project_overlays(id,project_id,world_id,branch_id,owner_type,owner_id,path,value_json,status,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (overlay_id, project_id, world_id, branch_id, owner_type, owner_id, path.strip(), _dumps(value), "active", now, now),
                )
        return next(x for x in self.list_project_overlays(project_id, owner_type=owner_type, owner_id=owner_id) if x["id"] == overlay_id)

    def delete_project_overlay(self, overlay_id: str) -> None:
        with self._lock, self._connection() as con:
            cur = con.execute("DELETE FROM project_overlays WHERE id=?", (overlay_id,))
            if cur.rowcount == 0:
                raise KeyError(overlay_id)

    def get_scene_card(self, document_id: str) -> dict[str, Any] | None:
        with self._connection() as con:
            row = con.execute(
                "SELECT c.*,d.title,d.document_type,d.status AS document_status "
                "FROM project_scene_cards c JOIN workspace_documents d ON d.id=c.document_id WHERE c.document_id=?",
                (document_id,),
            ).fetchone()
        if row is None:
            return None
        return {**dict(row), "participants": _loads(row["participants_json"], [])}

    def list_scene_cards(self, project_id: str) -> list[dict[str, Any]]:
        with self._connection() as con:
            rows = con.execute(
                "SELECT c.document_id FROM project_scene_cards c JOIN workspace_documents d ON d.id=c.document_id "
                "WHERE c.project_id=? ORDER BY c.sort_order ASC,d.sort_order ASC,d.title COLLATE NOCASE",
                (project_id,),
            ).fetchall()
        return [card for row in rows if (card := self.get_scene_card(row["document_id"])) is not None]

    def set_scene_card(
        self, project_id: str, document_id: str, *, world_id: str | None = None,
        branch_id: str | None = None, pov_variant_id: str | None = None,
        location_variant_id: str | None = None, participants: list[str] | None = None,
        narrative_time: str = "", target_outcome: str = "", notes: str = "",
        status: str = "planned", sort_order: float = 0.0,
    ) -> dict[str, Any]:
        status = status.strip() or "planned"
        if status not in {"planned", "drafting", "complete", "skipped"}:
            raise ValueError("Unsupported scene-card status")
        now = utc_now()
        with self._lock, self._connection() as con:
            doc = con.execute("SELECT project_id FROM workspace_documents WHERE id=?", (document_id,)).fetchone()
            if doc is None:
                raise KeyError(document_id)
            if doc["project_id"] != project_id:
                raise ValueError("Scene document does not belong to this project")
            con.execute(
                "INSERT INTO project_scene_cards(document_id,project_id,world_id,branch_id,pov_variant_id,location_variant_id,participants_json,narrative_time,target_outcome,notes,status,sort_order,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET "
                "world_id=excluded.world_id,branch_id=excluded.branch_id,pov_variant_id=excluded.pov_variant_id,location_variant_id=excluded.location_variant_id,"
                "participants_json=excluded.participants_json,narrative_time=excluded.narrative_time,target_outcome=excluded.target_outcome,notes=excluded.notes,status=excluded.status,sort_order=excluded.sort_order,updated_at=excluded.updated_at",
                (document_id, project_id, world_id, branch_id, pov_variant_id, location_variant_id, _dumps(participants or []), narrative_time.strip(), target_outcome.strip(), notes.strip(), status, float(sort_order), now, now),
            )
        return self.get_scene_card(document_id) or {}

    def delete_scene_card(self, project_id: str, document_id: str) -> None:
        with self._lock, self._connection() as con:
            con.execute("DELETE FROM project_scene_cards WHERE project_id=? AND document_id=?", (project_id, document_id))

    def get_active_scene(self, project_id: str) -> dict[str, Any] | None:
        with self._connection() as con:
            row = con.execute("SELECT * FROM project_active_scenes WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            return None
        return {
            **dict(row),
            "participants": _loads(row["participants_json"], []),
        }

    def set_active_scene(
        self, project_id: str, *, document_id: str | None = None,
        world_id: str | None = None, branch_id: str | None = None,
        pov_variant_id: str | None = None, location_variant_id: str | None = None,
        participants: list[str] | None = None, narrative_time: str = "", notes: str = "",
    ) -> dict[str, Any]:
        now = utc_now()
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT INTO project_active_scenes(project_id,document_id,world_id,branch_id,pov_variant_id,location_variant_id,participants_json,narrative_time,notes,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET "
                "document_id=excluded.document_id,world_id=excluded.world_id,branch_id=excluded.branch_id,"
                "pov_variant_id=excluded.pov_variant_id,location_variant_id=excluded.location_variant_id,"
                "participants_json=excluded.participants_json,narrative_time=excluded.narrative_time,notes=excluded.notes,updated_at=excluded.updated_at",
                (project_id, document_id, world_id, branch_id, pov_variant_id, location_variant_id, _dumps(participants or []), narrative_time.strip(), notes.strip(), now),
            )
        return self.get_active_scene(project_id) or {}

    def stage_change(
        self, *, project_id: str, owner_type: str, owner_id: str, path: str,
        proposed_value: Any, old_value: Any = None, confidence: float = 0.5,
        world_id: str | None = None, branch_id: str | None = None,
        session_id: str | None = None, turn_id: str | None = None, source_text: str = "",
    ) -> dict[str, Any]:
        change_id = make_id("STAGE")
        now = utc_now()
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT INTO staged_changes(id,project_id,world_id,branch_id,session_id,turn_id,owner_type,owner_id,path,old_value_json,proposed_value_json,confidence,status,source_text,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (change_id, project_id, world_id, branch_id, session_id, turn_id, owner_type, owner_id, path.strip(), _dumps(old_value) if old_value is not None else None, _dumps(proposed_value), max(0.0, min(1.0, float(confidence))), "pending", source_text.strip(), now, now),
            )
        return self.get_staged_change(change_id)

    def get_staged_change(self, change_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT * FROM staged_changes WHERE id=?", (change_id,)).fetchone()
        if row is None:
            raise KeyError(change_id)
        return {
            **dict(row),
            "old_value": _loads(row["old_value_json"], None),
            "proposed_value": _loads(row["proposed_value_json"], None),
        }

    def list_staged_changes(
        self, project_id: str, *, status: str = "pending", world_id: str | None = None,
        branch_id: str | None = None,
    ) -> list[dict[str, Any]]:
        where = ["project_id=?"]
        params: list[Any] = [project_id]
        if status:
            where.append("status=?")
            params.append(status)
        if world_id:
            where.append("world_id=?")
            params.append(world_id)
        if branch_id:
            where.append("(branch_id IS NULL OR branch_id=?)")
            params.append(branch_id)
        with self._connection() as con:
            rows = con.execute(
                f"SELECT id FROM staged_changes WHERE {' AND '.join(where)} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [self.get_staged_change(row["id"]) for row in rows]

    def resolve_staged_change(self, change_id: str, *, accept: bool) -> dict[str, Any]:
        change = self.get_staged_change(change_id)
        status = "accepted" if accept else "rejected"
        if accept:
            # Accepted discoveries become explicit facts. They are not written
            # directly into opaque JSON blobs, preserving revision/audit data.
            self.add_fact(
                project_id=WORLD_BIBLE_PROJECT_ID,
                world_id=change.get("world_id"), branch_id=change.get("branch_id"),
                owner_type=change["owner_type"], owner_id=change["owner_id"],
                path=change["path"], value=change["proposed_value"], status="canon",
                authority="user_promoted", source_type="staged_change", source_id=change_id,
            )
        with self._lock, self._connection() as con:
            con.execute(
                "UPDATE staged_changes SET status=?,updated_at=? WHERE id=?",
                (status, utc_now(), change_id),
            )
        return self.get_staged_change(change_id)

    def add_timeline_event(
        self, *, world_id: str, summary: str, branch_id: str | None = None,
        owner_type: str | None = None, owner_id: str | None = None,
        time_label: str = "", order_key: float = 0.0, event_type: str = "event",
        state_patch: dict[str, Any] | None = None, source_type: str = "manual",
        source_id: str | None = None, status: str = "canon",
    ) -> dict[str, Any]:
        if not summary.strip():
            raise ValueError("Timeline summary cannot be blank")
        event_id = make_id("TIME")
        now = utc_now()
        with self._lock, self._connection() as con:
            con.execute(
                "INSERT INTO timeline_events(id,world_id,branch_id,owner_type,owner_id,time_label,order_key,event_type,summary,state_patch_json,source_type,source_id,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (event_id, world_id, branch_id, owner_type, owner_id, time_label.strip(), float(order_key), event_type.strip() or "event", summary.strip(), _dumps(state_patch or {}), source_type, source_id, status, now, now),
            )
        result=self.get_timeline_event(event_id)
        emit_domain_event(self.path,"workspace.timeline_event_created",{"event":result})
        return result

    def get_timeline_event(self, event_id: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT * FROM timeline_events WHERE id=?", (event_id,)).fetchone()
        if row is None:
            raise KeyError(event_id)
        return {**dict(row), "state_patch": _loads(row["state_patch_json"], {})}

    def list_timeline_events(
        self, world_id: str, *, branch_id: str | None = None,
        owner_type: str | None = None, owner_id: str | None = None,
    ) -> list[dict[str, Any]]:
        where = ["world_id=?"]
        params: list[Any] = [world_id]
        if branch_id:
            where.append("(branch_id IS NULL OR branch_id=?)")
            params.append(branch_id)
        if owner_type:
            where.append("owner_type=?")
            params.append(owner_type)
        if owner_id:
            where.append("owner_id=?")
            params.append(owner_id)
        with self._connection() as con:
            rows = con.execute(
                f"SELECT id FROM timeline_events WHERE {' AND '.join(where)} ORDER BY order_key ASC,created_at ASC",
                params,
            ).fetchall()
        return [self.get_timeline_event(row["id"]) for row in rows]

    def timeline_state(
        self, world_id: str, *, owner_type: str, owner_id: str,
        branch_id: str | None = None, at_order: float | None = None,
    ) -> dict[str, Any]:
        events = self.list_timeline_events(world_id, branch_id=branch_id, owner_type=owner_type, owner_id=owner_id)
        state: dict[str, Any] = {}
        applied: list[str] = []
        for event in events:
            if at_order is not None and float(event["order_key"]) > float(at_order):
                break
            for key, value in (event.get("state_patch") or {}).items():
                state[key] = value
            applied.append(event["id"])
        return {"state": state, "applied_events": applied, "at_order": at_order}

    def list_context_recipes(self, project_id: str | None = None) -> list[dict[str, Any]]:
        with self._connection() as con:
            if project_id:
                rows = con.execute(
                    "SELECT * FROM context_recipes WHERE project_id IS NULL OR project_id=? ORDER BY builtin DESC,name COLLATE NOCASE",
                    (project_id,),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM context_recipes WHERE project_id IS NULL ORDER BY name COLLATE NOCASE"
                ).fetchall()
        return [{**dict(row), "recipe": _loads(row["recipe_json"], {})} for row in rows]

    def save_context_recipe(
        self, project_id: str, name: str, *, description: str = "", recipe: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValueError("Recipe name cannot be blank")
        now = utc_now()
        with self._lock, self._connection() as con:
            row = con.execute(
                "SELECT id FROM context_recipes WHERE project_id=? AND name=?", (project_id, name)
            ).fetchone()
            recipe_id = row["id"] if row else make_id("RECIPE")
            if row:
                con.execute(
                    "UPDATE context_recipes SET description=?,recipe_json=?,updated_at=? WHERE id=?",
                    (description.strip(), _dumps(recipe or {}), now, recipe_id),
                )
            else:
                con.execute(
                    "INSERT INTO context_recipes(id,project_id,name,description,recipe_json,builtin,created_at,updated_at) VALUES(?,?,?,?,?,0,?,?)",
                    (recipe_id, project_id, name, description.strip(), _dumps(recipe or {}), now, now),
                )
        return next(x for x in self.list_context_recipes(project_id) if x["id"] == recipe_id)

    def backlinks(self, resource_type: str, resource_id: str) -> dict[str, Any]:
        links: list[dict[str, Any]] = []
        with self._connection() as con:
            for row in con.execute(
                "SELECT * FROM project_manifest_refs WHERE resource_type=? AND resource_id=?",
                (resource_type, resource_id),
            ).fetchall():
                links.append({"kind": "project_manifest", **dict(row)})
            for row in con.execute(
                "SELECT * FROM context_pins WHERE resource_type=? AND resource_id=?",
                (resource_type, resource_id),
            ).fetchall():
                links.append({"kind": "context_pin", **dict(row)})
            for row in con.execute(
                "SELECT * FROM canon_facts WHERE owner_type=? AND owner_id=? ORDER BY updated_at DESC LIMIT 100",
                (resource_type, resource_id),
            ).fetchall():
                links.append({"kind": "canon_fact", "id": row["id"], "path": row["path"], "status": row["status"], "world_id": row["world_id"]})
            for row in con.execute(
                "SELECT * FROM scene_dependencies WHERE target_type=? AND target_id=?",
                (resource_type, resource_id),
            ).fetchall():
                links.append({"kind": "scene_dependency", **dict(row)})
            for row in con.execute(
                "SELECT * FROM timeline_events WHERE owner_type=? AND owner_id=? ORDER BY order_key ASC",
                (resource_type, resource_id),
            ).fetchall():
                links.append({"kind": "timeline_event", "id": row["id"], "summary": row["summary"], "time_label": row["time_label"]})
            if resource_type == "entity_variant":
                for row in con.execute(
                    "SELECT id,relation_type,subject_variant_id,object_variant_id,world_id,branch_id FROM relationships WHERE subject_variant_id=? OR object_variant_id=?",
                    (resource_id, resource_id),
                ).fetchall():
                    links.append({"kind": "relationship", **dict(row)})
        return {"resource_type": resource_type, "resource_id": resource_id, "links": links, "count": len(links)}

    def continuity_report(
        self, project_id: str, *, world_id: str | None = None, branch_id: str | None = None,
    ) -> dict[str, Any]:
        warnings: list[dict[str, Any]] = []
        conflicts = self.list_conflicts(project_id=project_id, world_id=world_id, branch_id=branch_id, status="open")
        for conflict in conflicts:
            warnings.append({"severity": "error", "kind": "recorded_conflict", "message": f"Conflict on {conflict['path']}", "resource": conflict})

        # Multiple live facts for one owner/path with different values are a
        # deterministic continuity smell even when no conflict row exists.
        with self._connection() as con:
            where = ["status NOT IN ('retconned','deprecated')"]
            params: list[Any] = []
            if world_id:
                where.append("world_id=?")
                params.append(world_id)
            rows = con.execute(
                f"SELECT owner_type,owner_id,path,COUNT(DISTINCT value_json) AS variants,COUNT(*) AS n FROM canon_facts WHERE {' AND '.join(where)} GROUP BY owner_type,owner_id,path HAVING variants>1",
                params,
            ).fetchall()
        for row in rows:
            warnings.append({
                "severity": "warning", "kind": "competing_facts",
                "message": f"{row['owner_type']}:{row['owner_id']} has {row['variants']} live values for {row['path']}",
                "owner_type": row["owner_type"], "owner_id": row["owner_id"], "path": row["path"],
            })

        active_scene = self.get_active_scene(project_id)
        if active_scene and world_id and active_scene.get("world_id") and active_scene["world_id"] != world_id:
            warnings.append({"severity": "warning", "kind": "scene_scope_mismatch", "message": "Active scene points to a different world than the current scope."})
        staged = self.list_staged_changes(project_id, status="pending", world_id=world_id, branch_id=branch_id)
        return {
            "warnings": warnings,
            "warning_count": len(warnings),
            "active_scene": active_scene,
            "pending_changes": staged,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _table_exists(con: sqlite3.Connection, name: str) -> bool:
        return con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone() is not None

    def _unique_slug(
        self,
        con: sqlite3.Connection,
        table: str,
        base: str,
        *,
        scope_column: str | None = None,
        scope_value: Any = None,
        extra_scope: tuple[str, Any] | None = None,
    ) -> str:
        candidate = base
        index = 2
        while True:
            where = ["slug=?"]
            params: list[Any] = [candidate]
            if scope_column:
                where.append(f"{scope_column}=?")
                params.append(scope_value)
            if extra_scope:
                where.append(f"{extra_scope[0]}=?")
                params.append(extra_scope[1])
            row = con.execute(
                f"SELECT 1 FROM {table} WHERE {' AND '.join(where)}", params
            ).fetchone()
            if row is None:
                return candidate
            candidate = f"{base}-{index}"
            index += 1
