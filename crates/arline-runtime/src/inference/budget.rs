//! Output allowances are application targets, not provider-enforced quotas.
//! LM Studio receives one combined generation cap; input-window budgeting is separate.

use crate::{config::RuntimeConfig, ApiError, ApiResult};
use serde_json::{json, Value};

use super::telemetry::normalize_provider_performance;

const MAX_INTEGER: u64 = i64::MAX as u64;
pub(crate) const FIELDS: &[(&str, bool)] = &[
    ("visible_output_tokens", false),
    ("reasoning_reserve_tokens", true),
    ("max_output_tokens", false),
    ("beat_tokens", false),
    ("total_story_target_tokens", false),
    ("beat_count", false),
    ("deliberation_max_tokens", false),
];

#[derive(Clone, Debug)]
pub(crate) struct OutputBudget {
    pub visible: u64,
    pub reserve: u64,
    pub api_max: u64,
    requested_reserve: u64,
    mode: String,
    task: String,
    source: String,
    scope: &'static str,
    task_minimum: u64,
    length_hint: Option<u64>,
}

impl OutputBudget {
    pub(crate) fn to_value(&self) -> Value {
        let visible_allowance = self.visible.min(self.api_max);
        json!({
            "version":"1", "mode":self.mode, "task":self.task, "scope":self.scope,
            "source":self.source, "visible_target_tokens":self.visible,
            "visible_allowance_tokens":visible_allowance,
            "requested_reasoning_reserve_tokens":self.requested_reserve,
            "reasoning_reserve_tokens":self.reserve, "api_max_output_tokens":self.api_max,
            "visible_target_exceeds_cap":self.visible > self.api_max,
            "unallocated_output_tokens":self.api_max.saturating_sub(visible_allowance + self.reserve),
            "task_minimum_tokens":self.task_minimum, "length_hint_minimum_tokens":self.length_hint,
            "allocation_enforcement":"shared_provider_cap"
        })
    }
}

pub(crate) struct BudgetPlan {
    pub writers: Vec<OutputBudget>,
    pub planner: OutputBudget,
}

fn integer(name: &str, value: &Value, zero: bool) -> ApiResult<u64> {
    value
        .as_u64()
        .filter(|n| *n <= MAX_INTEGER && (zero || *n > 0))
        .ok_or_else(|| {
            ApiError::bad_request(format!(
                "{name} must be {} integer within the signed 64-bit range",
                if zero { "a non-negative" } else { "a positive" }
            ))
        })
}

fn supplied(body: &Value, key: &str) -> Option<u64> {
    body.get(key)
        .filter(|v| !v.is_null())
        .and_then(Value::as_u64)
}

pub(crate) fn mode(body: &Value, cfg: &RuntimeConfig) -> ApiResult<String> {
    let fallback = cfg.str("generation.output_budget_mode", "fixed");
    let value = body.get("output_budget_mode").filter(|v| !v.is_null());
    let selected = match value {
        Some(value) => value
            .as_str()
            .ok_or_else(|| ApiError::bad_request("output_budget_mode must be a string"))?,
        None => &fallback,
    };
    if !["fixed", "auto"].contains(&selected) {
        return Err(ApiError::bad_request("Unsupported output_budget_mode"));
    }
    Ok(selected.to_owned())
}

pub(crate) fn validate_request(body: &Value, cfg: &RuntimeConfig) -> ApiResult<()> {
    mode(body, cfg)?;
    for &(name, zero) in FIELDS {
        if let Some(value) = body.get(name).filter(|v| !v.is_null()) {
            integer(name, value, zero)?;
        }
    }
    if supplied(body, "beat_count").is_some_and(|n| n > 24) {
        return Err(ApiError::bad_request("beat_count must be between 1 and 24"));
    }
    Ok(())
}

