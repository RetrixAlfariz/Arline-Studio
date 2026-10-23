use arline_runtime::{
    config::RuntimeConfig,
    foundation::memory::{spatial, temporal},
    AppState,
};
use serde_json::json;

fn fixture() -> (tempfile::TempDir, AppState) {
    let temp = tempfile::tempdir().unwrap();
    let config =
        RuntimeConfig::create_default(temp.path().join("config.toml"), temp.path()).unwrap();
    (temp, AppState::open(config).unwrap())
}

#[test]
fn spatial_neighborhood_is_depth_limited_and_branch_aware() {
    let (_temp, state) = fixture();
    let _ = spatial::neighborhood(&state.store, "w", None, "entity", "a", 0).unwrap();
    let now = "2026-01-01T00:00:00Z";
    state.store.connection().unwrap().execute("INSERT INTO spatial_edges(id,world_id,branch_id,subject_type,subject_id,relation,object_type,object_id,structural,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",rusqlite::params!["e1","w",Option::<String>::None,"entity","a","inside","location","room",1,"accepted",now,now]).unwrap();
    state.store.connection().unwrap().execute("INSERT INTO spatial_edges(id,world_id,branch_id,subject_type,subject_id,relation,object_type,object_id,structural,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",rusqlite::params!["e2","w",Option::<String>::None,"location","room","inside","location","house",1,"accepted",now,now]).unwrap();
    let one = spatial::neighborhood(&state.store, "w", None, "entity", "a", 1).unwrap();
    assert_eq!(one["edges"].as_array().unwrap().len(), 1);
    let two = spatial::neighborhood(&state.store, "w", None, "entity", "a", 2).unwrap();
    assert_eq!(two["edges"].as_array().unwrap().len(), 2);
    let route = spatial::path(
        &state.store,
        "w",
        None,
        "entity",
        "a",
        "location",
        "house",
        2,
    )
    .unwrap();
    assert_eq!(route.as_array().unwrap().len(), 2);
}

#[test]
fn temporal_state_and_epistemic_queries_respect_story_intervals_and_threads() {
    let (_temp, state) = fixture();
    let _ = temporal::current_state(&state.store, "w", None, "entity", "a", None).unwrap();
    state.store.connection().unwrap().execute("INSERT INTO current_state_projection(world_id,branch_id,owner_type,owner_id,state_key,value_json,source_type,source_id,authority,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",rusqlite::params!["w",Option::<String>::None,"entity","a","mood",json!({"value":"calm"}).to_string(),"manual","s1","canon","2026-01-01"]).unwrap();
    state.store.connection().unwrap().execute("INSERT INTO state_intervals(id,world_id,branch_id,owner_type,owner_id,state_key,value_json,story_order_from,story_order_to,source_type,authority,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",rusqlite::params!["i1","w",Option::<String>::None,"entity","a","mood",json!("calm").to_string(),0.0,5.0,"manual","canon","accepted","2026-01-01"]).unwrap();
    state.store.connection().unwrap().execute("INSERT INTO state_intervals(id,world_id,branch_id,owner_type,owner_id,state_key,value_json,story_order_from,story_order_to,source_type,authority,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",rusqlite::params!["i2","w",Option::<String>::None,"entity","a","mood",json!("alert").to_string(),5.0,10.0,"manual","canon","accepted","2026-01-02"]).unwrap();
    state.store.connection().unwrap().execute("INSERT INTO epistemic_intervals(id,world_id,branch_id,character_variant_id,topic_type,topic_id,state_type,value_json,story_order_from,story_order_to,source_type,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",rusqlite::params!["ep1","w",Option::<String>::None,"v1","entity","a","knows",json!(true).to_string(),0.0,3.0,"manual","accepted","2026-01-01"]).unwrap();
    state.store.connection().unwrap().execute("INSERT INTO story_threads(id,project_id,world_id,branch_id,thread_type,title,description,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",rusqlite::params!["t1",Option::<String>::None,"w",Option::<String>::None,"plot","Open thread","","open","2026-01-01","2026-01-01"]).unwrap();
    let current =
        temporal::current_state(&state.store, "w", None, "entity", "a", Some("mood")).unwrap();
    assert_eq!(
        current.as_array().unwrap()[0]["value"],
        json!({"value":"calm"})
    );
    let historical = temporal::state_at(&state.store, "w", None, "entity", "a", Some(7.0)).unwrap();
    assert_eq!(historical.as_array().unwrap()[0]["value"], "alert");
    let past = temporal::state_at(&state.store, "w", None, "entity", "a", Some(2.0)).unwrap();
    assert_eq!(past.as_array().unwrap()[0]["value"], "calm");
    let epistemic = temporal::epistemic(
        &state.store,
        "w",
        None,
        "v1",
        Some("entity"),
        Some("a"),
        Some(2.0),
    )
    .unwrap();
    assert_eq!(epistemic.as_array().unwrap().len(), 1);
    assert_eq!(
        temporal::threads(&state.store, "w", None, Some("open"), None, None)
            .unwrap()
            .as_array()
            .unwrap()
            .len(),
        1
    );
}

