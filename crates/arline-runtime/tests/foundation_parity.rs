use arline_runtime::{config::RuntimeConfig, router, AppState};
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use serde_json::{json, Value};
use tower::ServiceExt;
fn fixture() -> (tempfile::TempDir, AppState) {
    let dir = tempfile::tempdir().unwrap();
    let cfg = RuntimeConfig::create_default(dir.path().join("config.toml"), dir.path()).unwrap();
    let state = AppState::open(cfg).unwrap();
    (dir, state)
}
async fn req(s: &AppState, m: &str, u: &str, b: Value) -> (StatusCode, Value) {
    let r = router(s.clone())
        .oneshot(
            Request::builder()
                .method(m)
                .uri(u)
                .header("host", "localhost")
                .body(Body::from(b.to_string()))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = r.status();
    let bytes = to_bytes(r.into_body(), 8 * 1024 * 1024).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(json!(null)),
    )
}
#[tokio::test]
async fn identity_collection_inspector_and_lifecycle_roundtrip() {
    let (_dir, s) = fixture();
    let (status, project) = req(&s, "POST", "/api/projects", json!({"name":"My manuscript"})).await;
    assert_eq!(status, StatusCode::OK, "{project}");
    let pid = project["id"].as_str().unwrap();
    let (_, doc) = req(
        &s,
        "POST",
        "/api/documents",
        json!({"project_id":pid,"title":"Scene","content":"Mara waits."}),
    )
    .await;
    let id = doc["id"].as_str().unwrap();
    let (_, alias) = req(
        &s,
        "POST",
        "/api/aliases",
        json!({"resource_type":"document","resource_id":id,"alias":"Opening"}),
    )
    .await;
    let (status, dup) = req(
        &s,
        "POST",
        "/api/aliases",
        json!({"resource_type":"document","resource_id":id,"alias":"opening"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{dup}");
    assert_eq!(alias["id"], dup["id"]);
    let (_, coll) = req(&s, "POST", "/api/collections", json!({"name":"Favorites"})).await;
    let cid = coll["id"].as_str().unwrap();
    let (status, linked) = req(
        &s,
        "POST",
        &format!("/api/collections/{cid}/links"),
        json!({"resource_type":"document","resource_id":id}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{linked}");
    assert_eq!(linked["links"][0]["resource_id"], id);
    let (status, inspect) = req(
        &s,
        "GET",
        &format!("/api/resources/document/{id}"),
        json!({}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{inspect}");
    assert_eq!(inspect["aliases"].as_array().unwrap().len(), 1);
    assert_eq!(inspect["collections"][0]["id"], cid);
    let (status, _) = req(
        &s,
        "DELETE",
        &format!("/api/trash/document/{id}"),
        json!({}),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT);
    let (status, _) = req(
        &s,
        "POST",
        "/api/lifecycle/trash",
        json!({"resource_type":"document","resource_id":id}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let (_, trash) = req(&s, "GET", "/api/trash", json!({})).await;
    assert_eq!(trash["items"][0]["resource"]["id"], id);
    let (status, deleted) = req(
        &s,
        "DELETE",
        &format!("/api/trash/document/{id}"),
        json!({}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{deleted}");
    assert!(s.store.get("workspace_documents", id).unwrap().is_none());
    let (_, cols) = req(&s, "GET", "/api/collections", json!({})).await;
    assert_eq!(cols["collections"][0]["links"], json!([]));
    let (status, _) = req(
        &s,
        "GET",
        &format!("/api/resources/document/{id}"),
        json!({}),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}
#[tokio::test]
async fn context_preferences_and_builtin_protection() {
    let (_dir, s) = fixture();
    let (status,saved)=req(&s,"PUT","/api/context-stack",json!({"stack_id":"writer","references":[{"type":"document","id":"draft"}],"overrides":{"language":"id"}})).await;
    assert_eq!(status, StatusCode::OK, "{saved}");
    let (_, loaded) = req(&s, "GET", "/api/context-stack?stack_id=writer", json!({})).await;
    assert_eq!(loaded["references"][0]["id"], "draft");
    assert_eq!(loaded["overrides"]["language"], "id");
    let (status, saved) = req(
        &s,
        "PUT",
        "/api/preferences",
        json!({"key":"theme","value":"dark"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(saved, json!({"ok":true}));
    let (_, prefs) = req(&s, "GET", "/api/preferences", json!({})).await;
    assert_eq!(prefs["theme"], "dark");
    let (_, profiles) = req(&s, "GET", "/api/run-profiles", json!({})).await;
    let id = profiles["profiles"][0]["id"].as_str().unwrap();
    let (status, _) = req(&s, "DELETE", &format!("/api/run-profiles/{id}"), json!({})).await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    let (status, _) = req(
        &s,
        "POST",
        "/api/run-profiles",
        json!({"id":id,"name":"Overwrite builtin","profile":{}}),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    let (status, _) = req(
        &s,
        "POST",
        "/api/lifecycle/trash",
        json!({"resource_type":"document","resource_id":"does-not-exist"}),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}
#[tokio::test]
async fn selecting_a_cover_replaces_only_the_same_owners_cover() {
    let (_dir, s) = fixture();
    let world = s.store.list("worlds", &[]).unwrap()[0]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    let upload = |name: &str| json!({"resource_type":"world","resource_id":world,"filename":name,"data_url":"data:image/png;base64,aW1hZ2U=","is_cover":true});
    let (status, first) = req(&s, "POST", "/api/media", upload("../first.png")).await;
    assert_eq!(status, StatusCode::OK, "{first}");
    assert_eq!(first["original_name"], "first.png");
    let (status, second) = req(&s, "POST", "/api/media", upload("second.png")).await;
    assert_eq!(status, StatusCode::OK, "{second}");
    let (_, covers) = req(
        &s,
        "GET",
        &format!("/api/media?resource_type=world&resource_id={world}&cover_only=true"),
        json!({}),
    )
    .await;
    assert_eq!(covers["items"].as_array().unwrap().len(), 1);
    assert_eq!(covers["items"][0]["id"], second["id"]);
    let (status, _) = req(
        &s,
        "PATCH",
        &format!("/api/media/{}", first["id"].as_str().unwrap()),
        json!({"is_cover":true}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let (_, covers) = req(
        &s,
        "GET",
        &format!("/api/media?resource_type=world&resource_id={world}&cover_only=true"),
        json!({}),
    )
    .await;
    assert_eq!(covers["items"].as_array().unwrap().len(), 1);
    assert_eq!(covers["items"][0]["id"], first["id"]);
}
