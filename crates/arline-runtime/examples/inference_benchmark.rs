//! Reproducible, provider-facing inference benchmark.
//!
//! The benchmark owns a temporary Arline runtime workspace and talks to it over
//! loopback. It records observations only; it does not reset, load, unload, or
//! infer a cache hit from timing.

use arline_runtime::{config::RuntimeConfig, router, AppState};
use clap::{Parser, ValueEnum};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    cmp::Ordering,
    fs,
    future::IntoFuture,
    io::Read,
    path::PathBuf,
    process::{Command, Stdio},
    thread,
    time::{Duration as StdDuration, Instant},
};
use tokio::{
    net::TcpListener,
    time::{timeout, Duration},
};

const CORPUS: &str = include_str!("../tests/fixtures/inference_workloads.json");

#[derive(Clone, Copy, Debug, Deserialize, Serialize, ValueEnum, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
enum Category {
    ColdModel,
    WarmUnique,
    WarmPrefix,
    WarmDynamic,
}

#[derive(Debug, Deserialize)]
struct Workload {
    id: String,
    kind: String,
    prompt: String,
    stable_context: String,
    prefix_eligible: bool,
    dynamic_eligible: bool,
}

#[derive(Clone, Copy, Debug, ValueEnum, Serialize)]
#[serde(rename_all = "lowercase")]
enum Deliberation {
    On,
    Off,
    Auto,
    Fast,
    Deep,
}

#[derive(Clone, Copy, Debug, ValueEnum, Serialize)]
#[serde(rename_all = "lowercase")]
enum OutputBudgetMode {
    Fixed,
    Auto,
}

#[derive(Parser, Debug)]
#[command(about = "Run a bounded Arline inference benchmark against a local provider")]
struct Args {
    #[arg(long, default_value = "http://127.0.0.1:1234")]
    provider_url: String,
    #[arg(long)]
    model: String,
    #[arg(long)]
    out: Option<PathBuf>,
    #[arg(long, default_value_t = 1, value_parser = clap::value_parser!(u32).range(1..=100))]
    repeats: u32,
    #[arg(long, value_enum, default_value_t = Category::WarmUnique)]
    category: Category,
    #[arg(long, value_enum, default_value_t = Deliberation::Off)]
    deliberation: Deliberation,
    #[arg(long, value_enum, default_value_t = OutputBudgetMode::Fixed)]
    output_budget_mode: OutputBudgetMode,
    #[arg(long)]
    workload: Option<String>,
    #[arg(long, default_value_t = 0.2)]
    temperature: f64,
    #[arg(long)]
    output_budget: Option<u64>,
    #[arg(long)]
    cold_attestation: Option<String>,
    #[arg(long)]
    revision: Option<String>,
    #[arg(long)]
    dry_run: bool,
}

#[derive(Serialize)]
struct ManifestItem<'a> {
    id: &'a str,
    kind: &'a str,
    repetition: u32,
    order: u32,
}

fn workloads() -> Result<Vec<Workload>, String> {
    serde_json::from_str(CORPUS).map_err(|e| format!("invalid benchmark corpus: {e}"))
}

fn eligible(w: &Workload, category: Category) -> bool {
    match category {
        Category::WarmPrefix => w.prefix_eligible,
        Category::WarmDynamic => w.dynamic_eligible,
        _ => true,
    }
}

