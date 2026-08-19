from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Missing expected block in {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_replace(path: str, pattern: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, new, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"Expected one regex match in {path}, got {count}")
    target.write_text(updated, encoding="utf-8")


# DiscoveryStore owns all Discovery/Continuity/Provisional tables.
replace(
    "src/discovery/store.py",
    'DISCOVERY_SCHEMA_VERSION = 2\nCONTINUITY_SCHEMA_VERSION = "1.2.2a1"\n',
    'DISCOVERY_SCHEMA_VERSION = 3\nCONTINUITY_SCHEMA_VERSION = "1.2.2a1"\nPROVISIONAL_SCHEMA_VERSION = 1\n',
)
replace(
    "src/discovery/store.py",
    '''                CREATE TABLE IF NOT EXISTS continuity_forms(id TEXT PRIMARY KEY,project_id TEXT,world_id TEXT,branch_id TEXT,session_id TEXT,subject_key TEXT NOT NULL,subject_label TEXT NOT NULL,source_turn_id TEXT NOT NULL,source_kind TEXT NOT NULL,anchor_proposition_id TEXT,parent_form_id TEXT,reason TEXT NOT NULL,story_order REAL,world_time_json TEXT,state_json TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(subject_key,source_turn_id,source_kind));
                CREATE INDEX IF NOT EXISTS idx_continuity_form_subject ON continuity_forms(project_id,world_id,subject_key,story_order,created_at);
''',
    '''                CREATE TABLE IF NOT EXISTS continuity_forms(id TEXT PRIMARY KEY,project_id TEXT,world_id TEXT,branch_id TEXT,session_id TEXT,subject_key TEXT NOT NULL,subject_label TEXT NOT NULL,source_turn_id TEXT NOT NULL,source_kind TEXT NOT NULL,anchor_proposition_id TEXT,parent_form_id TEXT,reason TEXT NOT NULL,story_order REAL,world_time_json TEXT,state_json TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(subject_key,source_turn_id,source_kind));
                CREATE INDEX IF NOT EXISTS idx_continuity_form_subject ON continuity_forms(project_id,world_id,subject_key,story_order,created_at);

                CREATE TABLE IF NOT EXISTS discovery_provisional_meta(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS discovery_changes(
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    world_id TEXT,
                    branch_id TEXT,
                    subject_key TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    from_proposition_id TEXT NOT NULL,
                    to_proposition_id TEXT NOT NULL,
                    change_kind TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'discovery',
                    source_id TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(from_proposition_id,to_proposition_id,change_kind),
                    FOREIGN KEY(from_proposition_id) REFERENCES discovery_propositions(id) ON DELETE CASCADE,
                    FOREIGN KEY(to_proposition_id) REFERENCES discovery_propositions(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_discovery_changes_subject
                    ON discovery_changes(world_id,branch_id,subject_key,predicate,created_at);
                CREATE TABLE IF NOT EXISTS discovery_spatial_zones(
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    world_id TEXT NOT NULL,
                    branch_id TEXT,
                    subject_key TEXT NOT NULL,
                    label TEXT NOT NULL,
                    zone_kind TEXT NOT NULL,
                    parent_subject_key TEXT,
                    attributes_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(world_id,branch_id,subject_key)
                );
                CREATE INDEX IF NOT EXISTS idx_discovery_zone_scope
                    ON discovery_spatial_zones(world_id,branch_id,subject_key);
''',
)
replace(
    "src/discovery/store.py",
    '''            con.execute("INSERT INTO discovery_meta(key,value) VALUES('continuity_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(CONTINUITY_SCHEMA_VERSION,))
''',
    '''            con.execute(
                "INSERT INTO discovery_meta(key,value) VALUES('continuity_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (CONTINUITY_SCHEMA_VERSION,),
            )
            con.execute(
                "INSERT INTO discovery_provisional_meta(key,value) VALUES('schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(PROVISIONAL_SCHEMA_VERSION),),
            )
''',
)

# Provisional no longer owns DDL/backups.
replace(
    "src/discovery/provisional.py",
    'from src.storage_backup import backup_sqlite_before_migrations\nfrom src.workspace.store import WORLD_BIBLE_PROJECT_ID\n',
    'from src.domain_events import get_domain_event_bus\nfrom src.workspace.store import WORLD_BIBLE_PROJECT_ID\n',
)
regex_replace(
    "src/discovery/provisional.py",
    r'''def _ensure_schema\(service: DiscoveryService\) -> None:.*?\n\ndef _resource_subject_links''',
    '''def _ensure_schema(service: DiscoveryService) -> None:
    """Mark the store-owned Provisional schema as available for this service."""
    service._provisional_schema_ready = True


def _resource_subject_links''',
)

# Workspace emits edit events after authoritative commit.
replace(
    "src/workspace/store.py",
    '''    def update_entity_family(self, family_id: str, *, note: str = "updated", **changes: Any) -> dict[str, Any]:
        fields: list[str] = []
''',
    '''    def update_entity_family(self, family_id: str, *, note: str = "updated", **changes: Any) -> dict[str, Any]:
        before = self.get_entity_family(family_id)
        fields: list[str] = []
''',
)
replace(
    "src/workspace/store.py",
    '''        return self.get_entity_family(family_id)

    def preview_entity_family_merge''',
    '''        result = self.get_entity_family(family_id)
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

    def preview_entity_family_merge''',
)
replace(
    "src/workspace/store.py",
    '''    def update_variant(self, variant_id: str, *, note: str = "updated", **changes: Any) -> dict[str, Any]:
        fields: list[str] = []
''',
    '''    def update_variant(self, variant_id: str, *, note: str = "updated", **changes: Any) -> dict[str, Any]:
        before = self.get_variant(variant_id)
        fields: list[str] = []
''',
)
replace(
    "src/workspace/store.py",
    '''        return self.get_variant(variant_id)

    def delete_variant''',
    '''        result = self.get_variant(variant_id)
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

    def delete_variant''',
)

# Provisional subscribes instead of replacing Workspace methods.
regex_replace(
    "src/discovery/provisional.py",
    r'''def bind_workspace_edit_hooks\(service: DiscoveryService\) -> None:.*?\n\ndef install_provisional_discovery''',
    '''def bind_workspace_edit_hooks(service: DiscoveryService) -> None:
    if getattr(service, "_provisional_workspace_hooks_bound", False):
        return

    def variant_updated(event) -> None:
        payload = event.payload
        note = str(payload.get("note") or "updated")
        if note.startswith("discovery:"):
            return
        before = payload.get("before") or {}
        after = payload.get("after") or {}
        changes = payload.get("changes") or {}
        if not after:
            return
        record_user_variant_edit(service, before, after, changes)

    def family_updated(event) -> None:
        payload = event.payload
        note = str(payload.get("note") or "updated")
        if note.startswith("discovery:"):
            return
        before = payload.get("before") or {}
        after = payload.get("after") or {}
        changes = payload.get("changes") or {}
        family_id = after.get("id")
        new_name = changes.get("name")
        if not family_id or not new_name or new_name == before.get("name"):
            return

        links = _resource_subject_links(service, family_id)
        keys = [row["subject_key"] for row in links]
        if keys:
            marks = ",".join("?" for _ in keys)
            with service.store._lock, service.store.connection() as con:
                con.execute(
                    f"UPDATE discovery_propositions SET subject_label=?,updated_at=? "
                    f"WHERE subject_key IN ({marks})",
                    [after["name"], utc_now(), *keys],
                )
                con.execute(
                    f"UPDATE discovery_propositions SET object_label=?,updated_at=? "
                    f"WHERE object_key IN ({marks})",
                    [after["name"], utc_now(), *keys],
                )
        if service.foundation is not None and before.get("name"):
            service.foundation.add_alias("entity_family", family_id, before["name"])

    event_bus = get_domain_event_bus(service.workspace.path)
    event_bus.subscribe(
        "workspace.variant_updated",
        variant_updated,
        key="discovery.provisional.variant_updated",
    )
    event_bus.subscribe(
        "workspace.entity_family_updated",
        family_updated,
        key="discovery.provisional.family_updated",
    )
    service._provisional_workspace_hooks_bound = True


def install_provisional_discovery''',
)

print("Workspace/Discovery event migration applied")
