//! Bounded timing and LM Studio performance normalization for one generation run.
//!
//! This module deliberately keeps raw provider responses outside the telemetry
//! contract. Unknown, malformed, negative, and non-finite provider values are
//! represented as `null`; no cache or prefill behavior is inferred.

use serde_json::{json, Map, Value};
use std::collections::BTreeMap;
use std::time::{Duration, Instant};

pub const TELEMETRY_VERSION: &str = "1";

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderPerformance {
    pub input_tokens: Option<u64>,
    pub output_tokens: Option<u64>,
    pub reasoning_tokens: Option<u64>,
    pub ttft_ms: Option<f64>,
    pub output_tokens_per_sec: Option<f64>,
    pub model_load_ms: Option<f64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderAppTimings {
    pub first_text: Option<Duration>,
    pub total: Option<Duration>,
    pub text_stream: Option<Duration>,
}

#[derive(Clone, Debug)]
struct ProviderCall {
    performance: ProviderPerformance,
    app_timings: ProviderAppTimings,
}

/// A monotonic, single-run telemetry accumulator. The caller owns the run ID
/// and should construct this before analysis or provider preparation begins.
#[derive(Debug)]
pub struct RunTelemetry {
    run_id: String,
    started: Instant,
    stages: BTreeMap<String, Duration>,
    server_first_visible_text_ms: Option<u64>,
    provider_calls: Vec<ProviderCall>,
    metadata: BTreeMap<String, Value>,
    frozen_total_ms: Option<u64>,
}

/// A timer that can be ended once and recorded as a named stage.
#[derive(Debug)]
pub struct StageTimer {
    name: String,
    started: Instant,
}

impl RunTelemetry {
    pub fn new(run_id: impl Into<String>) -> Self {
        Self {
            run_id: run_id.into(),
            started: Instant::now(),
            stages: BTreeMap::new(),
            server_first_visible_text_ms: None,
            provider_calls: Vec::new(),
            metadata: BTreeMap::new(),
            frozen_total_ms: None,
        }
    }

    pub fn run_id(&self) -> &str {
        &self.run_id
    }

    pub fn elapsed(&self) -> Duration {
        self.started.elapsed()
    }

    pub fn begin_stage(&self, name: impl Into<String>) -> StageTimer {
        StageTimer {
            name: name.into(),
            started: Instant::now(),
        }
    }

    pub fn end_stage(&mut self, timer: StageTimer) {
        self.record_stage(timer.name, timer.started.elapsed());
    }

    pub fn record_stage(&mut self, name: impl Into<String>, elapsed: Duration) {
        let name = name.into();
        if !name.is_empty() {
            self.stages.insert(name, elapsed);
        }
    }

    /// Accumulate repeated observations such as streamed deltas or persistence
    /// operations instead of replacing an earlier measurement.
    pub fn accumulate_stage(&mut self, name: impl Into<String>, elapsed: Duration) {
        let name = name.into();
        if !name.is_empty() {
            let value = elapsed;
            self.stages
                .entry(name)
                .and_modify(|current| *current = current.saturating_add(value))
                .or_insert(value);
        }
    }

    pub fn freeze_total(&mut self) {
        self.frozen_total_ms = Some(millis(self.started.elapsed()));
    }

    /// Records only the first server-visible text event. This is an
    /// server emission boundary and is intentionally separate from provider TTFT.
    pub fn record_server_first_visible_text(&mut self, elapsed: Duration) {
        if self.server_first_visible_text_ms.is_none() {
            self.server_first_visible_text_ms = Some(millis(elapsed));
        }
    }

    pub fn record_provider_call(&mut self, raw_stats: &Value) {
        self.record_provider_call_with_timings(raw_stats, ProviderAppTimings::default());
    }

    pub fn record_provider_call_with_timings(
        &mut self,
        raw_stats: &Value,
        app_timings: ProviderAppTimings,
    ) {
        self.provider_calls.push(ProviderCall {
            performance: normalize_provider_performance(raw_stats),
            app_timings,
        });
    }

    /// Adds only non-sensitive scalar metadata. Prompt/story/API material is
    /// rejected by key, keeping this output safe for persistence and diagnostics.
    pub fn record_metadata(&mut self, key: impl Into<String>, value: Value) -> bool {
        let key = key.into();
        let lower = key.to_ascii_lowercase();
        let sensitive = [
            "prompt",
            "story",
            "api_key",
            "apikey",
            "authorization",
            "secret",
            "token",
        ]
        .iter()
        .any(|part| lower.contains(part));
        if sensitive || !value.is_string() && !value.is_number() && !value.is_boolean() {
            return false;
        }
        self.metadata.insert(key, value);
        true
    }

    pub fn to_value(&self) -> Value {
        let mut durations = Map::new();
        for key in [
            "preparation",
            "analyze",
            "memory_retrieval",
            "deliberation",
            "context_assembly",
            "provider_capabilities",
            "server_first_visible_text",
            "provider_request_first_text",
            "provider_request_total",
            "provider_text_stream",
            "persistence",
            "validation",
            "memory_index",
            "prefill",
            "decode",
            "total",
        ] {
            let value = if key == "provider_request_first_text" {
                self.provider_call_timing_first_text()
            } else if key == "provider_request_total" {
                self.provider_call_timing_sum(|timings| timings.total)
            } else if key == "provider_text_stream" {
                self.provider_call_timing_sum(|timings| timings.text_stream)
            } else if key == "total" {
                self.stages.get("total").map_or_else(
                    || {
                        self.frozen_total_ms
                            .or_else(|| Some(millis(self.started.elapsed())))
                            .map_or(Value::Null, |v| json!(v))
                    },
                    |v| json!(millis(*v)),
                )
            } else {
                self.stage_value(key)
            };
            durations.insert(key.into(), value);
        }
        for (key, value) in &self.stages {
            durations
                .entry(key.clone())
                .or_insert(json!(millis(*value)));
        }

        let provider = if self.provider_calls.len() == 1 {
            let call = &self.provider_calls[0];
            let mut out = performance_value(&call.performance);
            out.insert("calls".into(), json!([call_value(call)]));
            out.insert("call_count".into(), json!(1));
            Value::Object(out)
        } else {
            json!({
                "input_tokens": Value::Null,
                "output_tokens": Value::Null,
                "reasoning_tokens": Value::Null,
                "ttft_ms": Value::Null,
                "output_tokens_per_sec": Value::Null,
                "model_load_ms": Value::Null,
                "calls": self.provider_calls.iter().map(call_value).collect::<Vec<_>>(),
                "call_count": self.provider_calls.len(),
            })
        };
        json!({
            "version": TELEMETRY_VERSION,
            "run_id": self.run_id,
            "durations_ms": durations,
            "provider": provider,
            "metadata": self.metadata,
        })
    }

    fn provider_call_timing_first_text(&self) -> Value {
        if self.provider_calls.len() != 1 {
            return Value::Null;
        }
        self.provider_calls[0]
            .app_timings
            .first_text
            .map_or(Value::Null, |v| json!(millis(v)))
    }

    fn provider_call_timing_sum<F>(&self, mut select: F) -> Value
    where
        F: FnMut(&ProviderAppTimings) -> Option<Duration>,
    {
        if self.provider_calls.is_empty() {
            return Value::Null;
        }
        let mut sum = 0_u64;
        for call in &self.provider_calls {
            let Some(duration) = select(&call.app_timings) else {
                return Value::Null;
            };
            sum = sum.saturating_add(millis(duration));
        }
        json!(sum)
    }

    fn stage_value(&self, key: &str) -> Value {
        if key == "server_first_visible_text" {
            return self
                .server_first_visible_text_ms
                .map_or(Value::Null, |v| json!(v));
        }
        self.stages
            .get(key)
            .map_or(Value::Null, |v| json!(millis(*v)))
    }
}

impl StageTimer {
    pub fn elapsed(&self) -> Duration {
        self.started.elapsed()
    }
}

fn millis(duration: Duration) -> u64 {
    duration.as_millis().min(u64::MAX as u128) as u64
}

fn call_value(call: &ProviderCall) -> Value {
    let mut out = performance_value(&call.performance);
    out.insert(
        "app_timings_ms".into(),
        json!({
            "first_text": call.app_timings.first_text.map(millis),
            "total": call.app_timings.total.map(millis),
            "text_stream": call.app_timings.text_stream.map(millis),
        }),
    );
    Value::Object(out)
}

fn performance_value(perf: &ProviderPerformance) -> Map<String, Value> {
    let mut out = Map::new();
    out.insert(
        "input_tokens".into(),
        perf.input_tokens.map_or(Value::Null, |v| json!(v)),
    );
    out.insert(
        "output_tokens".into(),
        perf.output_tokens.map_or(Value::Null, |v| json!(v)),
    );
    out.insert(
        "reasoning_tokens".into(),
        perf.reasoning_tokens.map_or(Value::Null, |v| json!(v)),
    );
    out.insert(
        "ttft_ms".into(),
        perf.ttft_ms.map_or(Value::Null, |v| json!(v)),
    );
    out.insert(
        "output_tokens_per_sec".into(),
        perf.output_tokens_per_sec.map_or(Value::Null, |v| json!(v)),
    );
    out.insert(
        "model_load_ms".into(),
        perf.model_load_ms.map_or(Value::Null, |v| json!(v)),
    );
    out
}

/// Normalize known LM Studio/OpenAI-compatible aliases. LM Studio's unsuffixed
/// timing fields are seconds; explicit `_ms` fields remain milliseconds.
pub fn normalize_provider_performance(raw: &Value) -> ProviderPerformance {
    let source = raw
        .get("stats")
        .or_else(|| raw.get("timings"))
        .or_else(|| raw.get("usage"))
        .or_else(|| raw.get("performance"))
        .unwrap_or(raw);
    let source = source
        .get("stats")
        .or_else(|| source.get("timings"))
        .or_else(|| source.get("usage"))
        .or_else(|| source.get("performance"))
        .unwrap_or(source);
    ProviderPerformance {
        input_tokens: integer(
            source,
            &[
                "input_tokens",
                "total_input_tokens",
                "prompt_tokens",
                "prompt_token_count",
            ],
        ),
        output_tokens: integer(
            source,
            &[
                "output_tokens",
                "completion_tokens",
                "total_output_tokens",
                "generated_tokens",
            ],
        ),
        reasoning_tokens: integer(source, &["reasoning_tokens", "reasoning_output_tokens"]),
        ttft_ms: timing_ms(
            source,
            &["ttft_ms", "time_to_first_token_ms", "first_token_ms"],
            &["time_to_first_token_seconds", "time_to_first_token"],
        ),
        output_tokens_per_sec: finite(
            source,
            &[
                "output_tokens_per_sec",
                "tokens_per_second",
                "predicted_per_second",
            ],
        ),
        model_load_ms: timing_ms(source, &["model_load_ms"], &["model_load_time_seconds"]),
    }
}

fn integer(source: &Value, keys: &[&str]) -> Option<u64> {
    keys.iter().find_map(|key| {
        let value = source.get(*key)?;
        value
            .as_u64()
            .or_else(|| value.as_i64().filter(|v| *v >= 0).map(|v| v as u64))
    })
}

fn finite(source: &Value, keys: &[&str]) -> Option<f64> {
    keys.iter().find_map(|key| {
        let value = source.get(*key)?.as_f64()?;
        (value.is_finite() && value >= 0.0).then_some(value)
    })
}

fn timing_ms(source: &Value, millisecond_keys: &[&str], second_keys: &[&str]) -> Option<f64> {
    finite(source, millisecond_keys).or_else(|| {
        finite(source, second_keys)
            .map(|v| v * 1000.0)
            .filter(|v| v.is_finite())
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn missing_malformed_negative_and_non_finite_are_null() {
        let p = normalize_provider_performance(&json!({
            "prompt_tokens": -1,
            "completion_tokens": "bad",
            "time_to_first_token": -0.1,
            "tokens_per_second": "NaN",
            "model_load_time": null,
        }));
        assert_eq!(p.input_tokens, None);
        assert_eq!(p.output_tokens, None);
        assert_eq!(p.ttft_ms, None);
        assert_eq!(p.output_tokens_per_sec, None);
        assert_eq!(p.model_load_ms, None);
    }

    #[test]
    fn lm_studio_seconds_and_millisecond_aliases_are_normalized() {
        let p = normalize_provider_performance(&json!({"stats": {
            "prompt_tokens": 12, "completion_tokens": 8, "reasoning_tokens": 3,
            "time_to_first_token": 0.125, "tokens_per_second": 16.5,
            "model_load_time_seconds": 1.25
        }}));
        assert_eq!(p.input_tokens, Some(12));
        assert_eq!(p.output_tokens, Some(8));
        assert_eq!(p.reasoning_tokens, Some(3));
        assert_eq!(p.ttft_ms, Some(125.0));
        assert_eq!(p.output_tokens_per_sec, Some(16.5));
        assert_eq!(p.model_load_ms, Some(1250.0));
    }

    #[test]
    fn first_visible_text_is_recorded_once_and_provider_ttft_is_distinct() {
        let mut t = RunTelemetry::new("run-1");
        let timer = t.begin_stage("preparation");
        std::thread::yield_now();
        t.end_stage(timer);
        t.record_server_first_visible_text(Duration::from_millis(40));
        t.record_server_first_visible_text(Duration::from_millis(90));
        t.record_provider_call_with_timings(
            &json!({"time_to_first_token": 0.012}),
            ProviderAppTimings {
                first_text: Some(Duration::from_millis(8)),
                total: Some(Duration::from_millis(20)),
                text_stream: Some(Duration::from_millis(12)),
            },
        );
        assert_eq!(
            t.to_value()["durations_ms"]["server_first_visible_text"],
            40
        );
        assert!(!t.to_value()["durations_ms"]["preparation"].is_null());
        assert_eq!(t.to_value()["durations_ms"]["provider_text_stream"], 12);
        assert_eq!(t.to_value()["provider"]["ttft_ms"], 12.0);
    }

    #[test]
    fn repeated_stage_observations_accumulate_and_total_can_be_frozen() {
        let mut t = RunTelemetry::new("run-1");
        t.accumulate_stage("persistence", Duration::from_millis(4));
        t.accumulate_stage("persistence", Duration::from_millis(6));
        t.freeze_total();
        assert_eq!(t.to_value()["durations_ms"]["persistence"], 10);
        assert!(!t.to_value()["durations_ms"]["total"].is_null());
    }

    #[test]
    fn sub_millisecond_stage_accumulation_is_serialized_after_summing() {
        let mut t = RunTelemetry::new("run-1");
        for _ in 0..10 {
            t.accumulate_stage("persistence", Duration::from_micros(900));
        }
        assert_eq!(t.to_value()["durations_ms"]["persistence"], 9);
    }

    #[test]
    fn beat_calls_are_retained_without_a_false_aggregate() {
        let mut t = RunTelemetry::new("run-1");
        t.record_provider_call(&json!({"prompt_tokens": 2, "completion_tokens": 3}));
        t.record_provider_call_with_timings(
            &json!({"prompt_tokens": 4, "completion_tokens": 5}),
            ProviderAppTimings {
                first_text: Some(Duration::from_millis(7)),
                total: Some(Duration::from_millis(10)),
                text_stream: None,
            },
        );
        let provider = &t.to_value()["provider"];
        assert_eq!(provider["call_count"], 2);
        assert!(provider["input_tokens"].is_null());
        assert_eq!(provider["calls"][1]["app_timings_ms"]["first_text"], 7);
    }

    #[test]
    fn metadata_rejects_prompt_story_and_api_keys() {
        let mut t = RunTelemetry::new("run-1");
        assert!(!t.record_metadata("prompt", json!("secret")));
        assert!(!t.record_metadata("api_key", json!("secret")));
        assert!(t.record_metadata("model", json!("local")));
        assert_eq!(t.to_value()["metadata"]["model"], "local");
    }
}