fn manifest(args: &Args, corpus: &[Workload]) -> Result<Vec<(usize, u32)>, String> {
    if args.model.trim().is_empty() {
        return Err("--model is required and cannot be empty".into());
    }
    if !args.temperature.is_finite() || !(0.0..=2.0).contains(&args.temperature) {
        return Err("--temperature must be finite and between 0 and 2".into());
    }
    if args
        .output_budget
        .is_some_and(|value| !(1..=8192).contains(&value))
    {
        return Err("--output-budget must be between 1 and 8192".into());
    }
    if matches!(args.category, Category::ColdModel)
        && args
            .cold_attestation
            .as_deref()
            .unwrap_or("")
            .trim()
            .is_empty()
    {
        return Err("--cold-attestation is required for --category cold-model".into());
    }
    if matches!(args.category, Category::ColdModel)
        && (args.repeats != 1 || args.workload.is_none())
    {
        return Err("cold-model requires exactly one --workload and --repeats 1".into());
    }
    if corpus.len() != 6
        || corpus.iter().any(|w| {
            w.id.trim().is_empty()
                || w.prompt.trim().is_empty()
                || w.stable_context.trim().is_empty()
        })
    {
        return Err("corpus must contain six non-empty synthetic workloads".into());
    }
    let eligible: Vec<usize> = corpus
        .iter()
        .enumerate()
        .filter(|(_, w)| {
            eligible(w, args.category) && args.workload.as_deref().is_none_or(|id| id == w.id)
        })
        .map(|(i, _)| i)
        .collect();
    if eligible.is_empty() {
        return Err("category has no eligible workloads".into());
    }
    let mut result = Vec::new();
    for rep in 0..args.repeats {
        let mut order = eligible.clone();
        if rep % 2 == 1 {
            order.reverse();
        }
        result.extend(order.into_iter().map(|i| (i, rep + 1)));
    }
    Ok(result)
}

fn render_prompt(workload: &Workload, category: Category, repetition: u32) -> String {
    let context = if workload.id == "canon-long" {
        (1..=120)
            .map(|index| format!("Context segment {index}: {}", workload.stable_context))
            .collect::<Vec<_>>()
            .join("\n")
    } else {
        workload.stable_context.clone()
    };
    let variation = match category {
        Category::WarmDynamic | Category::WarmUnique => {
            format!("\nSynthetic variation {repetition}.")
        }
        _ => String::new(),
    };
    format!("{context}\n\n{}{variation}", workload.prompt)
}

fn seed_continuation(
    state: &AppState,
    session_id: &str,
    workload: &Workload,
) -> Result<(), String> {
    state.store.insert("sessions", json!({"id":session_id,"title":"Synthetic continuation","created_at":"2026-01-01T00:00:00Z","updated_at":"2026-01-01T00:00:00Z"})).map_err(|e| e.to_string())?;
    state.store.insert("turns", json!({"session_id":session_id,"user_prompt":"Synthetic prior courier turn","story":workload.stable_context,"created_at":"2026-01-01T00:00:00Z","updated_at":"2026-01-01T00:00:00Z"})).map_err(|e| e.to_string())?;
    Ok(())
}

fn make_request_body(
    args: &Args,
    workload: &Workload,
    prompt: String,
    session_id: String,
) -> Value {
    let mut body = json!({"model":args.model,"prompt":prompt,"session_id":session_id,"conversation_mode":if workload.kind=="story-lab"{"story_lab"}else{"story_writer"},"deliberation_mode":args.deliberation,"output_budget_mode":args.output_budget_mode,"reasoning":"off","temperature":args.temperature,"reasoning_reserve_tokens":0});
    let budget = match args.output_budget_mode {
        OutputBudgetMode::Fixed => Some(args.output_budget.unwrap_or(256)),
        OutputBudgetMode::Auto => args.output_budget,
    };
    if let Some(budget) = budget {
        body["visible_output_tokens"] = json!(budget);
        body["max_output_tokens"] = json!(budget);
    }
    if workload.kind == "multi-beat" {
        body["generation_mode"] = json!("beats");
        body["beat_count"] = json!(3);
        if let Some(budget) = budget {
            body["beat_tokens"] = json!(budget.max(256));
        }
    }
    body
}

fn quantile(values: &[f64], q: f64) -> Option<f64> {
    if values.is_empty() {
        return None;
    }
    let mut v = values.to_vec();
    v.sort_by(|a, b| a.partial_cmp(b).unwrap_or(Ordering::Equal));
    let position = (v.len() - 1) as f64 * q;
    let lower = position.floor() as usize;
    let upper = position.ceil() as usize;
    if lower == upper {
        return v.get(lower).copied();
    }
    Some(v[lower] + (v[upper] - v[lower]) * (position - lower as f64))
}

