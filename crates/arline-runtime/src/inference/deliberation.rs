//! Pure deliberation routing policy.
//!
//! This module only classifies a request.  It does not retrieve context,
//! validate canon, call a provider, or infer facts from prose.

use crate::{config::RuntimeConfig, ApiError, ApiResult};
use serde_json::{json, Value};

const MODES: &[&str] = &["on", "off", "auto", "fast", "deep"];

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct RoutingDecision {
    pub planning_enabled: bool,
    requested_mode: String,
    mode_source: String,
    effective_mode: String,
    task: String,
    reason: String,
    preparation_fast_path: bool,
}

impl RoutingDecision {
    pub(crate) fn to_value(&self) -> Value {
        json!({
            "version": "1.0",
            "requested_mode": self.requested_mode,
            "mode_source": self.mode_source,
            "effective_mode": self.effective_mode,
            "planning_enabled": self.planning_enabled,
            "task": self.task,
            "reason": self.reason,
            "preparation_fast_path": self.preparation_fast_path,
        })
    }
}

fn validate_value(name: &str, value: &toml::Value) -> ApiResult<()> {
    let mode = value
        .as_str()
        .ok_or_else(|| ApiError::bad_request(format!("{name} must be a string")))?;
    if !MODES.contains(&mode) {
        return Err(ApiError::bad_request(format!("Unknown {name}: {mode}")));
    }
    Ok(())
}

/// Validate explicit request and saved configuration modes without changing
/// any state. A JSON null request means "not specified" for compatibility.
pub(crate) fn validate_mode(body: &Value, cfg: &RuntimeConfig) -> ApiResult<()> {
    if let Some(value) = body.get("deliberation_mode") {
        if !value.is_null() {
            let mode = value.as_str().ok_or_else(|| {
                ApiError::bad_request("deliberation_mode must be a string or null")
            })?;
            if !MODES.contains(&mode) {
                return Err(ApiError::bad_request(format!(
                    "Unknown deliberation_mode: {mode}"
                )));
            }
        }
    }
    if let Some(value) = cfg.value("deliberation.mode") {
        validate_value("deliberation.mode", value)?;
    }
    Ok(())
}

fn command_rows(directives: &Value) -> Vec<&Value> {
    let mut rows = Vec::new();
    if let Some(stack) = directives.get("stack").and_then(Value::as_array) {
        rows.extend(stack.iter());
    }
    if let Some(command) = directives.get("command") {
        if command.is_object() && !rows.iter().any(|row| std::ptr::eq(*row, command)) {
            rows.push(command);
        }
    }
    rows
}

fn author_task(directives: &Value) -> Option<&'static str> {
    for row in command_rows(directives) {
        let id = row.get("id").and_then(Value::as_str).unwrap_or("");
        let profile = row
            .get("execution_contract")
            .and_then(|x| x.get("deliberation_profile"))
            .and_then(Value::as_str)
            .unwrap_or("");
        if id == "intuition" || profile == "inspect" {
            return Some("author_intuition");
        }
        if id == "alternatives" || profile == "alternatives" {
            return Some("alternatives");
        }
    }
    None
}

fn has_profile(directives: &Value, profiles: &[&str]) -> bool {
    command_rows(directives).iter().any(|row| {
        row.get("execution_contract")
            .and_then(|x| x.get("deliberation_profile"))
            .and_then(Value::as_str)
            .is_some_and(|profile| profiles.contains(&profile))
    })
}

fn ref_count(directives: &Value) -> usize {
    directives
        .get("reference_expressions")
        .and_then(Value::as_array)
        .map_or(0, Vec::len)
}

fn body_ref_count(body: &Value) -> usize {
    body.get("references")
        .and_then(Value::as_array)
        .map_or(0, Vec::len)
}

fn complex_auto(body: &Value, analysis: &Value, directives: &Value) -> bool {
    if body.get("conversation_mode").and_then(Value::as_str) == Some("story_lab")
        || body.get("generation_mode").and_then(Value::as_str) == Some("beats")
    {
        return true;
    }
    let prompt = body.get("prompt").and_then(Value::as_str).unwrap_or("");
    let lower = prompt.trim().to_ascii_lowercase();
    if [
        "review continuity",
        "check continuity",
        "continuity review",
        "cek kontinuitas",
        "periksa kontinuitas",
    ]
    .iter()
    .any(|prefix| lower.starts_with(prefix))
    {
        return true;
    }
    if has_profile(directives, &["scene", "interaction", "revision"])
        || analysis
            .get("unresolved")
            .and_then(Value::as_array)
            .is_some_and(|x| !x.is_empty())
        || analysis
            .get("unknown")
            .or_else(|| analysis.get("unknowns"))
            .and_then(Value::as_array)
            .is_some_and(|x| !x.is_empty())
        || directives
            .get("diagnostics")
            .and_then(Value::as_array)
            .is_some_and(|x| !x.is_empty())
        || directives
            .get("unresolved_references")
            .and_then(Value::as_array)
            .is_some_and(|x| !x.is_empty())
        || analysis
            .get("writer_context")
            .and_then(|x| x.get("unknown"))
            .and_then(Value::as_array)
            .is_some_and(|x| !x.is_empty())
        || analysis
            .get("wcf_validation")
            .and_then(|x| x.get("valid"))
            .and_then(Value::as_bool)
            == Some(false)
        || ref_count(directives) > 2
        || body_ref_count(body) > 2
        || prompt.chars().count() > 800
        || prompt.split_whitespace().count() > 80
    {
        return true;
    }
    false
}