#[test]
fn refresh_world_replays_canon_facts_and_timeline_patches() {
    let (_temp, state) = fixture();
    let _ = temporal::current_state(&state.store, "WORLD-BIBLE-MAIN", None, "entity", "v1", None)
        .unwrap();
    state.store.connection().unwrap().execute("INSERT INTO canon_facts(id,project_id,world_id,branch_id,owner_type,owner_id,path,value_json,status,authority,source_type,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", rusqlite::params!["f1","PROJ-WORLD-BIBLE","WORLD-BIBLE-MAIN",Option::<String>::None,"entity_variant","v1","mood",json!("calm").to_string(),"canon","manual","test","2026-01-01","2026-01-01"]).unwrap();
    state.store.connection().unwrap().execute("INSERT INTO timeline_events(id,world_id,branch_id,owner_type,owner_id,time_label,order_key,event_type,summary,state_patch_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", rusqlite::params!["e1","WORLD-BIBLE-MAIN",Option::<String>::None,"entity_variant","v1","later",2.0,"change","became alert",json!({"mood":"alert"}).to_string(),"canon","2026-01-02","2026-01-02"]).unwrap();
    let report = temporal::refresh_world(&state.store, "WORLD-BIBLE-MAIN", None).unwrap();
    assert_eq!(report["state_count"], 1);
    let current = temporal::current_state(
        &state.store,
        "WORLD-BIBLE-MAIN",
        None,
        "entity_variant",
        "v1",
        Some("mood"),
    )
    .unwrap();
    assert_eq!(current.as_array().unwrap()[0]["value"], "calm");
    temporal::refresh_world(&state.store, "WORLD-BIBLE-MAIN", None).unwrap();
    assert_eq!(
        state
            .store
            .query(
                "SELECT COUNT(*) AS n FROM current_state_projection WHERE world_id=? AND owner_type=? AND owner_id=?",
                &[&"WORLD-BIBLE-MAIN", &"entity_variant", &"v1"]
            )
            .unwrap()[0]["n"],
        1
    );
    state
        .store
        .connection()
        .unwrap()
        .execute("DELETE FROM canon_facts WHERE id='f1'", [])
        .unwrap();
    temporal::refresh_world(&state.store, "WORLD-BIBLE-MAIN", None).unwrap();
    let after_fact_delete = temporal::current_state(
        &state.store,
        "WORLD-BIBLE-MAIN",
        None,
        "entity_variant",
        "v1",
        Some("mood"),
    )
    .unwrap();
    assert_eq!(after_fact_delete.as_array().unwrap()[0]["value"], "alert");
    state
        .store
        .connection()
        .unwrap()
        .execute("DELETE FROM timeline_events WHERE id='e1'", [])
        .unwrap();
    temporal::refresh_world(&state.store, "WORLD-BIBLE-MAIN", None).unwrap();
    assert!(temporal::current_state(
        &state.store,
        "WORLD-BIBLE-MAIN",
        None,
        "entity_variant",
        "v1",
        None
    )
    .unwrap()
    .as_array()
    .unwrap()
    .is_empty());
}

#[test]
fn refresh_world_preserves_manual_state_conflicts() {
    let (_temp, state) = fixture();
    let _ = temporal::current_state(&state.store, "WORLD-BIBLE-MAIN", None, "entity", "v1", None)
        .unwrap();
    state.store.connection().unwrap().execute("INSERT INTO current_state_projection(world_id,branch_id,owner_type,owner_id,state_key,value_json,source_type,source_id,authority,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",rusqlite::params!["WORLD-BIBLE-MAIN",Option::<String>::None,"entity","v1","mood",json!("manual").to_string(),"manual","m1","user_accepted_world_canon","2026-01-01"]).unwrap();
    state.store.connection().unwrap().execute("INSERT INTO state_intervals(id,world_id,branch_id,owner_type,owner_id,state_key,value_json,story_order_from,source_type,authority,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",rusqlite::params!["manual-i","WORLD-BIBLE-MAIN",Option::<String>::None,"entity","v1","mood",json!("manual").to_string(),0.0,"manual","user_accepted_world_canon","accepted","2026-01-01"]).unwrap();
    state.store.connection().unwrap().execute("INSERT INTO timeline_events(id,world_id,branch_id,owner_type,owner_id,time_label,order_key,event_type,summary,state_patch_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",rusqlite::params!["e-manual","WORLD-BIBLE-MAIN",Option::<String>::None,"entity","v1","later",2.0,"change","ignored",json!({"mood":"timeline"}).to_string(),"accepted","2026-01-02","2026-01-02"]).unwrap();
    let report = temporal::refresh_world(&state.store, "WORLD-BIBLE-MAIN", None).unwrap();
    assert_eq!(report["state_count"], 1);
    let current = temporal::current_state(
        &state.store,
        "WORLD-BIBLE-MAIN",
        None,
        "entity",
        "v1",
        Some("mood"),
    )
    .unwrap();
    assert_eq!(current.as_array().unwrap()[0]["value"], "manual");
    assert_eq!(
        state
            .store
            .query(
                "SELECT COUNT(*) AS n FROM state_intervals WHERE source_type='timeline_event'",
                &[]
            )
            .unwrap()[0]["n"],
        0
    );
}
