use arline_runtime::{config::RuntimeConfig, foundation::memory::discovery, AppState};
use serde_json::json;
use std::collections::HashMap;
use tempfile::TempDir;

fn state() -> (TempDir, AppState) {
    let dir = tempfile::tempdir().unwrap();
    let config =
        RuntimeConfig::create_default(dir.path().join("runtime.toml"), dir.path()).unwrap();
    (dir, AppState::open(config).unwrap())
}

fn call(
    s: &AppState,
    method: &str,
    path: &[&str],
    query: &[(&str, &str)],
    body: serde_json::Value,
) -> serde_json::Value {
    let q = query
        .iter()
        .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
        .collect::<HashMap<_, _>>();
    discovery::handle(s, method, path, &q, &body)
        .unwrap()
        .unwrap()
}

fn seed_turn(s: &AppState) {
    s.store
        .insert(
            "projects",
            json!({"id":"P1","name":"Discovery","slug":"discovery"}),
        )
        .unwrap();
    s.store
        .insert(
            "worlds",
            json!({"id":"W1","project_id":"P1","name":"World","slug":"world"}),
        )
        .unwrap();
    s.store.insert("sessions", json!({"id":"S1","title":"Discovery","created_at":"2026-01-01","updated_at":"2026-01-01","project_id":"P1","world_id":"W1"})).unwrap();
    s.store.insert("turns", json!({"id":"T1","session_id":"S1","user_prompt":"Mira is careful. Mira lives in Haven.","story":"","created_at":"2026-01-01","updated_at":"2026-01-01"})).unwrap();
}

#[test]
fn capture_creates_multiple_observed_propositions_without_autocanon() {
    let (_tmp, s) = state();
    seed_turn(&s);
    let report = call(
        &s,
        "POST",
        &["discoveries", "capture-turn", "T1"],
        &[("source_kind", "user_prompt")],
        json!({}),
    );
    assert!(report["propositions"].as_i64().unwrap() >= 2);
    assert_eq!(report["auto_canon"], false);
    let listed = call(&s, "GET", &["discoveries"], &[], json!({}));
    assert!(listed["items"]
        .as_array()
        .unwrap()
        .iter()
        .all(|x| x["authority_state"] == "observed"));
}

#[test]
fn explicit_decisions_edit_reset_and_dismiss_are_persisted() {
    let (_tmp, s) = state();
    seed_turn(&s);
    call(
        &s,
        "POST",
        &["discoveries", "capture-turn", "T1"],
        &[],
        json!({}),
    );
    let id = s.store.list("discovery_propositions", &[]).unwrap()[0]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    assert_eq!(
        call(
            &s,
            "POST",
            &["discoveries", &id, "edit"],
            &[],
            json!({"value":"revised"})
        )["authority_state"],
        "reviewed"
    );
    assert_eq!(
        call(
            &s,
            "POST",
            &["discoveries", &id, "canon"],
            &[],
            json!({"note":"confirmed"})
        )["authority_state"],
        "canon"
    );
    assert_eq!(
        call(&s, "POST", &["discoveries", &id, "dismiss"], &[], json!({}))["authority_state"],
        "dismissed"
    );
    assert_eq!(
        call(&s, "POST", &["discoveries", &id, "reset"], &[], json!({}))["authority_state"],
        "observed"
    );
    assert_eq!(s.store.list("discovery_decisions", &[]).unwrap().len(), 4);
}

#[test]
fn canon_materializes_entity_variant_and_source_fact() {
    let (_tmp, s) = state();
    seed_turn(&s);
    call(
        &s,
        "POST",
        &["discoveries", "capture-turn", "T1"],
        &[],
        json!({}),
    );
    let id = s
        .store
        .list("discovery_propositions", &[])
        .unwrap()
        .into_iter()
        .find(|x| x["predicate"] == "personality.descriptor")
        .unwrap()["id"]
        .as_str()
        .unwrap()
        .to_owned();
    let result = call(
        &s,
        "POST",
        &["discoveries", &id, "canon"],
        &[],
        json!({"note":"approved"}),
    );
    assert_eq!(result["authority_state"], "canon");
    assert_eq!(s.store.list("entity_families", &[]).unwrap().len(), 1);
    assert_eq!(s.store.list("entity_variants", &[]).unwrap().len(), 1);
    let facts = s.store.list("canon_facts", &[]).unwrap();
    assert_eq!(facts.len(), 1);
    assert_eq!(facts[0]["source_type"], "discovery_proposition");
    assert_eq!(facts[0]["source_id"], id);
    assert_eq!(
        s.store.get("discovery_propositions", &id).unwrap().unwrap()["materialized_resource_type"],
        "fact"
    );
}

#[test]
fn relation_canon_materializes_relationship_and_conflict_is_reviewable() {
    let (_tmp, s) = state();
    seed_turn(&s);
    let report = call(
        &s,
        "POST",
        &["discoveries", "capture-turn", "T1"],
        &[],
        json!({}),
    );
    assert!(report["propositions"].as_i64().unwrap() >= 2);
    let relation = s
        .store
        .list("discovery_propositions", &[])
        .unwrap()
        .into_iter()
        .find(|x| x["operation"] == "relation")
        .unwrap();
    let rid = relation["id"].as_str().unwrap().to_owned();
    let result = call(
        &s,
        "POST",
        &["discoveries", &rid, "canon"],
        &[],
        json!({"note":"confirmed residence"}),
    );
    assert_eq!(result["materialized"]["resource_type"], "relationship");
    assert_eq!(s.store.list("relationships", &[]).unwrap().len(), 1);
    assert_eq!(s.store.list("entity_families", &[]).unwrap().len(), 2);

    // A changed source revision invalidates the old active evidence and is
    // still reviewable through the continuity endpoint.
    s.store
        .connection()
        .unwrap()
        .execute(
            "UPDATE turns SET user_prompt=? WHERE id=?",
            rusqlite::params!["Mira is reckless.", "T1"],
        )
        .unwrap();
    call(
        &s,
        "POST",
        &["discoveries", "capture-turn", "T1"],
        &[],
        json!({}),
    );
    let conflicts = call(
        &s,
        "GET",
        &["discoveries", "continuity", "conflicts"],
        &[],
        json!({}),
    );
    assert!(!conflicts["items"].as_array().unwrap().is_empty());
}