pub(crate) fn route(
    body: &Value,
    analysis: &Value,
    directives: &Value,
    cfg: &RuntimeConfig,
) -> ApiResult<RoutingDecision> {
    validate_mode(body, cfg)?;
    let selected = if let Some(value) = body.get("deliberation_mode") {
        if value.is_null() {
            None
        } else {
            Some((value.as_str().unwrap_or_default(), "request"))
        }
    } else {
        None
    };
    let selected = selected.or_else(|| {
        cfg.value("deliberation.mode")
            .and_then(toml::Value::as_str)
            .map(|mode| (mode, "config"))
    });
    let (requested_mode, mode_source) = match selected {
        Some((mode, source)) => (mode.to_owned(), source.to_owned()),
        None => {
            let enabled = cfg.bool("deliberation.enabled", false);
            (
                if enabled { "on" } else { "off" }.to_owned(),
                "legacy_enabled".to_owned(),
            )
        }
    };

    let author = author_task(directives);
    let explicit_off = requested_mode == "off";
    let deep = requested_mode == "deep";
    let complex_task = complex_auto(body, analysis, directives);
    let auto_deep = requested_mode == "auto" && complex_task;
    let planning_enabled =
        !explicit_off && (deep || auto_deep || requested_mode == "on" || author.is_some());
    let continuity_review = body
        .get("prompt")
        .and_then(Value::as_str)
        .map(|prompt| prompt.trim().to_ascii_lowercase())
        .is_some_and(|prompt| {
            [
                "review continuity",
                "check continuity",
                "continuity review",
                "cek kontinuitas",
                "periksa kontinuitas",
            ]
            .iter()
            .any(|prefix| prompt.starts_with(prefix))
        });
    let task = author
        .map(str::to_owned)
        .or_else(|| {
            if body.get("conversation_mode").and_then(Value::as_str) == Some("story_lab") {
                Some("story_lab".to_owned())
            } else if body.get("generation_mode").and_then(Value::as_str) == Some("beats") {
                Some("beats".to_owned())
            } else if continuity_review {
                Some("continuity_review".to_owned())
            } else if has_profile(directives, &["dialogue", "character"]) && !complex_task {
                Some("dialogue".to_owned())
            } else if complex_task {
                Some("deep_scene".to_owned())
            } else {
                Some("short_continue".to_owned())
            }
        })
        .unwrap();
    let effective_mode = if planning_enabled { "deep" } else { "fast" };
    let reason = if explicit_off {
        "explicit_off"
    } else if author.is_some() {
        "explicit_author_command"
    } else if requested_mode == "deep" {
        "explicit_deep"
    } else if requested_mode == "fast" {
        "explicit_fast"
    } else if requested_mode == "on" {
        "explicit_on"
    } else if auto_deep {
        "auto_complex"
    } else {
        "auto_simple"
    };
    Ok(RoutingDecision {
        planning_enabled,
        requested_mode,
        mode_source,
        effective_mode: effective_mode.to_owned(),
        task,
        reason: reason.to_owned(),
        preparation_fast_path: effective_mode == "fast" && !planning_enabled,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::RuntimeConfig;
    use serde_json::json;
    use tempfile::tempdir;

    fn cfg(extra: &str) -> RuntimeConfig {
        let dir = tempdir().unwrap();
        let path = dir.path().join("runtime.toml");
        std::fs::write(&path, format!("[deliberation]\n{extra}")).unwrap();
        RuntimeConfig::load(&path, dir.path()).unwrap()
    }

    fn route_with(
        body: Value,
        analysis: Value,
        directives: Value,
        config: &RuntimeConfig,
    ) -> RoutingDecision {
        route(&body, &analysis, &directives, config).unwrap()
    }

    #[test]
    fn explicit_modes_and_saved_legacy_precedence() {
        let config = cfg("mode='deep'\nenabled=true");
        assert!(
            !route_with(
                json!({"prompt":"x","deliberation_mode":"off"}),
                json!({}),
                json!({}),
                &config
            )
            .planning_enabled
        );
        assert_eq!(
            route_with(
                json!({"prompt":"x","deliberation_mode":"on"}),
                json!({}),
                json!({}),
                &config
            )
            .effective_mode,
            "deep"
        );
        assert_eq!(
            route_with(
                json!({"prompt":"x","deliberation_mode":null}),
                json!({}),
                json!({}),
                &config
            )
            .requested_mode,
            "deep"
        );
    }

    #[test]
    fn invalid_and_non_string_modes_are_rejected() {
        let config = cfg("");
        assert!(route(
            &json!({"deliberation_mode":"sometimes"}),
            &json!({}),
            &json!({}),
            &config
        )
        .is_err());
        assert!(route(
            &json!({"deliberation_mode":true}),
            &json!({}),
            &json!({}),
            &config
        )
        .is_err());
        let mut bad = cfg("");
        bad.set("deliberation.mode", toml::Value::String("sometimes".into()))
            .unwrap();
        assert!(validate_mode(&json!({}), &bad).is_err());
    }

    #[test]
    fn quoted_prompt_does_not_create_author_command() {
        let config = cfg("");
        let d = route_with(
            json!({"prompt":"Write \"/intuition\" as dialogue","deliberation_mode":"auto"}),
            json!({}),
            json!({"stack":[]}),
            &config,
        );
        assert_eq!(d.task, "short_continue");
    }

    #[test]
    fn stacked_author_command_survives_last_command() {
        let config = cfg("");
        let directives =
            json!({"stack":[{"id":"intuition"},{"id":"continue"}],"command":{"id":"continue"}});
        let d = route_with(
            json!({"prompt":"x","deliberation_mode":"fast"}),
            json!({}),
            directives,
            &config,
        );
        assert!(d.planning_enabled);
        assert_eq!(d.task, "author_intuition");
    }

    #[test]
    fn auto_uses_structured_complexity_and_multilingual_continuity() {
        let config = cfg("mode='auto'");
        let d = route_with(
            json!({"prompt":"Cek kontinuitas antara bab ini dan cabang aktif."}),
            json!({}),
            json!({}),
            &config,
        );
        assert_eq!(d.effective_mode, "deep");
        let long = "kata ".repeat(81);
        let d = route_with(json!({"prompt":long}), json!({}), json!({}), &config);
        assert_eq!(d.effective_mode, "deep");
    }

    #[test]
    fn explicit_off_preserves_author_task_metadata() {
        let config = cfg("");
        let d = route_with(
            json!({"prompt":"x","deliberation_mode":"off"}),
            json!({}),
            json!({"stack":[{"id":"alternatives"}]}),
            &config,
        );
        assert!(!d.planning_enabled);
        assert_eq!(d.task, "alternatives");
        assert_eq!(d.reason, "explicit_off");
        assert_eq!(d.effective_mode, "fast");
        assert!(!d.to_value()["planning_enabled"].as_bool().unwrap());
    }

    #[test]
    fn explicit_mode_reasons_and_fast_author_override_are_distinct() {
        let config = cfg("");
        let fast = route_with(
            json!({"prompt":"x","deliberation_mode":"fast"}),
            json!({}),
            json!({"stack":[{"id":"intuition"}]}),
            &config,
        );
        assert!(fast.planning_enabled);
        assert_eq!(fast.effective_mode, "deep");
        assert_eq!(fast.reason, "explicit_author_command");
        let deep = route_with(
            json!({"prompt":"x","deliberation_mode":"deep"}),
            json!({}),
            json!({}),
            &config,
        );
        assert_eq!(deep.reason, "explicit_deep");
        let on = route_with(
            json!({"prompt":"x","deliberation_mode":"on"}),
            json!({}),
            json!({}),
            &config,
        );
        assert_eq!(on.reason, "explicit_on");
    }

    #[test]
    fn auto_prioritizes_task_kind_and_structured_unknowns() {
        let config = cfg("mode='auto'");
        let continuity = route_with(
            json!({"prompt":"review continuity of this scene"}),
            json!({}),
            json!({}),
            &config,
        );
        assert_eq!(continuity.task, "continuity_review");
        assert_eq!(continuity.reason, "auto_complex");
        let unknown = route_with(
            json!({"prompt":"continue"}),
            json!({"writer_context":{"unknown":["pov"]}}),
            json!({}),
            &config,
        );
        assert_eq!(unknown.task, "deep_scene");
        let refs = route_with(
            json!({"prompt":"continue","references":[1,2,3]}),
            json!({}),
            json!({}),
            &config,
        );
        assert_eq!(refs.task, "deep_scene");
    }
}