pub(crate) fn validate_config(cfg: &RuntimeConfig) -> ApiResult<()> {
    if let Some(value) = cfg.value("generation.output_budget_mode") {
        if !value
            .as_str()
            .is_some_and(|v| ["fixed", "auto"].contains(&v))
        {
            return Err(ApiError::bad_request("Unsupported output_budget_mode"));
        }
    }
    for (key, name, zero) in [
        (
            "generation.visible_output_tokens",
            "visible_output_tokens",
            false,
        ),
        (
            "generation.reasoning_reserve_tokens",
            "reasoning_reserve_tokens",
            true,
        ),
        ("generation.beat_tokens", "beat_tokens", false),
        (
            "generation.total_story_target_tokens",
            "total_story_target_tokens",
            false,
        ),
        ("generation.beat_count", "beat_count", false),
        ("deliberation.max_tokens", "deliberation_max_tokens", false),
    ] {
        if let Some(value) = cfg.value(key) {
            integer(
                name,
                &serde_json::to_value(value).map_err(|e| ApiError::bad_request(e.to_string()))?,
                zero,
            )?;
        }
    }
    if cfg.u64("generation.beat_count", 4) > 24 {
        return Err(ApiError::bad_request("beat_count must be between 1 and 24"));
    }
    checked_add(
        cfg.u64("generation.visible_output_tokens", 4096),
        cfg.u64("generation.reasoning_reserve_tokens", 4096),
    )?;
    Ok(())
}

fn checked_add(a: u64, b: u64) -> ApiResult<u64> {
    a.checked_add(b)
        .filter(|n| *n <= MAX_INTEGER)
        .ok_or_else(|| {
            ApiError::bad_request("Combined output budget exceeds the signed 64-bit range")
        })
}

fn checked_mul(a: u64, b: u64) -> ApiResult<u64> {
    a.checked_mul(b)
        .filter(|n| *n <= MAX_INTEGER)
        .ok_or_else(|| ApiError::bad_request("Total output budget exceeds the signed 64-bit range"))
}

fn task_minimum(task: &str) -> u64 {
    match task {
        "dialogue" => 768,
        "deep_scene" => 4096,
        "alternatives" | "author_intuition" | "continuity_review" => 1536,
        "story_lab" => 2048,
        "beats" => 1024,
        _ => 512,
    }
}

fn count(text: &str) -> Option<u64> {
    // Accept integers, ranges and conventional thousands separators; no decimals.
    let text = text.trim_matches(|c: char| !c.is_ascii_digit());
    text.split(['-', '–', '—'])
        .map(|part| {
            let groups = part.split(',').collect::<Vec<_>>();
            if groups.len() > 1
                && (groups[0].len() > 3 || groups.iter().skip(1).any(|g| g.len() != 3))
            {
                return None;
            }
            groups.concat().parse::<u64>().ok().filter(|n| *n > 0)
        })
        .collect::<Option<Vec<_>>>()?
        .into_iter()
        .max()
}

fn length_hint(prompt: &str) -> ApiResult<Option<u64>> {
    let words = prompt.split_whitespace().collect::<Vec<_>>();
    let mut minimum = None;
    for (index, word) in words.iter().enumerate() {
        let lower = word.to_ascii_lowercase();
        let unit = lower.trim_matches(|c: char| !c.is_ascii_alphabetic());
        let number = if ["word", "words", "kata", "token", "tokens"].contains(&unit) {
            index.checked_sub(1).and_then(|i| count(words[i]))
        } else {
            None
        };
        if let Some(number) = number {
            let allowance = if ["word", "words", "kata"].contains(&unit) {
                checked_add(checked_mul(number, 3)?, 256)?
            } else {
                number
            };
            minimum = Some(minimum.map_or(allowance, |old: u64| old.max(allowance)));
        }
    }
    Ok(minimum)
}

fn budget(
    visible: u64,
    requested_reserve: u64,
    active_reserve: u64,
    cap: Option<u64>,
    mode: &str,
    task: &str,
    source: &str,
) -> ApiResult<OutputBudget> {
    let nominal = checked_add(visible, active_reserve)?;
    let api_max = cap.unwrap_or(nominal);
    Ok(OutputBudget {
        visible,
        reserve: active_reserve.min(api_max.saturating_sub(visible)),
        api_max,
        requested_reserve,
        mode: mode.into(),
        task: task.into(),
        source: source.into(),
        scope: "writer_call",
        task_minimum: task_minimum(task),
        length_hint: None,
    })
}

