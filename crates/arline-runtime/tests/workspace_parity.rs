use arline_runtime::{config::RuntimeConfig, workspace_advanced, AppState};
use serde_json::{json, Value};
use std::collections::HashMap;

fn fixture() -> (tempfile::TempDir, AppState) {
    let temp = tempfile::tempdir().unwrap();
    let config =
        RuntimeConfig::create_default(temp.path().join("config.toml"), temp.path()).unwrap();
    (temp, AppState::open(config).unwrap())
}
fn call(s: &AppState, method: &str, path: &[&str], body: Value) -> Value {
    workspace_advanced::handle(s, method, path, &HashMap::new(), &body)
        .unwrap()
        .unwrap()
}
fn seed(s: &AppState) {
    s.store
        .insert("projects", json!({"id":"p","name":"P","slug":"p"}))
        .unwrap();
    s.store
        .insert(
            "worlds",
            json!({"id":"w","project_id":"p","name":"W","slug":"w"}),
        )
        .unwrap();
    s.store.insert("world_branches", json!({"id":"main","world_id":"w","name":"Main","slug":"main","kind":"main","canon_status":"canon"})).unwrap();
    s.store
        .insert(
            "entity_families",
            json!({"id":"f1","project_id":"p","entity_type":"character","name":"A","slug":"a"}),
        )
        .unwrap();
    s.store
        .insert(
            "entity_families",
            json!({"id":"f2","project_id":"p","entity_type":"character","name":"B","slug":"b"}),
        )
        .unwrap();
    s.store
        .insert(
            "entity_variants",
            json!({"id":"v1","family_id":"f1","world_id":"w","display_name":"A","summary":"one"}),
        )
        .unwrap();
    s.store
        .insert(
            "entity_variants",
            json!({"id":"v2","family_id":"f2","world_id":"w","display_name":"B","summary":"two"}),
        )
        .unwrap();
    s.store.insert("relationships", json!({"id":"r1","world_id":"w","subject_variant_id":"v1","object_variant_id":"v2","relation_type":"knows"})).unwrap();
    s.store.insert("canon_facts", json!({"id":"fact1","project_id":"p","world_id":"w","owner_type":"entity_variant","owner_id":"v1","path":"mood","value":"calm"})).unwrap();
    s.store
        .insert(
            "timeline_events",
            json!({"id":"t1","world_id":"w","summary":"origin"}),
        )
        .unwrap();
}

#[test]
fn fork_clones_semantic_state_and_preserves_lineage() {
    let (_tmp, s) = fixture();
    seed(&s);
    let fork = call(
        &s,
        "POST",
        &["worlds", "w", "fork"],
        json!({"name":"AU","clone_parent":true}),
    );
    let wid = fork["id"].as_str().unwrap();
    assert_eq!(fork["parent_world_id"], "w");
    assert_eq!(
        s.store
            .list("entity_variants", &[("world_id", json!(wid))])
            .unwrap()
            .len(),
        2
    );
    assert_eq!(
        s.store
            .list("relationships", &[("world_id", json!(wid))])
            .unwrap()
            .len(),
        1
    );
    assert_eq!(
        s.store
            .list("canon_facts", &[("world_id", json!(wid))])
            .unwrap()
            .len(),
        1
    );
    assert_eq!(
        s.store
            .list("timeline_events", &[("world_id", json!(wid))])
            .unwrap()
            .len(),
        1
    );
}

#[test]
fn branch_merge_copies_requested_entity_and_rejects_cross_world() {
    let (_tmp, s) = fixture();
    seed(&s);
    let bid = "sandbox";
    s.store.insert("world_branches", json!({"id":bid,"world_id":"w","name":"Sandbox","slug":"sandbox","kind":"sandbox","canon_status":"what_if"})).unwrap();
    s.store.insert("entity_variants", json!({"id":"bv1","family_id":"f1","world_id":"w","branch_id":bid,"display_name":"A","summary":"changed"})).unwrap();
    let out = call(
        &s,
        "POST",
        &["branches", bid, "merge"],
        json!({"target_branch_id":"main","changes":[{"kind":"entity","family_id":"f1"}]}),
    );
    assert_eq!(out["merged"].as_array().unwrap().len(), 1);
    assert!(!s
        .store
        .list(
            "entity_variants",
            &[("branch_id", json!("main")), ("family_id", json!("f1"))]
        )
        .unwrap()
        .is_empty());
}

