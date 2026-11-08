//! R0 query-path baseline: isolated synthetic chunks, no writer/model/network.
use arline_runtime::{config::RuntimeConfig, router, AppState};
use axum::{
    body::{to_bytes, Body},
    http::Request,
};
use clap::Parser;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{fs::OpenOptions, io::Write, path::PathBuf, time::Instant};
use tower::ServiceExt;

const FIXTURE: &str = include_str!("../tests/fixtures/retrieval_r0.json");

#[derive(Parser)]
struct Args {
    #[arg(long)]
    out: PathBuf,
    #[arg(long, default_value_t = 20, value_parser = clap::value_parser!(u32).range(1..=100))]
    repeats: u32,
}

async fn query(state: &AppState, text: &str) -> Result<Value, Box<dyn std::error::Error>> {
    let response = router(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/memory/query")
                .header("content-type", "application/json")
                .body(Body::from(
                    json!({"query":text,"limit":12,"token_budget":4096}).to_string(),
                ))?,
        )
        .await?;
    if !response.status().is_success() {
        return Err(format!("retrieval returned {}", response.status()).into());
    }
    Ok(serde_json::from_slice(
        &to_bytes(response.into_body(), 8 * 1024 * 1024).await?,
    )?)
}

fn percentile(values: &mut [f64], p: f64) -> f64 {
    values.sort_by(f64::total_cmp);
    values[((values.len() as f64 * p).ceil() as usize).saturating_sub(1)]
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse();
    let fixture: Value = serde_json::from_str(FIXTURE)?;
    let temp = tempfile::tempdir()?;
    let mut config = RuntimeConfig::create_default(temp.path().join("config.toml"), temp.path())?;
    // Never contact a resident generation or embedding service.
    config.set("memory.dense_enabled", toml::Value::Boolean(false))?;
    config.set("memory.embedding.enabled", toml::Value::Boolean(false))?;
    let state = AppState::open(config)?;
    {
        let connection = state.store.connection()?;
        let now = "2026-11-05T00:00:00Z";
        let mut insert = connection.prepare("INSERT INTO memory_chunks(id,source_type,source_id,text,branch_id,importance,checksum,created_at,updated_at) VALUES(?,'external_note',?,?,?,?,?,?,?)")?;
        for row in fixture["chunks"].as_array().unwrap() {
            let id = row["id"].as_str().unwrap();
            insert.execute(rusqlite::params![
                id,
                id,
                row["text"].as_str().unwrap(),
                Option::<String>::None,
                0.5,
                id,
                now,
                now
            ])?;
        }
        for i in 0..fixture["distractors"]["count"].as_u64().unwrap() {
            let id = format!("distractor-{i:04}");
            insert.execute(rusqlite::params![
                id,
                id,
                fixture["distractors"]["text"].as_str().unwrap(),
                fixture["distractors"]["branch_id"].as_str().unwrap(),
                1.0,
                id,
                now,
                now
            ])?;
        }
    }
    let mut reports = Vec::new();
    for case in fixture["queries"].as_array().unwrap() {
        let text = case["query"].as_str().unwrap();
        let relevant = case["relevant"].as_array().unwrap();
        let _ = query(&state, text).await?; // one untimed warm-up per probe
        let mut times = Vec::new();
        let mut samples = Vec::new();
        for _ in 0..args.repeats {
            let started = Instant::now();
            let result = query(&state, text).await?;
            times.push(started.elapsed().as_secs_f64() * 1000.0);
            let selected = result["selected"]
                .as_array()
                .ok_or("missing selected evidence")?;
            let first = selected
                .iter()
                .take(10)
                .position(|row| relevant.contains(&row["source_id"]));
            let hits = selected
                .iter()
                .take(5)
                .filter(|row| relevant.contains(&row["source_id"]))
                .count();
            let dcg: f64 = selected
                .iter()
                .take(10)
                .enumerate()
                .filter(|(_, row)| relevant.contains(&row["source_id"]))
                .map(|(i, _)| 1.0 / ((i + 2) as f64).log2())
                .sum();
            let ideal: f64 = (0..relevant.len().min(10))
                .map(|i| 1.0 / ((i + 2) as f64).log2())
                .sum();
            samples.push(json!({"recall_at_5":hits as f64/relevant.len() as f64,
                "mrr_at_10":first.map_or(0.0, |i| 1.0/(i+1) as f64),"ndcg_at_10":dcg/ideal,
                "unauthorized_selected":selected.iter().filter(|row| !row["branch_id"].is_null()).count(),
                "selected_ids":selected.iter().map(|row|row["source_id"].clone()).collect::<Vec<_>>(),
                "candidates":result["results"].as_array().map(Vec::len),"packed_tokens":result["packed_tokens"]}));
        }
        reports.push(json!({"id":case["id"],"latency_p50_ms":percentile(&mut times,0.5),
            "latency_p95_ms":percentile(&mut times,0.95),"latency_samples_ms":times,"samples":samples}));
    }
    let db_bytes = std::fs::metadata(&state.store.path)?.len();
    let report = json!({"schema":"arline.retrieval-baseline.v1","fixture_sha256":format!("{:x}",Sha256::digest(FIXTURE)),
        "split":fixture["split"],"backend":"native-fts5+structured","os":std::env::consts::OS,
        "arch":std::env::consts::ARCH,"build":if cfg!(debug_assertions){"debug"}else{"release"},
        "synthetic_chunks":523,"warmup_queries_per_case":1,"repeats":args.repeats,
        "timing_scope":"in-process router + scope + packing + persisted retrieval trace; excludes fixture setup",
        "database_main_file_bytes":db_bytes,"ram_bytes":Value::Null,"indexing_throughput":Value::Null,
        "limitations":"Three synthetic development probes; no model, writer, held-out evaluation, or cross-platform qualification. Database size excludes WAL. No performance-improvement claim.",
        "queries":reports});
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&args.out)?;
    writeln!(output, "{}", serde_json::to_string_pretty(&report)?)?;
    println!("Saved {}", args.out.display());
    Ok(())
}