fn nvidia_snapshot() -> Value {
    let mut child = match Command::new("nvidia-smi")
        .args([
            "--query-gpu=name,memory.used,memory.total,utilization.gpu",
            "--format=csv,noheader,nounits",
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(child) => child,
        Err(_) => return json!({"status":"unavailable","reason":"nvidia-smi not found"}),
    };
    for _ in 0..30 {
        match child.try_wait() {
            Ok(Some(status)) => {
                let mut bytes = Vec::new();
                if let Some(mut stdout) = child.stdout.take() {
                    let _ = stdout.by_ref().take(4096).read_to_end(&mut bytes);
                }
                return if status.success() {
                    json!({"status":"available","text":String::from_utf8_lossy(&bytes)})
                } else {
                    json!({"status":"unavailable","reason":format!("exit {status}")})
                };
            }
            Ok(None) => thread::sleep(StdDuration::from_millis(100)),
            Err(error) => return json!({"status":"unavailable","reason":error.to_string()}),
        }
    }
    let _ = child.kill();
    let _ = child.wait();
    json!({"status":"unavailable","reason":"timeout"})
}

fn write_new(path: &PathBuf, value: &Value) -> Result<(), String> {
    let bytes = serde_json::to_vec_pretty(value).map_err(|e| e.to_string())?;
    use std::io::Write;
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|e| format!("cannot create report {}: {e}", path.display()))?;
    file.write_all(&bytes).map_err(|e| e.to_string())?;
    file.write_all(b"\n").map_err(|e| e.to_string())?;
    file.sync_all().map_err(|e| e.to_string())
}

async fn provider_snapshot(client: &reqwest::Client, base: &str, model: &str) -> Value {
    let response = match client
        .get(format!("{}/api/v1/models", base.trim_end_matches('/')))
        .send()
        .await
    {
        Ok(response) if response.status().is_success() => response,
        Ok(response) => {
            return json!({"status":"unavailable","reason":format!("http {}", response.status())})
        }
        Err(_) => {
            return json!({"status":"unavailable","reason":"provider model metadata unavailable"})
        }
    };
    let body = match response.json::<Value>().await {
        Ok(body) => body,
        Err(_) => return json!({"status":"unavailable","reason":"invalid provider model metadata"}),
    };
    let selected = body
        .get("models")
        .and_then(Value::as_array)
        .and_then(|models| {
            models.iter().find(|item| {
                item.get("id").and_then(Value::as_str) == Some(model)
                    || item.get("key").and_then(Value::as_str) == Some(model)
            })
        });
    let Some(selected) = selected else {
        return json!({"status":"available","selected_model":"unknown","residency":"unknown"});
    };
    let mut result = serde_json::Map::new();
    for key in [
        "id",
        "key",
        "loaded_instances",
        "loaded",
        "context_length",
        "max_context_length",
        "file",
        "path",
        "backend",
        "backend_version",
        "metadata",
    ] {
        if let Some(value) = selected.get(key) {
            result.insert(key.to_string(), value.clone());
        }
    }
    result.insert("status".into(), json!("available"));
    result.insert(
        "residency".into(),
        selected
            .get("loaded_instances")
            .or_else(|| selected.get("loaded"))
            .cloned()
            .unwrap_or_else(|| json!("unknown")),
    );
    Value::Object(result)
}

#[tokio::main]
async fn main() {
    if let Err(e) = run().await {
        eprintln!("benchmark error: {e}");
        std::process::exit(2);
    }
}

