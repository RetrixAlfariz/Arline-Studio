//! The native dispatcher tries module handlers in order, so a route claimed by
//! two modules would be silently shadowed. This pins one owner per legacy route
//! for the synchronous SQLite modules (no network or process side effects).
use arline_runtime::{
    canon_workflows, config::RuntimeConfig, foundation_extended, workspace, workspace_advanced,
    AppState,
};
use serde_json::json;
use std::collections::HashMap;

fn route_path(raw: &str) -> String {
    raw.replace("{project_id}", "p")
        .replace("{world_id}", "w")
        .replace("{branch_id}", "b")
        .replace("{variant_id}", "v1")
        .replace("{family_id}", "f1")
        .replace("{document_id}", "d1")
}

#[test]
fn every_legacy_route_has_at_most_one_sync_owner() {
    let routes: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/legacy-routes.json")).unwrap();
    let mut conflicts = Vec::new();
    for item in routes.as_array().unwrap() {
        let method = item["method"].as_str().unwrap();
        let path = route_path(item["path"].as_str().unwrap());
        let api: Vec<&str> = path
            .trim_start_matches("/api/")
            .split('/')
            .filter(|part| !part.is_empty())
            .collect();
        // Fresh store per route so one module's mutation cannot hide another's claim.
        let t = tempfile::tempdir().unwrap();
        let c = RuntimeConfig::create_default(t.path().join("config.toml"), t.path()).unwrap();
        let s = AppState::open(c).unwrap();
        let (q, b) = (HashMap::new(), json!({"world_id":"w"}));
        let advanced = workspace_advanced::handle(&s, method, &api, &q, &b).is_some();
        let mut owners = Vec::new();
        if foundation_extended::handle(&s, method, &api, &q, &b).is_some() {
            owners.push("foundation_extended");
        }
        if canon_workflows::handle(&s, method, &api, &q, &b).is_some() {
            owners.push("canon_workflows");
        }
        if advanced {
            owners.push("workspace_advanced");
        }
        // workspace::handle delegates to workspace_advanced first by design.
        if !advanced && workspace::handle(&s, method, &api, &q, &b).is_some() {
            owners.push("workspace");
        }
        if owners.len() > 1 {
            conflicts.push(format!("{method} {path}: {owners:?}"));
        }
    }
    assert!(conflicts.is_empty(), "shadowed routes:\n{}", conflicts.join("\n"));
}