#[test]
fn backfill_is_explicit_and_idempotent() {
    let (_tmp, s) = state();
    seed_turn(&s);
    let first = call(&s, "POST", &["discoveries", "backfill"], &[], json!({}));
    assert_eq!(first["turns"], 1);
    assert_eq!(first["auto_canon"], false);
    let count = s.store.list("discovery_instances", &[]).unwrap().len();
    let second = call(&s, "POST", &["discoveries", "backfill"], &[], json!({}));
    assert_eq!(second["turns"], 1);
    assert_eq!(
        s.store.list("discovery_instances", &[]).unwrap().len(),
        count
    );
}

#[test]
fn library_scope_is_nonempty_and_review_counts_user_notes_per_session() {
    let (_tmp, s) = state();
    seed_turn(&s);
    s.store
        .insert("turns", json!({"id":"T2","session_id":"S1","user_prompt":"Mira is careful. Mira lives in Haven.","story":"","created_at":"2026-01-02","updated_at":"2026-01-02"}))
        .unwrap();
    call(
        &s,
        "POST",
        &["discoveries", "capture-turn", "T1"],
        &[("source_kind", "user_prompt")],
        json!({}),
    );
    call(
        &s,
        "POST",
        &["discoveries", "capture-turn", "T2"],
        &[("source_kind", "user_prompt")],
        json!({}),
    );
    let library = call(
        &s,
        "GET",
        &["discoveries"],
        &[("project_id", "P1"), ("world_id", "W1")],
        json!({}),
    );
    assert!(!library["items"].as_array().unwrap().is_empty());
    assert!(library["items"]
        .as_array()
        .unwrap()
        .iter()
        .any(|x| x["knowledge_state"] == "reviewed"));

    s.store
        .insert("turns", json!({"id":"T3","session_id":"S1","user_prompt":"","story":"Mira is brave.","created_at":"2026-01-03","updated_at":"2026-01-03"}))
        .unwrap();
    let generation = call(
        &s,
        "POST",
        &["discoveries", "capture-turn", "T3"],
        &[("source_kind", "accepted_generation")],
        json!({}),
    );
    assert_eq!(generation["instances"], 1);
    let brave = s
        .store
        .list("discovery_instances", &[])
        .unwrap()
        .into_iter()
        .find(|x| x["source_turn_id"] == "T3")
        .unwrap();
    assert_eq!(brave["qualifies_review"], 0);
}

#[test]
fn session_scope_does_not_leak_to_fork_without_lineage() {
    let (_tmp, s) = state();
    seed_turn(&s);
    s.store.insert("sessions", json!({"id":"S2","title":"Other","created_at":"2026-01-02","updated_at":"2026-01-02","project_id":"P1","world_id":"W1"})).unwrap();
    s.store.insert("turns", json!({"id":"T2","session_id":"S2","user_prompt":"Nora is quiet.","story":"","created_at":"2026-01-02","updated_at":"2026-01-02"})).unwrap();
    call(
        &s,
        "POST",
        &["discoveries", "capture-turn", "T1"],
        &[],
        json!({}),
    );
    call(
        &s,
        "POST",
        &["discoveries", "capture-turn", "T2"],
        &[],
        json!({}),
    );
    let scoped = call(
        &s,
        "GET",
        &["discoveries"],
        &[("project_id", "P1"), ("session_id", "S2")],
        json!({}),
    );
    assert!(scoped["items"]
        .as_array()
        .unwrap()
        .iter()
        .all(|x| x["subject_label"] != "Mira"));
    assert!(scoped["items"]
        .as_array()
        .unwrap()
        .iter()
        .any(|x| x["subject_label"] == "Nora"));
}

#[test]
fn edited_source_revision_invalidates_old_instances_but_recapture_is_idempotent() {
    let (_tmp, s) = state();
    seed_turn(&s);
    call(
        &s,
        "POST",
        &["discoveries", "capture-turn", "T1"],
        &[],
        json!({}),
    );
    let first = s.store.list("discovery_instances", &[]).unwrap();
    assert!(!first.is_empty());
    s.store
        .connection()
        .unwrap()
        .execute(
            "UPDATE turns SET user_prompt=? WHERE id=?",
            rusqlite::params!["Mira is reckless. Mira lives in Haven.", "T1"],
        )
        .unwrap();
    call(
        &s,
        "POST",
        &["discoveries", "capture-turn", "T1"],
        &[],
        json!({}),
    );
    let changed = s.store.list("discovery_instances", &[]).unwrap();
    assert!(changed
        .iter()
        .any(|x| x["active"] == 0 && x["invalidation_reason"] == "source_revision_changed"));
    let count = changed.len();
    call(
        &s,
        "POST",
        &["discoveries", "capture-turn", "T1"],
        &[],
        json!({}),
    );
    assert_eq!(
        s.store.list("discovery_instances", &[]).unwrap().len(),
        count
    );
}
