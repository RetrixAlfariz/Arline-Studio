use arline_runtime::{config::RuntimeConfig, router, workspace_advanced, AppState};
use axum::{
    body::{to_bytes, Body},
    http::Request,
};
use serde_json::json;
use std::collections::HashMap;
use tower::ServiceExt;

fn fixture() -> (tempfile::TempDir, AppState) {
    let t = tempfile::tempdir().unwrap();
    let c = RuntimeConfig::create_default(t.path().join("config.toml"), t.path()).unwrap();
    (t, AppState::open(c).unwrap())
}

async fn http_json(
    s: &AppState,
    method: &str,
    path: &str,
    body: serde_json::Value,
) -> (u16, serde_json::Value) {
    let r = router(s.clone())
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
    let status = r.status().as_u16();
    let bytes = to_bytes(r.into_body(), 4 * 1024 * 1024).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(json!({"raw":String::from_utf8_lossy(&bytes)})),
    )
}
fn assert_shape(expected: &serde_json::Value, actual: &serde_json::Value, path: &str) {
    if let (Some(e), Some(a)) = (expected.as_object(), actual.as_object()) {
        for k in e.keys() {
            assert!(a.contains_key(k), "missing key {} at {}", k, path);
            assert_shape(&e[k], &a[k], &format!("{}/{}", path, k));
        }
    } else if let (Some(e), Some(a)) = (expected.as_array(), actual.as_array()) {
        if let (Some(first), Some(afirst)) = (e.first(), a.first()) {
            assert_shape(first, afirst, path);
        }
    }
}

#[tokio::test]
async fn python_golden_contracts_match_native_metadata_and_shapes() {
    let (_t, s) = fixture();
    let contracts: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/python-contracts.json")).unwrap();
    for case in contracts.as_array().unwrap().iter().filter(|x| {
        matches!(
            x["path"].as_str(),
            Some("/api/workspace/bootstrap")
                | Some("/api/projects")
                | Some("/api/world-bible")
                | Some("/api/home")
                | Some("/api/commands")
        )
    }) {
        let path = case["path"].as_str().unwrap();
        let query = if path == "/api/home" {
            "?project_id=PROJ-WORLD-BIBLE"
        } else {
            ""
        };
        let (status, actual) = http_json(
            &s,
            case["method"].as_str().unwrap(),
            &format!("{}{}", path, query),
            case["body"].clone(),
        )
        .await;
        assert_eq!(status, 200, "{}", path);
        assert_shape(&case["response"], &actual, path);
    }
    let (_status, bootstrap) = http_json(&s, "GET", "/api/workspace/bootstrap", json!({})).await;
    assert_eq!(
        bootstrap["world_bible"]["default_world_id"],
        "WORLD-BIBLE-MAIN"
    );
    assert_eq!(
        bootstrap["world_bible"]["default_branch_id"],
        "BRANCH-BIBLE-MAIN"
    );
    assert_eq!(bootstrap["active"]["world"]["id"], "WORLD-BIBLE-MAIN");
    assert_eq!(bootstrap["active"]["world"]["name"], "Main");
    assert_eq!(bootstrap["active"]["branch"]["id"], "BRANCH-BIBLE-MAIN");
    assert_eq!(bootstrap["active"]["branch"]["name"], "Main");
    for status in [
        "canon",
        "draft",
        "what_if",
        "deprecated",
        "provisional",
        "retconned",
    ] {
        assert!(
            bootstrap["canon_statuses"]
                .as_array()
                .unwrap()
                .iter()
                .any(|v| v == status),
            "missing builtin canon status {status}"
        );
    }
    let (_status, commands) = http_json(&s, "GET", "/api/commands", json!({})).await;
    assert!(commands["commands"]
        .as_array()
        .map(|x| !x.is_empty())
        .unwrap_or(false));
}