async fn run() -> Result<(), String> {
    let args = Args::parse();
    let corpus = workloads()?;
    let plan = manifest(&args, &corpus)?;
    if args.dry_run {
        let items: Vec<_> = plan
            .iter()
            .enumerate()
            .map(|(order, (idx, rep))| ManifestItem {
                id: &corpus[*idx].id,
                kind: &corpus[*idx].kind,
                repetition: *rep,
                order: (order + 1) as u32,
            })
            .collect();
        println!("{}", serde_json::to_string_pretty(&json!({"category":args.category,"model":args.model,"repeats":args.repeats,"workloads":items})).unwrap());
        return Ok(());
    }
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(900))
        .build()
        .map_err(|e| e.to_string())?;
    let provider_metadata = provider_snapshot(&client, &args.provider_url, &args.model).await;
    let mut samples = Vec::new();
    let mut latencies = Vec::new();
    let mut errors = 0u32;
    for (order, (idx, rep)) in plan.iter().enumerate() {
        let w = &corpus[*idx];
        let (elapsed, output_length, stats, error) = run_one(&args, w, *rep, &client).await?;
        if !error.is_null() {
            errors += 1;
        } else {
            latencies.push(elapsed);
        }
        samples.push(json!({"order":order+1,"repetition":rep,"workload_id":w.id,"latency_ms":elapsed,"output_length":output_length,"stats":stats,"error":error}));
    }
    let effective_budget = match args.output_budget_mode {
        OutputBudgetMode::Fixed => args.output_budget.or(Some(256)),
        OutputBudgetMode::Auto => args.output_budget,
    };
    let report = json!({"schema":"arline.inference-benchmark.v1","category":args.category,"model":args.model,"provider_url":args.provider_url,"workload":args.workload,"repeats":args.repeats,"deliberation":args.deliberation,"revision":args.revision.unwrap_or_else(||"unknown".into()),"cold_attestation":if matches!(args.category,Category::ColdModel){json!({"procedure":args.cold_attestation,"verification":"attested_not_independently_verified"})}else{Value::Null},"environment":{"application_state":"fresh_per_sample","runtime_config":{"deliberation":args.deliberation,"output_budget_mode":args.output_budget_mode,"output_budget_requested":args.output_budget,"output_budget_effective":effective_budget,"temperature":args.temperature,"effective_seed":"unsupported_unknown","cutoff_detection":"per_sample_stats_unknown_when_unreported"},"provider_metadata":provider_metadata,"nvidia":nvidia_snapshot()},"metrics":{"sample_count":plan.len(),"successful_count":latencies.len(),"error_count":errors,"median_latency_ms":quantile(&latencies,0.5),"p95_latency_ms":quantile(&latencies,0.95),"output_lengths_recorded":true,"cutoff_detection":"per_sample_stats_unknown_when_unreported","speedup_claim":"unknown"},"telemetry_metrics":telemetry_metrics(&samples),"residency_observation":"unknown_unless_reported_by_provider_or_stats.inference","samples":samples});
    if let Some(path) = args.out {
        write_new(&path, &report)?;
    } else {
        println!("{}", serde_json::to_string_pretty(&report).unwrap());
    }
    Ok(())
}

async fn run_one(
    args: &Args,
    workload: &Workload,
    repetition: u32,
    client: &reqwest::Client,
) -> Result<(f64, Option<usize>, Value, Value), String> {
    let temp = tempfile::tempdir().map_err(|e| e.to_string())?;
    let config_path = temp.path().join("arline.toml");
    fs::write(&config_path, format!("[lmstudio]\nbase_url = {:?}\nmodel = {:?}\napi_key = \"\"\ntimeout_seconds = 600.0\n[reasoning_runtime]\nenforce_model_capabilities = false\n[generation]\nreasoning = \"off\"\nvisible_output_tokens = {}\nreasoning_reserve_tokens = 0\n[writer]\nsystem_prompt_file = \"writer_system.txt\"\n[workspace]\ndatabase_path = \"data/history.db\"\n", args.provider_url, args.model, args.output_budget.unwrap_or(256))).map_err(|e| e.to_string())?;
    fs::write(
        temp.path().join("writer_system.txt"),
        "Synthetic benchmark system prompt.",
    )
    .map_err(|e| e.to_string())?;
    let config = RuntimeConfig::load(&config_path, temp.path()).map_err(|e| e.to_string())?;
    let state = AppState::open(config).map_err(|e| e.to_string())?;
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .map_err(|e| e.to_string())?;
    let url = format!(
        "http://{}",
        listener.local_addr().map_err(|e| e.to_string())?
    );
    let task = tokio::spawn(axum::serve(listener, router(state.clone())).into_future());
    let session_id = format!("benchmark-{}-{}", repetition, workload.id);
    if workload.kind == "continuation" {
        seed_continuation(&state, &session_id, workload)?;
    }
    let request_body = make_request_body(
        args,
        workload,
        render_prompt(workload, args.category, repetition),
        session_id,
    );
    let started = Instant::now();
    let response = timeout(
        Duration::from_secs(900),
        client
            .post(format!("{url}/api/generate"))
            .json(&request_body)
            .send(),
    )
    .await;
    let (output_length, stats, error) = match response {
        Ok(Ok(resp)) if resp.status().is_success() => match resp.json::<Value>().await {
            Ok(body) => (
                body["story"].as_str().map(|s| s.chars().count()),
                body.get("stats").cloned().unwrap_or(Value::Null),
                Value::Null,
            ),
            Err(e) => (None, Value::Null, json!(format!("invalid response: {e}"))),
        },
        Ok(Ok(resp)) => (None, Value::Null, json!(format!("http {}", resp.status()))),
        Ok(Err(e)) => (None, Value::Null, json!(e.to_string())),
        Err(_) => (None, Value::Null, json!("request timeout")),
    };
    let elapsed = started.elapsed().as_secs_f64() * 1000.0;
    task.abort();
    Ok((elapsed, output_length, stats, error))
}

