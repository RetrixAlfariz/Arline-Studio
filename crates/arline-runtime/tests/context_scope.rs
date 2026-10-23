use arline_runtime::{config::RuntimeConfig, context::build_context, AppState};
use serde_json::json;

fn fixture() -> (tempfile::TempDir, AppState) {
    let temp = tempfile::tempdir().unwrap();
    let config =
        RuntimeConfig::create_default(temp.path().join("config.toml"), temp.path()).unwrap();
    let state = AppState::open(config).unwrap();
    (temp, state)
}

fn project(state: &AppState, id: &str, name: &str) {
    state
        .store
        .insert("projects", json!({"id":id,"name":name,"slug":id}))
        .unwrap();
}

fn world(state: &AppState, id: &str, project_id: &str, name: &str) {
    state
        .store
        .insert(
            "worlds",
            json!({"id":id,"project_id":project_id,"name":name,"slug":id}),
        )
        .unwrap();
}

fn branch(state: &AppState, id: &str, world_id: &str) {
    state
        .store
        .insert(
            "world_branches",
            json!({"id":id,"world_id":world_id,"name":id,"slug":id}),
        )
        .unwrap();
}

fn fact(
    state: &AppState,
    id: &str,
    project_id: &str,
    world_id: Option<&str>,
    branch_id: Option<&str>,
    path: &str,
    value: &str,
) {
    state
        .store
        .insert(
            "canon_facts",
            json!({
                "id":id,
                "project_id":project_id,
                "world_id":world_id,
                "branch_id":branch_id,
                "owner_type":"world",
                "owner_id":world_id.unwrap_or(project_id),
                "path":path,
                "value":value,
                "status":"canon",
                "authority":"user_explicit",
                "source_type":"manual"
            }),
        )
        .unwrap();
}

#[test]
fn linked_world_bible_is_visible_but_unlinked_world_isolated() {
    let (_temp, state) = fixture();
    project(&state, "bible", "World Bible");
    project(&state, "writing", "Writing Project");
    world(&state, "shared-world", "bible", "Shared World");
    world(&state, "other-world", "bible", "Other World");
    state
        .store
        .connection()
        .unwrap()
        .execute(
            "INSERT INTO project_world_links(project_id,world_id,role,created_at) VALUES(?,?,?,?)",
            rusqlite::params![
                "writing",
                "shared-world",
                "reference",
                "2026-10-23T00:00:00Z"
            ],
        )
        .unwrap();
    fact(
        &state,
        "shared-fact",
        "bible",
        Some("shared-world"),
        None,
        "setting.city",
        "Shared City",
    );
    fact(
        &state,
        "other-fact",
        "bible",
        Some("other-world"),
        None,
        "setting.city",
        "Other City",
    );

    let context = build_context(
        &state,
        &json!({"project_id":"writing","world_id":"shared-world"}),
    )
    .unwrap();
    assert!(context.contains("Shared City"));
    assert!(!context.contains("Other City"));
}

#[test]
fn active_branch_wins_while_global_fact_remains_available() {
    let (_temp, state) = fixture();
    project(&state, "project", "Project");
    world(&state, "world", "project", "World");
    branch(&state, "branch-a", "world");
    branch(&state, "branch-b", "world");
    fact(
        &state,
        "global",
        "project",
        None,
        None,
        "rule.global",
        "Global canon",
    );
    fact(
        &state,
        "active",
        "project",
        Some("world"),
        Some("branch-a"),
        "rule.active",
        "Active branch canon",
    );
    fact(
        &state,
        "inactive",
        "project",
        Some("world"),
        Some("branch-b"),
        "rule.inactive",
        "Inactive branch canon",
    );

    let context = build_context(
        &state,
        &json!({"project_id":"project","world_id":"world","branch_id":"branch-a"}),
    )
    .unwrap();
    assert!(context.contains("Global canon"));
    assert!(context.contains("Active branch canon"));
    assert!(!context.contains("Inactive branch canon"));
}

#[test]
fn private_and_sensitive_profile_fields_are_never_emitted() {
    let (_temp, state) = fixture();
    project(&state, "project", "Project");
    state
        .store
        .insert(
            "user_profiles",
            json!({
                "id":"default",
                "profile":{
                    "collaboration":{"tone":"precise","private_note":"do not emit","email":"secret@example.test","sensitive_style":{"value":"hidden","sensitive":true}}
                }
            }),
        )
        .unwrap();

    let context = build_context(&state, &json!({"project_id":"project"})).unwrap();
    assert!(context.contains("precise"));
    assert!(!context.contains("do not emit"));
    assert!(!context.contains("secret@example.test"));
    assert!(!context.contains("hidden"));
}

#[test]
fn explicit_reference_from_another_project_is_rejected() {
    let (_temp, state) = fixture();
    project(&state, "project-a", "Project A");
    project(&state, "project-b", "Project B");
    world(&state, "world-a", "project-a", "World A");
    world(&state, "world-b", "project-b", "World B");
    state
        .store
        .insert("workspace_documents", json!({"id":"foreign-doc","project_id":"project-b","world_id":"world-b","title":"Foreign","content":"Private content","document_type":"scene"}))
        .unwrap();

    let result = build_context(
        &state,
        &json!({
            "project_id":"project-a",
            "world_id":"world-a",
            "references":[{"type":"document","id":"foreign-doc"}]
        }),
    );
    assert!(result.is_err());
}

#[test]
fn unicode_budget_preserves_valid_closing_tag() {
    let (_temp, state) = fixture();
    project(&state, "project", "Project");
    let mut config = state.runtime_config().unwrap();
    config
        .set("context_budget.max_chars", toml::Value::Integer(512))
        .unwrap();
    *state.config.write().unwrap() = config;
    state
        .store
        .insert("workspace_documents", json!({"id":"doc","project_id":"project","title":"Scene","content":"😀".repeat(2_000),"document_type":"scene"}))
        .unwrap();
    state
        .store
        .connection()
        .unwrap()
        .execute(
            "INSERT INTO project_active_scenes(project_id,document_id,updated_at) VALUES(?,?,?)",
            rusqlite::params!["project", "doc", "2026-10-23T00:00:00Z"],
        )
        .unwrap();

    let context = build_context(&state, &json!({"project_id":"project"})).unwrap();
    assert!(context.chars().count() <= 512);
    assert!(context.ends_with("</ARLINE_CONTEXT>"));
    assert!(std::str::from_utf8(context.as_bytes()).is_ok());
}
