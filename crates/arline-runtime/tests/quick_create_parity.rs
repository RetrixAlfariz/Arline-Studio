use arline_runtime::{config::RuntimeConfig, router, AppState};
use axum::{
    body::{to_bytes, Body},
    http::Request,
};
use serde_json::{json, Value};
use tower::ServiceExt;

fn fixture() -> (tempfile::TempDir, AppState) {
    let temp = tempfile::tempdir().unwrap();
    let config =
        RuntimeConfig::create_default(temp.path().join("config.toml"), temp.path()).unwrap();
    (temp, AppState::open(config).unwrap())
}

async fn post(state: &AppState, path: &str, body: Value) -> (u16, Value) {
    let response = router(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri(path)
                .header("host", "127.0.0.1")
                .header("content-type", "application/json")
                .body(Body::from(serde_json::to_vec(&body).unwrap()))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status().as_u16();
    let bytes = to_bytes(response.into_body(), 4 * 1024 * 1024)
        .await
        .unwrap();
    (
        status,
        serde_json::from_slice(&bytes)
            .unwrap_or_else(|_| json!({"raw": String::from_utf8_lossy(&bytes)})),
    )
}

#[tokio::test]
async fn quick_preview_parses_indonesian_and_english_prompts() {
    let (_temp, state) = fixture();
    for (text, kind, entity_type, name) in [
        ("character Mira", "entity", "character", "character Mira"),
        ("folder Notes", "folder", "", "Notes"),
        ("world Aurora", "world", "", "Aurora"),
        ("scene Gate", "document", "", "scene Gate"),
        ("karakter Mira", "entity", "character", "karakter Mira"),
    ] {
        let (status, response) =
            post(&state, "/api/quick-create/preview", json!({"text":text})).await;
        assert_eq!(status, 200, "{text}: {response}");
        assert_eq!(response["kind"], kind, "{text}: {response}");
        assert_eq!(response["name"], name, "{text}: {response}");
        if !entity_type.is_empty() {
            assert_eq!(response["entity_type"], entity_type, "{text}: {response}");
        }
        assert!(response.get("confidence").is_some());
        assert!(response.get("attributes").is_some());
        assert!(response.get("shared_core").is_some());
        assert!(response.get("possible_matches").is_some());
    }
}

#[tokio::test]
async fn quick_entity_is_library_global_and_variant_uses_main_world() {
    let (_temp, state) = fixture();
    let (status, response) = post(
        &state,
        "/api/quick-create",
        json!({"text":"character Mira"}),
    )
    .await;
    assert_eq!(status, 200, "{response}");
    assert_eq!(response["kind"], "entity");
    let family = &response["resource"];
    assert_eq!(family["project_id"], "PROJ-WORLD-BIBLE");
    let variant = &response["variant"];
    assert_eq!(variant["world_id"], "WORLD-BIBLE-MAIN");
    assert!(variant["branch_id"].is_null());
    let families = state.store.list("entity_families", &[]).unwrap();
    assert!(families.iter().any(|row| row["id"] == family["id"]));
}

#[tokio::test]
async fn quick_folder_and_document_require_project_and_persist_scope() {
    let (_temp, state) = fixture();
    state
        .store
        .insert("projects", json!({"id":"p","name":"P","slug":"p"}))
        .unwrap();
    let (status, folder) = post(
        &state,
        "/api/quick-create",
        json!({"text":"folder Notes","project_id":"p"}),
    )
    .await;
    assert_eq!(status, 200, "{folder}");
    assert_eq!(folder["resource"]["project_id"], "p");
    let folder_id = folder["resource"]["id"].as_str().unwrap();
    let (status, document) = post(
        &state,
        "/api/quick-create",
        json!({"text":"scene Gate","project_id":"p","folder_id":folder_id}),
    )
    .await;
    assert_eq!(status, 200, "{document}");
    assert_eq!(document["resource"]["project_id"], "p");
    assert_eq!(document["resource"]["folder_id"], folder_id);
}

#[tokio::test]
async fn story_lab_bundle_defaults_selected_and_creates_one_shared_sandbox_branch() {
    let (_temp, state) = fixture();
    state
        .store
        .insert("projects", json!({"id":"p","name":"P","slug":"p"}))
        .unwrap();
    let (_status, first) = post(
        &state,
        "/api/story-lab/sheet-proposals",
        json!({
            "project_id":"p", "world_id":"WORLD-BIBLE-MAIN", "kind":"character",
            "name":"Mira", "source_text":"Mira guards the gate."
        }),
    )
    .await;
    let (_status, second) = post(
        &state,
        "/api/story-lab/sheet-proposals",
        json!({
            "project_id":"p", "world_id":"WORLD-BIBLE-MAIN", "kind":"location",
            "name":"Gate", "source_text":"The gate stands above the valley."
        }),
    )
    .await;
    let c1 = first["change"]["id"].as_str().unwrap();
    let c2 = second["change"]["id"].as_str().unwrap();
    let (status, response) = post(&state, "/api/story-lab/sheet-proposal-bundles/apply", json!({
        "action":"branch", "branch_name":"Mira and Gate", "items":[
            {"change_id":c1,"proposal":{"kind":"character","name":"Mira","content":"Mira guards the gate.","operation":"create"}},
            {"change_id":c2,"proposal":{"kind":"location","name":"Gate","content":"The gate stands above the valley.","operation":"create"}}
        ]
    })).await;
    assert_eq!(status, 200, "{response}");
    let branch = &response["branch"];
    assert_eq!(branch["kind"], "sandbox");
    assert_eq!(response["results"].as_array().unwrap().len(), 2);
    let variants = state
        .store
        .list("entity_variants", &[("branch_id", branch["id"].clone())])
        .unwrap();
    assert_eq!(variants.len(), 2);
    assert!(variants.iter().all(|row| row["canon_status"] == "what_if"));
}

#[tokio::test]
async fn story_lab_bundle_explicit_rejection_leaves_resource_tables_unchanged() {
    let (_temp, state) = fixture();
    state
        .store
        .insert("projects", json!({"id":"p","name":"P","slug":"p"}))
        .unwrap();
    let (_status, staged) = post(
        &state,
        "/api/story-lab/sheet-proposals",
        json!({
            "project_id":"p", "world_id":"WORLD-BIBLE-MAIN", "kind":"character",
            "name":"Rejected", "source_text":"A rejected character."
        }),
    )
    .await;
    let change_id = staged["change"]["id"].as_str().unwrap();
    let (status, response) = post(
        &state,
        "/api/story-lab/sheet-proposal-bundles/apply",
        json!({
            "action":"accept", "items":[{"change_id":change_id,"selected":false}]
        }),
    )
    .await;
    assert_eq!(status, 200, "{response}");
    assert_eq!(response["results"][0]["change"]["status"], "rejected");
    assert!(state
        .store
        .list("entity_families", &[("name", json!("Rejected"))])
        .unwrap()
        .is_empty());
}

#[tokio::test]
async fn story_lab_apply_stale_change_returns_not_found() {
    let (_temp, state) = fixture();
    let (status, response) = post(
        &state,
        "/api/story-lab/sheet-proposals/missing-change/apply",
        json!({"action":"accept"}),
    )
    .await;
    assert_eq!(status, 404, "{response}");
}