fn telemetry_metrics(samples: &[Value]) -> Value {
    fn collect(samples: &[Value], path: &[&str]) -> Vec<f64> {
        samples
            .iter()
            .filter_map(|s| {
                let mut value = s.get("stats")?.get("inference")?;
                for key in path {
                    value = value.get(*key)?;
                }
                value.as_f64()
            })
            .collect()
    }
    let metric = |path: &[&str]| quantile(&collect(samples, path), 0.5);
    json!({"source":"stats.inference","median_server_first_visible_text_ms":metric(&["durations_ms","server_first_visible_text"]),"median_provider_request_total_ms":metric(&["durations_ms","provider_request_total"]),"median_provider_ttft_ms":metric(&["provider","ttft_ms"]),"median_output_tokens_per_sec":metric(&["provider","output_tokens_per_sec"]),"unknown_when_absent":true})
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn corpus_is_complete() {
        let c = workloads().unwrap();
        assert_eq!(c.len(), 6);
        assert!(c
            .iter()
            .all(|w| !w.id.is_empty() && !w.prompt.is_empty() && !w.stable_context.is_empty()));
        let long = c.iter().find(|w| w.id == "canon-long").unwrap();
        assert!(
            render_prompt(long, Category::WarmPrefix, 1)
                .split_whitespace()
                .count()
                >= 1500
        );
        let continuation = c.iter().find(|w| w.id == "continuation").unwrap();
        assert!(
            render_prompt(continuation, Category::WarmPrefix, 1).contains("Synthetic prior turn")
        );
    }
    #[test]
    fn quantiles_are_deterministic() {
        assert_eq!(quantile(&[10.0, 20.0, 30.0], 0.5), Some(20.0));
        assert_eq!(quantile(&[10.0, 20.0], 0.5), Some(15.0));
        assert_eq!(quantile(&[], 0.95), None);
    }
    #[test]
    fn cold_requires_attestation() {
        let c = workloads().unwrap();
        let mut a = Args {
            provider_url: "x".into(),
            model: "m".into(),
            out: None,
            repeats: 1,
            category: Category::ColdModel,
            deliberation: Deliberation::Off,
            output_budget_mode: OutputBudgetMode::Fixed,
            workload: None,
            temperature: 0.2,
            output_budget: Some(256),
            cold_attestation: None,
            revision: None,
            dry_run: true,
        };
        assert!(manifest(&a, &c).is_err());
        a.cold_attestation = Some("operator confirmed reset".into());
        assert!(manifest(&a, &c).is_err());
        a.workload = Some("canon-short".into());
        a.repeats = 2;
        assert!(manifest(&a, &c).is_err());
    }
}