pub(crate) fn resolve(body: &Value, cfg: &RuntimeConfig, task: &str) -> ApiResult<BudgetPlan> {
    validate_request(body, cfg)?;
    let mode = mode(body, cfg)?;
    let auto = mode == "auto";
    let prompt = body.get("prompt").and_then(Value::as_str).unwrap_or("");
    let numeric_target = [
        "visible_output_tokens",
        "beat_tokens",
        "total_story_target_tokens",
    ]
    .iter()
    .any(|key| supplied(body, key).is_some());
    let hint = if auto && !numeric_target {
        length_hint(prompt)?
    } else {
        None
    };
    let reserve = supplied(body, "reasoning_reserve_tokens")
        .unwrap_or(cfg.u64("generation.reasoning_reserve_tokens", 4096));
    let configured_reasoning = cfg.str("generation.reasoning", "off");
    let reasoning = body
        .get("reasoning")
        .and_then(Value::as_str)
        .unwrap_or(&configured_reasoning);
    let active_reserve = if reasoning.eq_ignore_ascii_case("off") {
        0
    } else {
        reserve
    };
    let cap = supplied(body, "max_output_tokens");
    let generation = body
        .get("generation_mode")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .unwrap_or_else(|| cfg.str("generation.generation_mode", "single"));
    if !["single", "beats"].contains(&generation.as_str()) {
        return Err(ApiError::bad_request("Unsupported generation mode"));
    }
    let mut writers = Vec::new();
    if generation == "beats" {
        let n = supplied(body, "beat_count").unwrap_or(cfg.u64("generation.beat_count", 4));
        let (total, source) = if let Some(total) = supplied(body, "total_story_target_tokens") {
            (total, "request_total")
        } else if let Some(per) =
            supplied(body, "beat_tokens").or_else(|| supplied(body, "visible_output_tokens"))
        {
            (checked_mul(n, per)?, "request_per_beat")
        } else if auto {
            (
                checked_mul(n, task_minimum("beats"))?.max(hint.unwrap_or(0)),
                "task",
            )
        } else if let Some(total) = cfg
            .value("generation.total_story_target_tokens")
            .and_then(toml::Value::as_integer)
        {
            (total as u64, "config_total")
        } else {
            (
                checked_mul(n, cfg.u64("generation.beat_tokens", 2048))?,
                "config_per_beat",
            )
        };
        if total < n {
            return Err(ApiError::bad_request(
                "total_story_target_tokens must allow at least one token per beat",
            ));
        }
        for index in 0..n {
            let mut resolved = budget(
                total / n + u64::from(index < total % n),
                reserve,
                active_reserve,
                cap,
                &mode,
                "beats",
                source,
            )?;
            resolved.length_hint = hint;
            writers.push(resolved);
        }
    } else {
        let (visible, source) = if let Some(value) = supplied(body, "visible_output_tokens") {
            (value, "request")
        } else if auto {
            // Long-form requests retain generous room even without a numeric hint.
            let lower = prompt.to_lowercase();
            let long = lower
                .split(|c: char| !c.is_alphabetic())
                .any(|w| ["chapter", "novel", "long", "panjang", "bab"].contains(&w));
            (
                task_minimum(task).max(hint.unwrap_or(0)).max(if long {
                    cfg.u64("generation.visible_output_tokens", 4096).max(4096)
                } else {
                    0
                }),
                "task",
            )
        } else {
            (cfg.u64("generation.visible_output_tokens", 4096), "config")
        };
        let mut resolved = budget(visible, reserve, active_reserve, cap, &mode, task, source)?;
        resolved.length_hint = hint;
        writers.push(resolved);
    }
    // Check run-level arithmetic before any planning/provider work.
    writers
        .iter()
        .try_fold(0, |sum, b| checked_add(sum, b.api_max))?;
    let configured_planner = cfg.u64("deliberation.max_tokens", 700);
    let planner_limit = supplied(body, "deliberation_max_tokens").unwrap_or(if auto {
        configured_planner.min(if ["short_continue", "dialogue"].contains(&task) {
            512
        } else {
            700
        })
    } else {
        configured_planner
    });
    let mut planner = budget(
        planner_limit,
        0,
        0,
        None,
        &mode,
        task,
        if supplied(body, "deliberation_max_tokens").is_some() {
            "request"
        } else {
            "config"
        },
    )?;
    planner.scope = "planner_call";
    planner.task_minimum = if auto {
        if ["short_continue", "dialogue"].contains(&task) {
            512
        } else {
            700
        }
    } else {
        0
    };
    if auto
        && supplied(body, "deliberation_max_tokens").is_none()
        && planner_limit < configured_planner
    {
        planner.source = "task".into();
    }
    Ok(BudgetPlan { writers, planner })
}

