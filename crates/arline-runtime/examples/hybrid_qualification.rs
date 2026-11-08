//! Frozen R3 comparison on isolated narrative fixtures and provisioned artifacts.
use arline_runtime::{
    config::RuntimeConfig,
    foundation::memory::{
        self,
        embedding::BekkoConfig,
        semantic_index::{self, IndexScope},
    },
    router, AppState,
};
use axum::{
    body::{to_bytes, Body},
    http::Request,
};
use clap::Parser;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{fs::OpenOptions, io::Write, path::PathBuf, time::Instant};
use tower::ServiceExt;
#[path = "support/process_memory.rs"]
mod process_memory;
const FIXTURE: &str = include_str!("../tests/fixtures/retrieval_r3.json");
#[derive(Parser)]
struct Args {
    #[arg(long)]
    out: PathBuf,
    #[arg(long)]
    model_dir: PathBuf,
    #[arg(long)]
    runtime: PathBuf,
    #[arg(long,default_value_t=3,value_parser=clap::value_parser!(u32).range(1..=20))]
    repeats: u32,
}
async fn query(state: &AppState, body: &Value) -> Result<Value, Box<dyn std::error::Error>> {
    let response = router(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/memory/query")
                .header("content-type", "application/json")
                .body(Body::from(body.to_string()))?,
        )
        .await?;
    if !response.status().is_success() {
        return Err(format!("retrieval {}", response.status()).into());
    }
    Ok(serde_json::from_slice(
        &to_bytes(response.into_body(), 16 * 1024 * 1024).await?,
    )?)
}
fn percentile(values: &[f64], p: f64) -> f64 {
    let mut v = values.to_vec();
    v.sort_by(f64::total_cmp);
    v[((v.len() as f64 * p).ceil() as usize).saturating_sub(1)]
}
fn metrics(rows: &[Value], relevant: &[Value]) -> Value {
    let first = rows
        .iter()
        .take(10)
        .position(|r| relevant.contains(&r["source_id"]));
    let recall = rows
        .iter()
        .take(5)
        .filter(|r| relevant.contains(&r["source_id"]))
        .count() as f64
        / relevant.len() as f64;
    let dcg = rows
        .iter()
        .take(10)
        .enumerate()
        .filter(|(_, r)| relevant.contains(&r["source_id"]))
        .map(|(i, _)| 1.0 / ((i + 2) as f64).log2())
        .sum::<f64>();
    let ideal = (0..relevant.len().min(10))
        .map(|i| 1.0 / ((i + 2) as f64).log2())
        .sum::<f64>();
    json!({"recall_at_5":recall,"mrr_at_10":first.map_or(0.0,|i|1.0/(i+1) as f64),"ndcg_at_10":dcg/ideal,"selected_ids":rows.iter().map(|r|r["source_id"].clone()).collect::<Vec<_>>(),"unauthorized_selected":rows.iter().filter(|r|r["project_id"]!="r3-benchmark" || !r["branch_id"].is_null()).count()})
}
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse();
    let mut output = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&args.out)?;
    let fixture: Value = serde_json::from_str(FIXTURE)?;
    let temp = tempfile::tempdir()?;
    let mut config = RuntimeConfig::create_default(temp.path().join("config.toml"), temp.path())?;
    config.set(
        "memory.embedding.backend",
        toml::Value::String("native_bekko_onnx".into()),
    )?;
    config.set("memory.embedding.enabled", toml::Value::Boolean(true))?;
    config.set(
        "memory.embedding.model_dir",
        toml::Value::String(args.model_dir.to_string_lossy().into()),
    )?;
    config.set(
        "memory.embedding.runtime_library",
        toml::Value::String(args.runtime.to_string_lossy().into()),
    )?;
    config.set("memory.final_k", toml::Value::Integer(10))?;
    config.set("memory.max_pack_tokens", toml::Value::Integer(8192))?;
    let native = BekkoConfig::from_runtime(&config)?;
    let state = AppState::open(config)?;
    state
        .store
        .insert("projects", json!({"id":"r3-benchmark","name":"R3"}))?;
    for doc in fixture["documents"].as_array().unwrap() {
        let id = doc["id"].as_str().unwrap();
        state.store.insert(
            "workspace_documents",
            json!({"id":id,"project_id":"r3-benchmark","title":id,"content":doc["text"]}),
        )?;
        memory::refresh_document(&state, id)?;
    }
    let before = process_memory::memory();
    let indexed = semantic_index::index_pending(
        state.clone(),
        native,
        IndexScope {
            project_id: Some("r3-benchmark".into()),
            ..Default::default()
        },
        32,
    )
    .await?;
    let after_index = process_memory::memory();
    let mut reports = vec![];
    let mut arm_reports = vec![];
    for arm in ["legacy", "scope_fts", "bekko_only", "hybrid"] {
        {
            let mut cfg = state.config.write().unwrap();
            cfg.set(
                "memory.engine_mode",
                toml::Value::String(if arm == "legacy" { "legacy" } else { "hybrid" }.into()),
            )?;
            cfg.set(
                "memory.embedding.enabled",
                toml::Value::Boolean(matches!(arm, "bekko_only" | "hybrid")),
            )?;
        }
        let mut times = vec![];
        for case in fixture["queries"].as_array().unwrap() {
            let body = json!({"query":case["query"],"project_id":"r3-benchmark","limit":10,"token_budget":8192});
            let _ = query(&state, &body).await?;
            for repeat in 0..args.repeats {
                let started = Instant::now();
                let result = query(&state, &body).await?;
                let elapsed = started.elapsed().as_secs_f64() * 1000.0;
                times.push(elapsed);
                let mut rows = result["selected"].as_array().cloned().unwrap_or_default();
                if arm == "bekko_only" {
                    rows = result["results"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .filter(|r| r["dense_score"].is_number())
                        .cloned()
                        .collect();
                    rows.sort_by(|a, b| {
                        b["dense_score"]
                            .as_f64()
                            .unwrap()
                            .total_cmp(&a["dense_score"].as_f64().unwrap())
                            .then_with(|| a["id"].as_str().cmp(&b["id"].as_str()))
                    });
                    rows.truncate(10);
                }
                reports.push(json!({"arm":arm,"query_id":case["id"],"split":case["split"],"exact":case["exact"]==true,"repeat":repeat,"metrics":metrics(&rows,case["relevant"].as_array().unwrap()),"latency_ms":elapsed,"trace":result["retrieval_trace"],"packed_tokens":result["packed_tokens"]}));
            }
        }
        let mut splits = serde_json::Map::new();
        for split in ["development", "heldout"] {
            let samples = reports
                .iter()
                .filter(|r| r["arm"] == arm && r["split"] == split)
                .collect::<Vec<_>>();
            let avg = |key: &str| {
                samples
                    .iter()
                    .map(|r| r["metrics"][key].as_f64().unwrap())
                    .sum::<f64>()
                    / samples.len() as f64
            };
            splits.insert(split.into(),json!({"recall_at_5":avg("recall_at_5"),"mrr_at_10":avg("mrr_at_10"),"ndcg_at_10":avg("ndcg_at_10"),"unauthorized_selected":samples.iter().map(|r|r["metrics"]["unauthorized_selected"].as_u64().unwrap()).sum::<u64>(),"exact_match_failures":samples.iter().filter(|r|r["exact"]==true && r["metrics"]["recall_at_5"]!=1.0).count()}));
        }
        arm_reports.push(json!({"arm":arm,"latency_p50_ms":percentile(&times,0.5),"latency_p95_ms":percentile(&times,0.95),"splits":splits,"memory":process_memory::memory()}));
    }
    let loaded = process_memory::memory();
    // Outside timed samples: a second AppState must fail open rather than load
    // a second resident model, while explicit indexing may overlap a query.
    let second = AppState::open_index_maintenance(state.runtime_config()?)?;
    let contention = query(
        &second,
        &json!({"query":"Mara key","project_id":"r3-benchmark"}),
    )
    .await?;
    if contention["dense_fallback_reason"] != "resource_busy" {
        return Err("second AppState did not report residency contention".into());
    }
    let native = BekkoConfig::from_runtime(&state.runtime_config()?)?;
    let concurrent_body = json!({"query":"Mara key","project_id":"r3-benchmark"});
    let (concurrent_query, concurrent_index) = tokio::join!(
        query(&state, &concurrent_body),
        semantic_index::index_pending(
            state.clone(),
            native,
            IndexScope {
                project_id: Some("r3-benchmark".into()),
                ..Default::default()
            },
            32
        )
    );
    let concurrent_query = concurrent_query?;
    let concurrent_index = concurrent_index?;
    if concurrent_index["indexed"] != 0 {
        return Err("explicit no-op concurrency probe unexpectedly indexed passages".into());
    }
    let resource_probes = json!({"second_appstate_fallback":contention["dense_fallback_reason"],"second_appstate_selected":contention["selected"].as_array().map(Vec::len),"concurrent_index_status":concurrent_index["status"],"concurrent_indexed":concurrent_index["indexed"],"concurrent_query_selected":concurrent_query["selected"].as_array().map(Vec::len)});
    state.embeddings.unload().await?;
    tokio::time::sleep(std::time::Duration::from_millis(200)).await;
    let unloaded = process_memory::memory();
    let legacy = &arm_reports[0]["splits"]["heldout"];
    let hybrid = &arm_reports[3]["splits"]["heldout"];
    let gate = hybrid["ndcg_at_10"].as_f64() > legacy["ndcg_at_10"].as_f64()
        && hybrid["exact_match_failures"] == 0
        && hybrid["unauthorized_selected"] == 0;
    let report = json!({"schema":"arline.hybrid-qualification.v1","fixture_sha256":format!("{:x}",Sha256::digest(FIXTURE)),"build":if cfg!(debug_assertions){"debug"}else{"release"},"os":std::env::consts::OS,"documents":fixture["documents"].as_array().unwrap().len(),"repeats":args.repeats,"index_job":indexed,"arms":arm_reports,"samples":reports,"resource_probes":resource_probes,"memory":{"before":before,"after_index":after_index,"loaded":loaded,"after_explicit_unload":unloaded},"heldout_relevance_gate_passed":gate,"limitations":"Authored synthetic 24-document corpus, 6 development and 10 held-out queries. Bekko-only is diagnostic rank extraction from the same eligible hybrid candidate pool; latency includes hybrid orchestration, not isolated semantic search. No real-manuscript or Linux qualification. Writer tests use mock writer services."});
    writeln!(output, "{}", serde_json::to_string_pretty(&report)?)?;
    println!(
        "Saved {}; held-out relevance gate: {gate}",
        args.out.display()
    );
    Ok(())
}
