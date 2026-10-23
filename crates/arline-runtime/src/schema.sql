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
