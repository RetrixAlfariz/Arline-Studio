use arline_runtime::profile::{normalize, personalization};
use serde_json::{json, Value};
#[test]
fn default_profile_matches_live_python_fixture() {
    let fixtures: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/python-contracts.json")).unwrap();
    let golden = fixtures
        .iter()
        .find(|f| f["path"] == "/api/user-profile")
        .unwrap();
    assert_eq!(normalize(&json!({})), golden["response"]);
}
#[test]
fn names_are_ordered_and_private_fields_stay_private() {
    let raw = json!({"display_name":"Vian","preferred_names":[{"value":"Revian","context":"formal","primary":true},{"value":"Vian","context":"casual"}],"personal_details":{"address":{"value":"secret","visibility":"private"},"motivation":{"value":"writes fiction","visibility":"collaboration"},"persona":{"value":"Captain","visibility":"story_presence"}},"memory_policy":{"categories":{"story_presence":{"enabled":true}}}});
    let profile = normalize(&raw);
    assert_eq!(profile["display_name"], "Revian");
    assert_eq!(
        profile["personal_details"]["preferred_name"]["visibility"],
        "collaboration"
    );
    let lab = personalization(&raw, "story_lab", "");
    assert_eq!(lab["preferred_name"], "Vian");
    assert!(lab["personal_details"]["address"].is_null());
    assert!(lab["personal_details"]["persona"].is_null());
    assert_eq!(lab["personal_details"]["motivation"], "writes fiction");
    let interactive = personalization(&raw, "interactive", "");
    assert_eq!(interactive["personal_details"]["persona"], "Captain");
    let disabled = personalization(
        &json!({"memory_policy":{"enabled":false},"about":"secret","collaboration":{"partner_name":"Opheline"}}),
        "story_lab",
        "",
    );
    assert_eq!(
        disabled,
        json!({"memory_enabled":false,"learn_from_chat":false,"partner_name":"Opheline"})
    );
}
#[test]
fn legacy_memory_booleans_and_invalid_retention_are_normalized() {
    let p = normalize(
        &json!({"memory_policy":{"creative_preferences":false,"reusable_personas":true,"categories":{"about_you":{"retention_days":-5},"story_presence":{"retention_days":"bad"}}}}),
    );
    assert_eq!(
        p["memory_policy"]["categories"]["collaboration_preferences"]["enabled"],
        false
    );
    assert_eq!(
        p["memory_policy"]["categories"]["story_presence"]["enabled"],
        true
    );
    assert_eq!(
        p["memory_policy"]["categories"]["about_you"]["retention_days"],
        0
    );
    assert_eq!(
        p["memory_policy"]["categories"]["story_presence"]["retention_days"],
        180
    );
}
