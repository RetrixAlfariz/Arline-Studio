//! Personalization normalization and projection; private profile data is never canon.
use serde_json::{json, Map, Value};
fn string(v: &Value) -> String {
    v.as_str().unwrap_or("").trim().to_owned()
}
fn flag(v: &Value, default: bool) -> bool {
    v.as_bool().unwrap_or(default)
}
fn days(v: &Value, default: i64) -> i64 {
    v.as_i64()
        .or_else(|| v.as_str().and_then(|s| s.parse().ok()))
        .unwrap_or(default)
        .max(0)
}
pub fn normalize(input: &Value) -> Value {
    let mut result = input.as_object().cloned().unwrap_or_default();
    result.insert(
        "id".into(),
        json!(input["id"].as_str().unwrap_or("default")),
    );
    result.insert("display_name".into(), json!(string(&input["display_name"])));
    result.insert("about".into(), json!(input["about"].as_str().unwrap_or("")));
    for key in [
        "personal_details",
        "creative_profile",
        "collaboration",
        "presence_defaults",
        "story_lab",
    ] {
        if !result.get(key).is_some_and(Value::is_object) {
            result.insert(key.into(), json!({}));
        }
    }
    if result
        .get("boundaries")
        .is_none_or(|v| v.as_object().is_none_or(|o| o.is_empty()))
    {
        result.insert(
            "boundaries".into(),
            json!({"prefer":[],"avoid":[],"ask_before":[]}),
        );
    }
    let policy = &input["memory_policy"];
    let mut categories = Map::new();
    for (key, enabled, scope, retention) in [
        ("collaboration_preferences", true, "private", 90),
        ("about_you", true, "private", 180),
        ("story_presence", false, "selected_stories", 180),
        ("conversation_insights", true, "private", 90),
    ] {
        let current = &policy["categories"][key];
        let legacy = match key {
            "collaboration_preferences" => flag(&policy["creative_preferences"], enabled),
            "story_presence" => flag(&policy["reusable_personas"], enabled),
            _ => enabled,
        };
        categories.insert(key.into(),json!({"enabled":flag(&current["enabled"],legacy),"scope":current["scope"].as_str().filter(|v|!v.is_empty()).unwrap_or(scope),"retention_days":days(&current["retention_days"],retention),"fields":current["fields"].as_object().cloned().unwrap_or_default()}));
    }
    let behavior = &policy["behavior"];
    let policy = json!({"schema_version":2,"enabled":flag(&policy["enabled"],true),"learn_from_chats":flag(&policy["learn_from_chats"],true),"creative_preferences":categories["collaboration_preferences"]["enabled"],"reusable_personas":categories["story_presence"]["enabled"],"categories":categories,"behavior":{"ask_before_sensitive":flag(&behavior["ask_before_sensitive"],true),"forget_inactive_days":days(&behavior["forget_inactive_days"],90),"prevent_personal_canon":flag(&behavior["prevent_personal_canon"],true)}});
    result.insert("memory_policy".into(), policy);
    let mut names = Vec::new();
    if let Some(raw) = input["preferred_names"].as_array() {
        for (index, name) in raw.iter().enumerate() {
            if !name.is_object() {
                continue;
            }
            let value = string(
                name.get("value")
                    .or_else(|| name.get("name"))
                    .unwrap_or(&Value::Null),
            );
            if value.is_empty() {
                continue;
            }
            let context = name["context"].as_str().unwrap_or("default");
            names.push(json!({"id":name["id"].as_str().map(str::to_owned).unwrap_or_else(||format!("name-{}",index+1)),"value":value,"context":if ["default","formal","casual","story_presence"].contains(&context){context}else{"default"},"primary":flag(&name["primary"],false),"pronunciation":string(&name["pronunciation"]),"language":string(&name["language"])}));
        }
    }
    if names.is_empty() {
        let preferred = string(&input["personal_details"]["preferred_name"]["value"]);
        let fallback = if preferred.is_empty() {
            string(&input["display_name"])
        } else {
            preferred
        };
        if !fallback.is_empty() {
            names.push(json!({"id":"name-1","value":fallback,"context":"default","primary":true,"pronunciation":"","language":""}));
        }
    }
    let primary = names.iter().position(|n| n["primary"] == true).unwrap_or(0);
    for (index, name) in names.iter_mut().enumerate() {
        name["primary"] = json!(index == primary);
    }
    if let Some(name) = names.get(primary) {
        result.insert("display_name".into(), name["value"].clone());
        let details = result
            .get_mut("personal_details")
            .unwrap()
            .as_object_mut()
            .unwrap();
        let mut preferred = details
            .get("preferred_name")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        preferred.insert("value".into(), name["value"].clone());
        preferred.insert("visibility".into(), json!("collaboration"));
        details.insert("preferred_name".into(), Value::Object(preferred));
    }
    result.insert("preferred_names".into(), json!(names));
    Value::Object(result)
}
pub fn personalization(input: &Value, mode: &str, prompt: &str) -> Value {
    let profile = normalize(input);
    let policy = &profile["memory_policy"];
    let collaboration = &profile["collaboration"];
    let partner = string(&collaboration["partner_name"]);
    let mut result = Map::new();
    if !flag(&policy["enabled"], true) {
        result.insert("memory_enabled".into(), json!(false));
        result.insert("learn_from_chat".into(), json!(false));
        if !partner.is_empty() {
            result.insert(
                "partner_name".into(),
                json!(partner.chars().take(80).collect::<String>()),
            );
        }
        return Value::Object(result);
    }
    let context = match mode {
        "story_lab" | "character_room" => "casual",
        "analyst" => "formal",
        "interactive" => "story_presence",
        _ => "default",
    };
    let names = profile["preferred_names"].as_array().unwrap();
    let name = names
        .iter()
        .find(|n| n["context"] == context && n["primary"] != true)
        .or_else(|| names.iter().find(|n| n["primary"] == true));
    result.insert("memory_enabled".into(), json!(true));
    result.insert("learn_from_chat".into(), policy["learn_from_chats"].clone());
    result.insert(
        "preferred_name".into(),
        name.map(|n| n["value"].clone()).unwrap_or(json!("User")),
    );
    result.insert("name_context".into(), json!(context));
    result.insert(
        "prevent_personal_canon".into(),
        policy["behavior"]["prevent_personal_canon"].clone(),
    );
    if !partner.is_empty() {
        result.insert(
            "partner_name".into(),
            json!(partner.chars().take(80).collect::<String>()),
        );
    }
    let categories = &policy["categories"];
    if categories["collaboration_preferences"]["enabled"] == true {
        for key in ["creative_profile", "collaboration", "boundaries"] {
            result.insert(key.into(), profile[key].clone());
        }
    }
    let story = categories["story_presence"]["enabled"] == true;
    let interactive = matches!(mode, "interactive" | "character_room");
    let lower = prompt.to_lowercase();
    let self_query = [
        "who am i",
        "what do you know about me",
        "tell me about myself",
        "siapa aku",
        "kamu tahu apa tentang aku",
        "tentang diriku",
    ]
    .iter()
    .any(|p| lower.contains(p));
    if categories["about_you"]["enabled"] == true {
        result.insert("about".into(), profile["about"].clone());
        let details = profile["personal_details"]
            .as_object()
            .unwrap()
            .iter()
            .filter(|(_, v)| {
                v["visibility"] == "collaboration"
                    || (story && (interactive || self_query) && v["visibility"] == "story_presence")
            })
            .filter(|(_, v)| !v["value"].is_null() && v["value"] != "")
            .map(|(k, v)| (k.clone(), v["value"].clone()))
            .collect::<Map<_, _>>();
        result.insert("personal_details".into(), Value::Object(details));
    }
    if story && interactive {
        result.insert(
            "presence_defaults".into(),
            profile["presence_defaults"].clone(),
        );
    }
    Value::Object(result)
}