#[tokio::test]
async fn populated_home_tree_and_mentions_expose_seeded_workspace_state() {
    let (_t, s) = fixture();
    s.store
        .insert("projects", json!({"id":"p","name":"P","slug":"p"}))
        .unwrap();
    s.store
        .insert(
            "workspace_documents",
            json!({"id":"d1","project_id":"p","title":"Arrival Scene","content":"arrival"}),
        )
        .unwrap();
    let (tree_status, tree) = http_json(&s, "GET", "/api/projects/p/tree", json!({})).await;
    assert_eq!(tree_status, 200);
    assert!(tree["documents"]
        .as_array()
        .unwrap()
        .iter()
        .any(|d| d["id"] == "d1"));
    let (mentions_status, mentions) =
        http_json(&s, "GET", "/api/mentions?project_id=p&q=arrival", json!({})).await;
    assert_eq!(mentions_status, 200);
    assert!(mentions["results"]
        .as_array()
        .unwrap()
        .iter()
        .any(|d| d["id"] == "d1"));
    let (home_status, home) = http_json(&s, "GET", "/api/home?project_id=p", json!({})).await;
    assert_eq!(home_status, 200);
    assert!(home["recent_documents"]
        .as_array()
        .unwrap()
        .iter()
        .any(|d| d["id"] == "d1"));
}

fn route_path(raw: &str) -> String {
    raw.replace("{project_id}", "p")
        .replace("{world_id}", "w")
        .replace("{branch_id}", "b")
        .replace("{left_world_id}", "w")
        .replace("{right_world_id}", "w")
        .replace("{left_branch_id}", "b")
        .replace("{right_branch_id}", "b")
        .replace("{left_variant_id}", "v1")
        .replace("{right_variant_id}", "v1")
        .replace("{resource_type}", "entity_variant")
        .replace("{resource_id}", "v1")
        .replace("{document_id}", "d1")
        .replace("{scene_document_id}", "d1")
        .replace("{variant_id}", "v1")
        .replace("{family_id}", "f1")
        .replace("{relationship_id}", "r1")
        .replace("{tag_id}", "tag1")
        .replace("{template_id}", "tpl1")
        .replace("{snapshot_id}", "snap1")
        .replace("{revision_id}", "rev1")
        .replace("{change_id}", "stage1")
        .replace("{conflict_id}", "conf1")
}

