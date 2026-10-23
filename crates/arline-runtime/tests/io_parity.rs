use arline_runtime::{config::RuntimeConfig, router, AppState};
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use serde_json::{json, Value};
use std::io::Cursor;
use tempfile::TempDir;
use tower::ServiceExt;

fn fixture() -> (TempDir, AppState) {
    let dir = tempfile::tempdir().unwrap();
    let cfg = RuntimeConfig::create_default(dir.path().join("runtime.toml"), dir.path()).unwrap();
    (dir, AppState::open(cfg).unwrap())
}
async fn request(state: &AppState, method: &str, uri: &str, body: Value) -> (StatusCode, Value) {
    let response = router(state.clone())
        .oneshot(
            Request::builder()
                .method(method)
                .uri(uri)
                .header("content-type", "application/json")
                .body(Body::from(body.to_string()))
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
        serde_json::from_slice(&bytes).unwrap_or_else(|_| json!({})),
    )
}

async fn bytes_request(
    state: &AppState,
    method: &str,
    uri: &str,
    body: Value,
) -> (StatusCode, Vec<u8>) {
    let response = router(state.clone())
        .oneshot(
            Request::builder()
                .method(method)
                .uri(uri)
                .header("content-type", "application/json")
                .body(Body::from(body.to_string()))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 8 * 1024 * 1024)
        .await
        .unwrap();
    (status, bytes.to_vec())
}

#[tokio::test]
async fn manuscript_import_preview_and_project_export_are_stateful() {
    let (_tmp, state) = fixture();
    let project = state.store.list("projects", &[]).unwrap()[0]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    let (status, preview) = request(
        &state,
        "POST",
        "/api/import/manuscript/preview",
        json!({"project_id":project,"title":"Book","text":"# Chapter One\nA\n## Scene\nB"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(preview["count"], 2);
    let (status, imported) = request(
        &state,
        "POST",
        "/api/import/manuscript",
        json!({"project_id":project,"title":"Book","text":"# Chapter One\nA\n## Scene\nB"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(imported["documents"].as_array().unwrap().len(), 2);
    let (status, bundle) = request(
        &state,
        "GET",
        &format!("/api/export/project/{project}"),
        json!({}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(bundle["schema_version"], 7);
    assert_eq!(bundle["documents"].as_array().unwrap().len(), 2);
}

#[tokio::test]
async fn dataset_stats_and_empty_exports_have_contracts() {
    let (_tmp, state) = fixture();
    let (status, stats) = request(&state, "GET", "/api/dataset/stats", json!({})).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(stats["total"], 0);
    for kind in ["master", "sft", "preference", "eval"] {
        let (status, out) = request(
            &state,
            "POST",
            &format!("/api/dataset/export/{kind}"),
            json!({}),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(out["kind"], kind);
        assert!(out["filename"].as_str().unwrap().ends_with(".jsonl"));
    }
}

#[tokio::test]
async fn reset_requires_exact_confirmation_and_creates_recovery_backup() {
    let (_tmp, state) = fixture();
    let (status, _) = request(
        &state,
        "POST",
        "/api/storage/reset",
        json!({"mode":"database","confirmation":"wrong"}),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    let (status, report) = request(
        &state,
        "POST",
        "/api/storage/reset",
        json!({"mode":"database","confirmation":"RESET DATABASE"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(report["mode"], "database");
    assert_eq!(report["backups"].as_array().unwrap().len(), 1);
}

#[tokio::test]
async fn feedback_exports_filter_real_records_and_saved_artifact_is_zip() {
    let (_tmp, state) = fixture();
    let now = chrono::Utc::now().to_rfc3339();
    let c = state.store.connection().unwrap();
    c.execute(
        "INSERT INTO sessions(id,title,created_at,updated_at) VALUES('S1','Session',?,?)",
        rusqlite::params![now, now],
    )
    .unwrap();
    for (id, run, status, edited) in [
        ("T1", "RUN-M", "unreviewed", ""),
        ("T2", "RUN-S", "accepted", ""),
        ("T3", "RUN-P", "edited_accept", "chosen"),
        ("T4", "RUN-E", "rejected", ""),
    ] {
        c.execute("INSERT INTO turns(id,session_id,run_id,created_at,updated_at,user_prompt,story,feedback_status,edited_story) VALUES(?,?,?,?,?,?,?,?,?)", rusqlite::params![id,"S1",run,now,now,"prompt",format!("story-{id}"),status,edited]).unwrap();
    }
    let (status, queue) = request(
        &state,
        "GET",
        "/api/feedback/queue?status=accepted",
        json!({}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(queue["items"].as_array().unwrap().len(), 1);
    for kind in ["master", "sft", "preference", "eval"] {
        let (status, out) = request(
            &state,
            "POST",
            &format!("/api/dataset/export/{kind}"),
            json!({}),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        let config = state.runtime_config().unwrap();
        let file = config
            .resolve(&config.str("history.dataset_root", "data/datasets"))
            .join(out["filename"].as_str().unwrap());
        let text = std::fs::read_to_string(file).unwrap();
        assert!(!text.is_empty());
        if kind == "sft" {
            assert_eq!(text.lines().count(), 2);
        }
    }
    let (status, out) = request(&state, "POST", "/api/save", json!({"run_id":"RUN-S"})).await;
    assert_eq!(status, StatusCode::OK);
    let archive = out["archive_name"].as_str().unwrap();
    let (status, bytes) =
        bytes_request(&state, "GET", &format!("/downloads/{archive}"), json!({})).await;
    assert_eq!(status, StatusCode::OK);
    let mut zip = zip::ZipArchive::new(Cursor::new(bytes)).unwrap();
    assert!(zip.len() >= 8);
    assert!(zip.by_name("manifest-RUN-S.json").is_ok());
    let (status, _) = request(&state, "POST", "/api/save", json!({"run_id":"RUN-S"})).await;
    assert_eq!(status, StatusCode::OK);
}
