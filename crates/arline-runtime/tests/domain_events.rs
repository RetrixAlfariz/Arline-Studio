use arline_runtime::{config::RuntimeConfig, domain_events, router, AppState};
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use serde_json::{json, Value};
use tower::ServiceExt;

fn state() -> (tempfile::TempDir, AppState) {
    let dir = tempfile::tempdir().unwrap();
    let cfg = RuntimeConfig::create_default(dir.path().join("runtime.toml"), dir.path()).unwrap();
    let state = AppState::open(cfg).unwrap();
    (dir, state)
}
async fn request(s: &AppState, method: &str, path: &str, body: Value) -> Value {
    let response = router(s.clone())
        .oneshot(
            Request::builder()
                .method(method)
                .uri(path)
                .body(Body::from(body.to_string()))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 1024 * 1024).await.unwrap();
    let result: Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(status, StatusCode::OK, "{result}");
    result
}

#[tokio::test]
async fn document_mutations_update_retrieval_without_manual_backfill() {
    let (_dir, s) = state();
    let project = request(&s, "POST", "/api/projects", json!({"name":"Hooks"})).await;
    let doc = request(
        &s,
        "POST",
        "/api/documents",
        json!({"project_id":project["id"],"title":"Notes","content":"amber tide"}),
    )
    .await;
    let first = request(
        &s,
        "POST",
        "/api/memory/query",
        json!({"query":"amber","project_id":project["id"]}),
    )
    .await;
    assert!(first["selected"]
        .as_array()
        .unwrap()
        .iter()
        .any(|x| x["source_id"] == doc["id"]));
    request(
        &s,
        "PATCH",
        &format!("/api/documents/{}", doc["id"].as_str().unwrap()),
        json!({"content":"cobalt coast"}),
    )
    .await;
    let stale = request(
        &s,
        "POST",
        "/api/memory/query",
        json!({"query":"amber","project_id":project["id"]}),
    )
    .await;
    assert!(!stale["selected"]
        .as_array()
        .unwrap()
        .iter()
        .any(|x| x["source_id"] == doc["id"]));
    let fresh = request(
        &s,
        "POST",
        "/api/memory/query",
        json!({"query":"cobalt","project_id":project["id"]}),
    )
    .await;
    assert!(fresh["selected"]
        .as_array()
        .unwrap()
        .iter()
        .any(|x| x["source_id"] == doc["id"]));
    request(
        &s,
        "DELETE",
        &format!("/api/documents/{}", doc["id"].as_str().unwrap()),
        json!({}),
    )
    .await;
    assert!(s
        .store
        .query(
            "SELECT id FROM memory_chunks WHERE source_id=? AND semantic_status='active'",
            &[&doc["id"].as_str().unwrap()]
        )
        .unwrap()
        .is_empty());
    assert!(s
        .store
        .query("SELECT id FROM native_change_queue", &[])
        .unwrap()
        .is_empty());
}

#[test]
fn transactional_workspace_writes_notify_projections_and_rollback_discards_events() {
    let (_dir, s) = state();
    let world = s.store.list("worlds", &[]).unwrap()[0]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    s.store
        .insert(
            "entity_families",
            json!({"id":"hook-family","project_id":s.store.list("projects",&[]).unwrap()[0]["id"],"name":"Mara","entity_type":"character"}),
        )
        .unwrap();
    s.store
        .insert(
            "entity_variants",
            json!({"id":"hook-mara","family_id":"hook-family","world_id":world,"display_name":"Mara"}),
        )
        .unwrap();
    s.store.insert("canon_facts",json!({"id":"hook-fact","project_id":s.store.list("projects",&[]).unwrap()[0]["id"],"world_id":world,"owner_type":"entity_variant","owner_id":"hook-mara","path":"mood","value":"calm","status":"canon"})).unwrap();
    domain_events::flush(&s).unwrap();
    let state=s.store.query("SELECT value_json FROM current_state_projection WHERE world_id=? AND owner_id='hook-mara' AND state_key='mood'",&[&world]).unwrap();
    assert_eq!(state.len(), 1);
    assert_eq!(state[0]["value"], "calm");
    let mut connection = s.store.connection().unwrap();
    {
        let tx = connection.transaction().unwrap();
        tx.execute(
            "UPDATE canon_facts SET value_json='\"angry\"' WHERE id='hook-fact'",
            [],
        )
        .unwrap();
    }
    assert!(
        s.store
            .query("SELECT id FROM native_change_queue", &[])
            .unwrap()
            .is_empty(),
        "rolled back writes must not enqueue projection changes"
    );
    s.store.delete("canon_facts", "hook-fact").unwrap();
    domain_events::flush(&s).unwrap();
    assert!(s.store.query("SELECT * FROM current_state_projection WHERE world_id=? AND owner_id='hook-mara' AND state_key='mood'",&[&world]).unwrap().is_empty());
}
