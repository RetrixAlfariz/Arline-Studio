use arline_runtime::{config::RuntimeConfig, router, AppState};
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use serde_json::{json, Value};
use tower::ServiceExt;

fn fixture() -> (tempfile::TempDir, AppState) {
    let temp = tempfile::tempdir().unwrap();
    let config =
        RuntimeConfig::create_default(temp.path().join("config.toml"), temp.path()).unwrap();
    let state = AppState::open(config).unwrap();
    (temp, state)
}

async fn request(state: &AppState, method: &str, path: &str, body: Value) -> (StatusCode, Value) {
    let response = router(state.clone())
        .oneshot(
            Request::builder()
                .method(method)
                .uri(path)
                .header("host", "127.0.0.1")
                .header("content-type", "application/json")
                .body(Body::from(serde_json::to_vec(&body).unwrap()))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 4 * 1024 * 1024)
        .await
        .unwrap();
    (
        status,
        serde_json::from_slice(&bytes)
            .unwrap_or_else(|_| json!({"raw":String::from_utf8_lossy(&bytes)})),
    )
}

#[tokio::test]
async fn startup_routes_are_owned_by_the_correct_services() {
    let (_temp, state) = fixture();
    for path in [
        "/api/health",
        "/api/config",
        "/api/workspace/bootstrap",
        "/api/world-bible",
        "/api/commands",
        "/api/sessions",
        "/api/home",
        "/api/user-profile",
        "/api/preferences",
        "/api/run-profiles",
        "/api/memory/status",
    ] {
        let (status, value) = request(&state, "GET", path, json!({})).await;
        assert_eq!(status, StatusCode::OK, "{path}: {value}");
    }
}