pub(crate) fn usage(raw: &Value, resolved: &OutputBudget) -> Value {
    let measured = normalize_provider_performance(raw);
    let total = measured.output_tokens;
    let story = total
        .zip(measured.reasoning_tokens)
        .and_then(|(total, reasoning)| total.checked_sub(reasoning));
    let stop = raw
        .get("stop_reason")
        .or_else(|| raw.get("finish_reason"))
        .or_else(|| raw.get("stats").and_then(|s| s.get("finish_reason")))
        .or_else(|| raw.get("stats").and_then(|s| s.get("stop_reason")))
        .or_else(|| {
            raw.get("choices")
                .and_then(Value::as_array)
                .and_then(|c| c.first())
                .and_then(|c| c.get("finish_reason"))
        })
        .and_then(Value::as_str);
    let cutoff = stop.and_then(|reason| match reason {
        "length" | "max_tokens" | "max_output_tokens" | "token_limit" => Some(true),
        "stop" | "eos" | "eos_token" | "end_turn" | "completed" => Some(false),
        _ => None,
    });
    json!({"output_budget":resolved.to_value(),"visible_output_target_tokens":resolved.visible,
        "api_max_output_tokens":resolved.api_max,"reasoning_reserve_tokens":resolved.reserve,
        "story_output_tokens":story,"total_output_tokens":total,"reasoning_output_tokens":measured.reasoning_tokens,
        "output_budget_usage_ratio":total.map(|n|n as f64/resolved.api_max as f64),
        "story_target_ratio":story.map(|n|n as f64/resolved.visible as f64),
        "output_cutoff":cutoff,"output_stop_reason":stop.map(|s|s.chars().take(128).collect::<String>()),
        "likely_output_budget_cutoff":total.map(|n|n as f64 >= resolved.api_max as f64*0.985)})
}