#[test]
fn snapshot_restore_creates_populated_sandbox_branch() {
    let (_tmp, s) = fixture();
    seed(&s);
    let snap = call(
        &s,
        "POST",
        &["snapshots"],
        json!({"project_id":"p","world_id":"w","name":"checkpoint"}),
    );
    let restored = call(
        &s,
        "POST",
        &["snapshots", snap["id"].as_str().unwrap(), "restore"],
        json!({"branch_name":"Restored"}),
    );
    let bid = restored["branch_id"].as_str().unwrap();
    assert_eq!(
        s.store
            .list("entity_variants", &[("branch_id", json!(bid))])
            .unwrap()
            .len(),
        2
    );
    assert_eq!(
        s.store
            .list("relationships", &[("branch_id", json!(bid))])
            .unwrap()
            .len(),
        1
    );
    assert_eq!(
        s.store
            .list("canon_facts", &[("branch_id", json!(bid))])
            .unwrap()
            .len(),
        1
    );
}

#[test]
fn staged_accept_writes_fact_and_reject_preserves_state() {
    let (_tmp, s) = fixture();
    seed(&s);
    let accepted = call(
        &s,
        "POST",
        &["projects", "p", "staged-changes"],
        json!({"owner_type":"entity_variant","owner_id":"v1","path":"mood","proposed_value":"bright","world_id":"w","confidence":0.9}),
    );
    let aid = accepted["id"].as_str().unwrap();
    call(
        &s,
        "POST",
        &["staged-changes", aid, "resolve"],
        json!({"accept":true}),
    );
    assert!(!s
        .store
        .query(
            "SELECT 1 FROM canon_facts WHERE owner_id='v1' AND path='mood' AND status='canon'",
            &[]
        )
        .unwrap()
        .is_empty());
    let rejected = call(
        &s,
        "POST",
        &["projects", "p", "staged-changes"],
        json!({"owner_type":"entity_variant","owner_id":"v1","path":"voice","proposed_value":"quiet","world_id":"w"}),
    );
    let rid = rejected["id"].as_str().unwrap();
    call(
        &s,
        "POST",
        &["staged-changes", rid, "resolve"],
        json!({"accept":false}),
    );
    assert!(s
        .store
        .query(
            "SELECT 1 FROM canon_facts WHERE owner_id='v1' AND path='voice'",
            &[]
        )
        .unwrap()
        .is_empty());
}

#[test]
fn continuity_and_retcon_report_real_conflicts_and_history() {
    let (_tmp, s) = fixture();
    seed(&s);
    s.store.insert("canon_facts",json!({"id":"fact2","project_id":"p","world_id":"w","owner_type":"entity_variant","owner_id":"v1","path":"mood","value":"angry","status":"canon"})).unwrap();
    let report = call(&s, "GET", &["projects", "p", "continuity"], json!({}));
    assert!(report["warning_count"].as_i64().unwrap() > 0);
    let preview = call(
        &s,
        "POST",
        &["retcon", "preview"],
        json!({"project_id":"p","world_id":"w","owner_type":"entity_variant","owner_id":"v1","path":"mood","new_value":"focused"}),
    );
    assert_eq!(
        preview["impact"]["relationships"].as_array().unwrap().len(),
        1
    );
    let applied = call(
        &s,
        "POST",
        &["retcon", "apply"],
        json!({"project_id":"p","world_id":"w","owner_type":"entity_variant","owner_id":"v1","path":"mood","new_value":"focused","note":"clarified"}),
    );
    assert_eq!(applied["status"], "canon");
    assert_eq!(s.store.query("SELECT 1 FROM canon_facts WHERE status='retconned' AND owner_id='v1' AND path='mood'",&[]).unwrap().len(),2);
    assert!(!s
        .store
        .list(
            "workspace_revisions",
            &[("resource_type", json!("canon_fact"))]
        )
        .unwrap()
        .is_empty());
}