#[tokio::test]
async fn every_workspace_legacy_get_is_recognized_by_native_router() {
    let (_t, s) = fixture();
    s.store
        .insert("projects", json!({"id":"p","name":"P","slug":"p"}))
        .unwrap();
    s.store
        .insert(
            "worlds",
            json!({"id":"w","project_id":"p","name":"W","slug":"w"}),
        )
        .unwrap();
    s.store.insert("world_branches",json!({"id":"b","world_id":"w","name":"Main","slug":"main","kind":"main","canon_status":"canon"})).unwrap();
    s.store
        .insert(
            "entity_families",
            json!({"id":"f1","project_id":"p","entity_type":"character","name":"A","slug":"a"}),
        )
        .unwrap();
    s.store
        .insert(
            "entity_variants",
            json!({"id":"v1","family_id":"f1","world_id":"w","display_name":"A"}),
        )
        .unwrap();
    s.store
        .insert(
            "workspace_documents",
            json!({"id":"d1","project_id":"p","title":"D","content":""}),
        )
        .unwrap();
    s.store.insert("relationships",json!({"id":"r1","world_id":"w","subject_variant_id":"v1","object_variant_id":"v1","relation_type":"self"})).unwrap();
    let routes: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/legacy-routes.json")).unwrap();
    let owned = [
        "backlinks",
        "branches",
        "context",
        "documents",
        "entities",
        "facts",
        "folders",
        "mentions",
        "overlays",
        "projects",
        "relationships",
        "revisions",
        "scenes",
        "snapshots",
        "staged-changes",
        "tags",
        "templates",
        "timeline",
        "world-bible",
        "workspace",
        "worlds",
    ];
    let mut failures = Vec::new();
    for item in routes
        .as_array()
        .unwrap()
        .iter()
        .filter(|x| x["method"] == "GET")
    {
        let raw = item["path"].as_str().unwrap();
        let head = raw.trim_start_matches("/api/").split('/').next().unwrap();
        if !owned.contains(&head) {
            continue;
        }
        let mut path = route_path(raw);
        if path == "/api/projects/p/manifest" {
            path.push_str("?project_id=p");
        } else if path.starts_with("/api/worlds")
            || path.starts_with("/api/branches")
            || path.starts_with("/api/snapshots")
            || path.starts_with("/api/timeline")
        {
            path.push_str(if path.contains('?') {
                "&world_id=w"
            } else {
                "?world_id=w"
            });
        } else if path == "/api/mentions" {
            path.push_str("?project_id=p");
        }
        let response = router(s.clone())
            .oneshot(
                Request::builder()
                    .method("GET")
                    .uri(&path)
                    .header("host", "127.0.0.1")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        let status = response.status().as_u16();
        let _ = to_bytes(response.into_body(), 1024 * 1024).await.unwrap();
        if status == 404 || status == 500 || status == 501 {
            failures.push(format!("{} {}", status, raw));
        }
    }
    assert!(
        failures.is_empty(),
        "unrecognized workspace GET routes: {:?}",
        failures
    );
}

#[tokio::test]
async fn all_legacy_routes_are_native_recognized_without_server_errors() {
    let (_t, s) = fixture();
    s.store
        .insert("projects", json!({"id":"p","name":"P","slug":"p"}))
        .unwrap();
    s.store
        .insert(
            "worlds",
            json!({"id":"w","project_id":"p","name":"W","slug":"w"}),
        )
        .unwrap();
    s.store.insert("world_branches",json!({"id":"b","world_id":"w","name":"Main","slug":"main","kind":"main","canon_status":"canon"})).unwrap();
    let routes: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/legacy-routes.json")).unwrap();
    let mut failures = Vec::new();
    for item in routes.as_array().unwrap() {
        let raw = item["path"].as_str().unwrap();
        let method = item["method"].as_str().unwrap();
        let mut path = route_path(raw);
        if path.starts_with("/api/worlds")
            || path.starts_with("/api/branches")
            || path.starts_with("/api/snapshots")
            || path.starts_with("/api/timeline")
        {
            path.push_str(if path.contains('?') {
                "&world_id=w"
            } else {
                "?world_id=w"
            });
        }
        let response = router(s.clone())
            .oneshot(
                Request::builder()
                    .method(method)
                    .uri(&path)
                    .header("host", "127.0.0.1")
                    .header("content-type", "application/json")
                    .body(Body::from("{}"))
                    .unwrap(),
            )
            .await
            .unwrap();
        let status = response.status().as_u16();
        let bytes = to_bytes(response.into_body(), 1024 * 1024).await.unwrap();
        let payload: serde_json::Value = serde_json::from_slice(&bytes).unwrap_or_else(|_| {
            json!({"detail": String::from_utf8_lossy(&bytes).chars().take(300).collect::<String>()})
        });
        let detail = payload
            .get("detail")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("");
        let detail_lower = detail.to_ascii_lowercase();
        if status >= 500
            || detail_lower.contains("workspace route not implemented")
            || detail_lower.contains("unknown api route")
            || detail_lower.contains("unsupported")
        {
            failures.push(format!("{} {} {} {}", status, method, raw, detail));
        }
    }
    assert!(
        failures.is_empty(),
        "legacy routes yielding server/unimplemented errors: {:?}",
        failures
    );
    let response = router(s)
        .oneshot(
            Request::builder()
                .method("GET")
                .uri("/api/__definitely_unknown__")
                .header("host", "127.0.0.1")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status().as_u16(), 404);
}
#[test]
fn legacy_inventory_is_present_and_stateful_wrappers_are_owned() {
    let routes: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/legacy-routes.json")).unwrap();
    assert_eq!(routes.as_array().unwrap().len(), 213);
    let (_t, s) = fixture();
    s.store
        .insert("projects", json!({"id":"p","name":"P","slug":"p"}))
        .unwrap();
    s.store
        .insert(
            "worlds",
            json!({"id":"w","project_id":"p","name":"W","slug":"w"}),
        )
        .unwrap();
    let q = HashMap::new();
    let manifest =
        workspace_advanced::handle(&s, "GET", &["projects", "p", "manifest"], &q, &json!({}))
            .unwrap()
            .unwrap();
    assert!(
        manifest.get("project").is_some()
            && manifest.get("refs").is_some()
            && manifest.get("overlays").is_some()
    );
    let snapshots =
        workspace_advanced::handle(&s, "GET", &["snapshots"], &q, &json!({"world_id":"w"}))
            .unwrap()
            .unwrap();
    assert!(snapshots.get("snapshots").is_some());
    let recipes = workspace_advanced::handle(&s, "GET", &["context", "recipes"], &q, &json!({}))
        .unwrap()
        .unwrap();
    assert!(recipes.get("recipes").is_some());
}
