use arline_runtime::{canon_workflows, config::RuntimeConfig, AppState};
use serde_json::{json, Value};
use std::collections::HashMap;
use tempfile::TempDir;

fn state() -> (TempDir, AppState) {
    let dir = tempfile::tempdir().unwrap();
    let config =
        RuntimeConfig::create_default(dir.path().join("runtime.toml"), dir.path()).unwrap();
    (dir, AppState::open(config).unwrap())
}

fn call(s: &AppState, method: &str, path: &[&str], body: Value) -> Value {
    canon_workflows::handle(s, method, path, &HashMap::new(), &body)
        .unwrap()
        .unwrap()
}

#[test]
fn proposal_is_pending_until_explicit_apply() {
    let (_tmp, s) = state();
    s.store
        .insert("projects", json!({"id":"P1","name":"P","slug":"p"}))
        .unwrap();
    s.store
        .insert(
            "worlds",
            json!({"id":"W1","project_id":"P1","name":"W","slug":"w"}),
        )
        .unwrap();
    let staged = call(
        &s,
        "POST",
        &["story-lab", "sheet-proposals"],
        json!({
            "project_id":"P1", "world_id":"W1", "prompt_text":"character named Mira who maps stars"
        }),
    );
    let change = staged["change"]["id"].as_str().unwrap();
    assert!(s.store.list("entity_families", &[]).unwrap().is_empty());
    assert_eq!(
        s.store.get("staged_changes", change).unwrap().unwrap()["status"],
        "pending"
    );
    let applied = call(
        &s,
        "POST",
        &["story-lab", "sheet-proposals", change, "apply"],
        json!({"action":"accept"}),
    );
    assert_eq!(applied["change"]["status"], "accepted");
    assert_eq!(s.store.list("entity_families", &[]).unwrap().len(), 1);
}

#[test]
fn merge_remaps_variants_facts_and_foundation_ownership() {
    let (_tmp, s) = state();
    s.store
        .insert("projects", json!({"id":"P1","name":"P","slug":"p"}))
        .unwrap();
    s.store
        .insert(
            "worlds",
            json!({"id":"W1","project_id":"P1","name":"W","slug":"w"}),
        )
        .unwrap();
    s.store.insert("entity_families", json!({"id":"F1","project_id":"P1","entity_type":"character","name":"Old","slug":"old"})).unwrap();
    s.store.insert("entity_families", json!({"id":"F2","project_id":"P1","entity_type":"character","name":"New","slug":"new"})).unwrap();
    s.store
        .insert(
            "entity_variants",
            json!({"id":"V1","family_id":"F1","world_id":"W1","display_name":"Old","summary":""}),
        )
        .unwrap();
    s.store
        .insert(
            "entity_variants",
            json!({"id":"V2","family_id":"F2","world_id":"W1","display_name":"New","summary":""}),
        )
        .unwrap();
    s.store.insert("relationships", json!({"id":"R1","world_id":"W1","subject_variant_id":"V1","object_variant_id":"V2","relation_type":"knows"})).unwrap();
    s.store.insert("canon_facts", json!({"id":"CF1","project_id":"P1","world_id":"W1","owner_type":"entity_variant","owner_id":"V1","path":"x","value":true})).unwrap();
    s.store.insert("resource_aliases", json!({"id":"A1","resource_type":"entity_family","resource_id":"F1","alias":"Old","normalized_alias":"old"})).unwrap();
    s.store.insert("memory_chunks", json!({"id":"M1","source_type":"entity_family","source_id":"F1","text":"old","checksum":"x"})).unwrap();
    let out = call(
        &s,
        "POST",
        &["library", "entity-merge"],
        json!({"source_family_id":"F1","target_family_id":"F2"}),
    );
    assert_eq!(out["id"], "F2");
    assert!(s.store.get("entity_families", "F1").unwrap().is_none());
    assert_eq!(
        s.store.get("relationships", "R1").unwrap().unwrap()["subject_variant_id"],
        "V2"
    );
    assert_eq!(
        s.store.get("canon_facts", "CF1").unwrap().unwrap()["owner_id"],
        "V2"
    );
    assert_eq!(
        s.store.get("memory_chunks", "M1").unwrap().unwrap()["source_id"],
        "F2"
    );
    assert_eq!(
        s.store.get("resource_aliases", "A1").unwrap().unwrap()["resource_id"],
        "F2"
    );
}

#[test]
fn profile_and_blueprint_routes_normalize_and_preserve_privacy() {
    let (_tmp, s) = state();
    let profile = call(
        &s,
        "PUT",
        &["user-profile"],
        json!({"display_name":"Vian","personal_details":{"birth_date":{"value":"2000-01-01","visibility":"private","sensitive":true}}}),
    );
    assert_eq!(profile["display_name"], "Vian");
    assert!(profile.get("memory_policy").is_some());
    let extracted = call(
        &s,
        "POST",
        &["user-profile", "extract"],
        json!({"text":"My name is Vian. I am 180 cm"}),
    );
    assert_eq!(extracted["display_name"], "Vian");
    let bp = call(
        &s,
        "POST",
        &["conversation", "blueprint", "extract"],
        json!({"text":"I want to map stars; don't make me royalty"}),
    );
    assert!(bp["blueprint"]["wanted"]
        .as_array()
        .unwrap()
        .iter()
        .any(|v| v == "I want to map stars"));
    assert!(bp["blueprint"]["avoid"]
        .as_array()
        .unwrap()
        .iter()
        .any(|v| v == "don't make me royalty"));
}
