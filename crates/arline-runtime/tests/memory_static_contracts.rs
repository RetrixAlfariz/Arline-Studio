use arline_runtime::foundation::memory::contracts;

#[test]
fn embedded_profiles_are_complete_and_schemas_sorted() {
    let profiles = contracts::profiles().unwrap();
    assert_eq!(profiles["profiles"].as_object().unwrap().len(), 8);
    assert_eq!(
        profiles["profiles"]["story_writer"]["may_commit_canon"],
        false
    );
    assert_eq!(
        profiles["profiles"]["structure_extractor"]["output_schema_id"],
        "memory_proposals_v1"
    );
    let schemas = contracts::schemas().unwrap();
    assert_eq!(
        schemas["schemas"],
        serde_json::json!(["memory_proposals_v1", "memory_summary_v1"])
    );
    assert!(
        contracts::schema("memory_summary_v1").unwrap()["schema"]["properties"]["source_chunk_ids"]
            .is_object()
    );
    assert_eq!(
        contracts::schema("missing").unwrap_err().status,
        axum::http::StatusCode::NOT_FOUND
    );
}