#[tokio::test]
async fn project_and_document_routes_preserve_created_content() {
    let (_temp, state) = fixture();
    let (status, project) = request(
        &state,
        "POST",
        "/api/projects",
        json!({"name":"Native writing"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{project}");
    let project_id = project["id"].as_str().expect("project id");
    let (status, loaded) = request(
        &state,
        "GET",
        &format!("/api/projects/{project_id}"),
        json!({}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{loaded}");
    assert_eq!(loaded["name"], "Native writing");
    let (status,doc)=request(&state,"POST","/api/documents",json!({"project_id":project_id,"title":"Scene one","content":"Mara kept the radio on.","document_type":"scene"})).await;
    assert_eq!(status, StatusCode::OK, "{doc}");
    let id = doc["id"].as_str().expect("document id");
    let (status, loaded) = request(&state, "GET", &format!("/api/documents/{id}"), json!({})).await;
    assert_eq!(status, StatusCode::OK, "{loaded}");
    assert_eq!(loaded["content"], "Mara kept the radio on.");
    let (status, empty) = request(
        &state,
        "GET",
        &format!("/api/projects/{project_id}/active-scene"),
        json!({}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert!(empty.is_object());
    assert!(empty["active_scene"].is_null());
    let (status, active) = request(
        &state,
        "PUT",
        &format!("/api/projects/{project_id}/active-scene"),
        json!({"document_id":id}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{active}");
    let (_, active) = request(
        &state,
        "GET",
        &format!("/api/projects/{project_id}/active-scene"),
        json!({}),
    )
    .await;
    assert_eq!(active["document"]["title"], "Scene one");
}

#[tokio::test]
async fn session_modes_round_trip_with_user_profile_and_notes() {
    let (_temp, state) = fixture();
    request(&state, "GET", "/api/sessions", json!({})).await;
    state.store.insert("sessions",json!({"id":"chat-fixture","title":"Native chat","conversation_mode":"story_lab","conversation_profile":{"living_session":{"current_question":"Why the lighthouse?"}},"created_at":"2026-10-23T00:00:00Z","updated_at":"2026-10-23T00:00:00Z"})).unwrap();
    let (status, value) = request(
        &state,
        "PATCH",
        "/api/sessions/chat-fixture",
        json!({"conversation_mode":"interactive"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{value}");
    let (status, value) = request(&state, "GET", "/api/sessions/chat-fixture", json!({})).await;
    assert_eq!(status, StatusCode::OK, "{value}");
    assert_eq!(value["conversation_mode"], "interactive");
    assert_eq!(
        value["conversation_profile"]["living_session"]["current_question"],
        "Why the lighthouse?"
    );
    assert!(value["turns"].is_array());
    assert!(
        value["mode_events"]
            .as_array()
            .is_some_and(|events| !events.is_empty()),
        "mode transitions must be durable: {value}"
    );
}

#[tokio::test]
async fn invalid_remote_host_and_cross_origin_writes_are_rejected() {
    let (_temp, state) = fixture();
    let response = router(state.clone())
        .oneshot(
            Request::builder()
                .uri("/api/config")
                .header("host", "external.invalid")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::FORBIDDEN);
    let response = router(state)
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/projects")
                .header("host", "127.0.0.1")
                .header("origin", "https://external.invalid")
                .header("content-type", "application/json")
                .body(Body::from(r#"{"name":"Unwanted"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn media_upload_uses_managed_storage_and_cannot_repoint_or_delete_external_files() {
    let (temp, state) = fixture();
    let world = state.store.list("worlds", &[]).unwrap()[0]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    let (status,media)=request(&state,"POST","/api/media",json!({"resource_type":"world","resource_id":world,"filename":"reference.png","data_url":"data:image/png;base64,aW1hZ2U=","caption":"Writing reference"})).await;
    assert_eq!(status, StatusCode::OK, "{media}");
    assert_eq!(media["original_name"], "reference.png");
    assert!(media.get("storage_path").is_none());
    let id = media["id"].as_str().unwrap();
    let protected = temp.path().join("protected.txt");
    std::fs::write(&protected, "preserve").unwrap();
    let (status, _) = request(
        &state,
        "PATCH",
        &format!("/api/media/{id}"),
        json!({"storage_path":protected}),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    state
        .store
        .update("resource_media", id, json!({"storage_path":protected}))
        .unwrap();
    let (status, _) = request(&state, "DELETE", &format!("/api/media/{id}"), json!({})).await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(std::fs::read_to_string(protected).unwrap(), "preserve");
}

#[tokio::test]
async fn session_lists_apply_world_branch_and_lifecycle_filters() {
    let (_temp, state) = fixture();
    request(&state, "GET", "/api/sessions", json!({})).await;
    for (id, world, branch, archived) in [
        ("wanted", "one", "b-one", false),
        ("foreign", "two", "b-two", false),
        ("archived", "one", "b-one", true),
        ("trashed", "one", "b-one", false),
    ] {
        state.store.insert("sessions",json!({"id":id,"title":id,"project_id":"p","world_id":world,"branch_id":branch,"archived":archived})).unwrap();
    }
    arline_runtime::foundation::FoundationStore::from_store(state.store.clone())
        .trash("session", "trashed", None)
        .unwrap();
    let (status, result) = request(
        &state,
        "GET",
        "/api/sessions?project_id=p&world_id=one&branch_id=b-one",
        json!({}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{result}");
    assert_eq!(result["sessions"].as_array().unwrap().len(), 1);
    assert_eq!(result["sessions"][0]["id"], "wanted");
    let (_, all) = request(&state, "GET", "/api/sessions", json!({})).await;
    assert_eq!(all["sessions"].as_array().unwrap().len(), 2);
}

#[tokio::test]
async fn session_fork_copies_history_atomically_and_reports_nested_family() {
    let (_temp, state) = fixture();
    state.store.insert("sessions", json!({"id":"fork-root","title":"Root","created_at":"2026-10-23T00:00:00Z","updated_at":"2026-10-23T00:00:00Z"})).unwrap();
    state.store.insert("turns", json!({"id":"root-turn-1","session_id":"fork-root","user_prompt":"first","story":"answer one","run_id":"RUN-1","created_at":"2026-10-23T00:00:01Z","updated_at":"2026-10-23T00:00:01Z"})).unwrap();
    state.store.insert("turns", json!({"id":"root-turn-2","session_id":"fork-root","user_prompt":"second","story":"answer two","run_id":"RUN-2","created_at":"2026-10-23T00:00:02Z","updated_at":"2026-10-23T00:00:02Z"})).unwrap();
    let before = state.store.list("sessions", &[]).unwrap().len();
    let (status, invalid) = request(
        &state,
        "POST",
        "/api/sessions/fork-root/fork",
        json!({"through_turn_id":"foreign-turn"}),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{invalid}");
    assert_eq!(state.store.list("sessions", &[]).unwrap().len(), before);

    let (status, fork) = request(
        &state,
        "POST",
        "/api/sessions/fork-root/fork",
        json!({"through_turn_id":"root-turn-1"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{fork}");
    let fork_id = fork["id"].as_str().unwrap();
    assert_eq!(fork["title"], "Root (fork)");
    assert!(fork["folder_id"].is_null());
    assert_eq!(fork["pinned"], false);
    assert_eq!(fork["archived"], false);
    assert_eq!(fork["turns"].as_array().unwrap().len(), 1);
    assert_eq!(fork["turns"][0]["user_prompt"], "first");
    assert!(fork["turns"][0]["run_id"]
        .as_str()
        .unwrap()
        .starts_with("FORK-RUN-1-"));
    assert_eq!(
        fork["turns"][0]["lineage"]["forked_from_session_id"],
        "fork-root"
    );
    assert_eq!(
        fork["turns"][0]["lineage"]["forked_from_turn_id"],
        "root-turn-1"
    );

    let (status, nested) = request(
        &state,
        "POST",
        &format!("/api/sessions/{fork_id}/fork"),
        json!({}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{nested}");
    let nested_id = nested["id"].as_str().unwrap();
    let (status, family) = request(&state, "GET", "/api/sessions/fork-root/forks", json!({})).await;
    assert_eq!(status, StatusCode::OK, "{family}");
    let sessions = family["sessions"].as_array().unwrap();
    assert!(sessions.iter().any(|x| x["id"] == fork_id));
    assert!(sessions.iter().any(|x| x["id"] == nested_id));
    assert_eq!(family["active_id"], "fork-root");
}