pub(crate) fn aggregate(calls: &[Value]) -> Value {
    let mut result = json!({});
    for key in [
        "visible_output_target_tokens",
        "api_max_output_tokens",
        "reasoning_reserve_tokens",
        "story_output_tokens",
        "total_output_tokens",
        "reasoning_output_tokens",
    ] {
        let sum = calls
            .iter()
            .try_fold(0u64, |sum, c| sum.checked_add(c[key].as_u64()?));
        result[key] = json!(sum);
    }
    for key in ["output_cutoff", "likely_output_budget_cutoff"] {
        result[key] = if calls.iter().any(|c| c[key] == true) {
            json!(true)
        } else if calls.iter().all(|c| c[key] == false) {
            json!(false)
        } else {
            Value::Null
        };
    }
    result["output_budget_usage_ratio"] = json!(result["total_output_tokens"]
        .as_u64()
        .zip(result["api_max_output_tokens"].as_u64())
        .map(|(used, cap)| used as f64 / cap as f64));
    result["story_target_ratio"] = json!(result["story_output_tokens"]
        .as_u64()
        .zip(result["visible_output_target_tokens"].as_u64())
        .map(|(used, target)| used as f64 / target as f64));
    result["output_budget"] = json!({"version":"1","mode":calls.first().map(|c|c["output_budget"]["mode"].clone()),"task":"beats","scope":"writer_total",
        "visible_target_tokens":result["visible_output_target_tokens"],"reasoning_reserve_tokens":result["reasoning_reserve_tokens"],"api_max_output_tokens":result["api_max_output_tokens"],
        "calls":calls.iter().map(|c|c["output_budget"].clone()).collect::<Vec<_>>()});
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    fn cfg() -> RuntimeConfig {
        let d = tempfile::tempdir().unwrap();
        let p = d.path().join("c.toml");
        std::fs::write(
            &p,
            "[generation]\nvisible_output_tokens=4096\nreasoning_reserve_tokens=9\n",
        )
        .unwrap();
        RuntimeConfig::load(&p, d.path()).unwrap()
    }
    #[test]
    fn auto_length_and_user_limits_have_distinct_authority() {
        let cfg = cfg();
        let auto = resolve(
            &json!({"prompt":"Write 1,000 words","output_budget_mode":"auto"}),
            &cfg,
            "short_continue",
        )
        .unwrap();
        assert_eq!(auto.writers[0].visible, 3256);
        let explicit=resolve(&json!({"prompt":"Write 1,000 words","output_budget_mode":"auto","visible_output_tokens":17,"max_output_tokens":7}),&cfg,"short_continue").unwrap();
        assert_eq!(explicit.writers[0].visible, 17);
        assert_eq!(explicit.writers[0].api_max, 7);
        assert_eq!(
            explicit.writers[0].to_value()["visible_target_exceeds_cap"],
            true
        );
    }
    #[test]
    fn explicit_extra_cap_is_not_misreported_as_reasoning_reserve() {
        let b = resolve(
            &json!({"visible_output_tokens":17,"reasoning":"on","max_output_tokens":100}),
            &cfg(),
            "short_continue",
        )
        .unwrap();
        assert_eq!(b.writers[0].reserve, 9);
        assert_eq!(b.writers[0].to_value()["unallocated_output_tokens"], 74);
    }
    #[test]
    fn cutoff_and_usage_unknowns_are_preserved() {
        let b = resolve(
            &json!({"visible_output_tokens":100}),
            &cfg(),
            "short_continue",
        )
        .unwrap();
        let unknown = usage(&json!({}), &b.writers[0]);
        assert!(unknown["output_cutoff"].is_null());
        assert!(unknown["story_output_tokens"].is_null());
        let near = usage(&json!({"stats":{"total_output_tokens":100}}), &b.writers[0]);
        assert_eq!(near["likely_output_budget_cutoff"], true);
        assert!(near["output_cutoff"].is_null());
        assert!(near["story_output_tokens"].is_null());
        assert_eq!(
            usage(&json!({"finish_reason":"length"}), &b.writers[0])["output_cutoff"],
            true
        );
    }
    #[test]
    fn exact_beat_split_and_overflow_validation() {
        let plan=resolve(&json!({"generation_mode":"beats","beat_count":3,"total_story_target_tokens":10,"reasoning":"on"}),&cfg(),"beats").unwrap();
        assert_eq!(
            plan.writers.iter().map(|b| b.visible).collect::<Vec<_>>(),
            vec![4, 3, 3]
        );
        assert!(resolve(
            &json!({"visible_output_tokens":i64::MAX,"reasoning":"on"}),
            &cfg(),
            "short_continue"
        )
        .is_err());
        assert!(resolve(
            &json!({"generation_mode":"beats","beat_count":3,"total_story_target_tokens":2}),
            &cfg(),
            "beats"
        )
        .is_err());
    }
    #[test]
    fn multilingual_hints_and_long_form_keep_room() {
        for (prompt, expected) in [
            ("Tulis 500-1000 kata.", 3256),
            ("Write 250 tokens.", 250),
            ("Write 1.5 words", 0),
        ] {
            assert_eq!(length_hint(prompt).unwrap().unwrap_or(0), expected);
        }
        assert!(
            resolve(
                &json!({"prompt":"Tulis bab panjang","output_budget_mode":"auto"}),
                &cfg(),
                "short_continue"
            )
            .unwrap()
            .writers[0]
                .visible
                >= 4096
        );
    }
}
