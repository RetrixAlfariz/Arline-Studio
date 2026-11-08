//! Explicit local-only R1 qualification. Never opens an application database.
use arline_runtime::{
    config::RuntimeConfig,
    foundation::memory::embedding::{BekkoConfig, EmbeddingProvider, EmbeddingService},
};
use clap::Parser;
use serde_json::{json, Value};
use std::{
    fs::OpenOptions,
    io::Write,
    path::PathBuf,
    time::{Duration, Instant},
};

#[derive(Parser)]
struct Args {
    #[arg(long)]
    model_dir: PathBuf,
    #[arg(long)]
    runtime_library: PathBuf,
    #[arg(long)]
    out: PathBuf,
    #[arg(long,default_value_t=20,value_parser=clap::value_parser!(u32).range(2..=100))]
    repeats: u32,
    #[arg(long,default_value_t=2,value_parser=clap::value_parser!(u64).range(1..=300))]
    eviction_seconds: u64,
}
fn quantile(values: &[f64], p: f64) -> f64 {
    let mut v = values.to_vec();
    v.sort_by(f64::total_cmp);
    v[((v.len() as f64 * p).ceil() as usize).saturating_sub(1)]
}

#[path = "support/process_memory.rs"]
mod process_memory;
use process_memory::memory;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse();
    // Reserve output before expensive qualification; never overwrite evidence.
    let mut out = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&args.out)?;
    let temp = tempfile::tempdir()?;
    let mut runtime = RuntimeConfig::create_default(temp.path().join("config.toml"), temp.path())?;
    for (key, value) in [
        ("backend", "native_bekko_onnx".to_owned()),
        ("model_dir", args.model_dir.to_string_lossy().into_owned()),
        (
            "runtime_library",
            args.runtime_library.to_string_lossy().into_owned(),
        ),
    ] {
        runtime.set(
            &format!("memory.embedding.{key}"),
            toml::Value::String(value),
        )?;
    }
    runtime.set("memory.embedding.enabled", toml::Value::Boolean(true))?;
    runtime.set(
        "memory.embedding.keep_warm_seconds",
        toml::Value::Integer(args.eviction_seconds as i64),
    )?;
    let config = BekkoConfig::from_runtime(&runtime)?;
    let service = EmbeddingService::default();
    let reference: Value =
        serde_json::from_str(include_str!("../tests/fixtures/bekko-reference.json"))?;
    let texts = reference["cases"]
        .as_array()
        .unwrap()
        .iter()
        .map(|c| c["text"].as_str().unwrap().to_owned())
        .collect::<Vec<_>>();
    let before = memory();
    let cold = service.embed_batch(config.clone(), texts.clone()).await?;
    let after_load = memory();
    let mut min_cosine = 1.0_f64;
    let mut max_component_error = 0.0_f64;
    for (vector, case) in cold
        .vectors
        .iter()
        .zip(reference["cases"].as_array().unwrap())
    {
        let expected = case["vector"].as_array().unwrap();
        let dot = vector
            .iter()
            .zip(expected)
            .map(|(a, b)| f64::from(*a) * b.as_f64().unwrap())
            .sum::<f64>();
        let norm = vector
            .iter()
            .map(|a| f64::from(*a).powi(2))
            .sum::<f64>()
            .sqrt();
        let refnorm = expected
            .iter()
            .map(|a| a.as_f64().unwrap().powi(2))
            .sum::<f64>()
            .sqrt();
        min_cosine = min_cosine.min(dot / (norm * refnorm));
        max_component_error = vector
            .iter()
            .zip(expected)
            .map(|(a, b)| (f64::from(*a) - b.as_f64().unwrap()).abs())
            .fold(max_component_error, f64::max);
    }
    if min_cosine < reference["cosine_min"].as_f64().unwrap()
        || max_component_error > reference["max_component_error"].as_f64().unwrap()
    {
        return Err("reference-vector parity failed".into());
    }
    let mut warm_total = Vec::new();
    let mut warm_infer = Vec::new();
    let mut hash_ms = Vec::new();
    for _ in 0..args.repeats {
        let batch = service
            .embed_batch(config.clone(), vec![texts[0].clone()])
            .await?;
        if !batch.timings.reused_session {
            return Err(
                "session expired during warm measurements; increase --eviction-seconds".into(),
            );
        }
        warm_total.push(batch.timings.total_ms);
        warm_infer.push(batch.timings.inference_ms);
        hash_ms.push(batch.timings.artifact_validation_ms);
    }
    let batch_texts = (0..16)
        .map(|i| texts[i % texts.len()].clone())
        .collect::<Vec<_>>();
    let batch = service.embed_batch(config.clone(), batch_texts).await?;
    // Missing-provider detection measured separately with an independent cache.
    let fallback = EmbeddingService::default();
    let mut missing = config.clone();
    missing.model_dir = temp.path().join("missing");
    let mut missing_ms = Vec::new();
    for _ in 0..args.repeats {
        let started = Instant::now();
        let failure = fallback
            .embed_batch(missing.clone(), vec!["probe".into()])
            .await
            .unwrap_err();
        assert_eq!(failure.fallback, "fts5+structured");
        missing_ms.push(started.elapsed().as_secs_f64() * 1000.0);
    }
    let idle_started = Instant::now();
    let settled = loop {
        let diagnostic = service.diagnostics();
        // A busy snapshot has unknown fields, not zero loads/an empty cache.
        // In particular, model destruction holds the cache lock during eviction.
        if !diagnostic.busy && !diagnostic.loaded && !diagnostic.eviction_worker_running {
            break diagnostic;
        }
        if idle_started.elapsed() > Duration::from_secs(args.eviction_seconds + 10) {
            return Err("idle eviction timed out".into());
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    };
    let after_eviction = memory();
    let idle_wait_seconds = idle_started.elapsed().as_secs_f64();
    let loads_before = settled.successful_loads;
    let (left, right) = tokio::join!(
        service.embed_batch(config.clone(), vec![texts[0].clone()]),
        service.embed_batch(config.clone(), vec![texts[1].clone()])
    );
    let (left, right) = (left?, right?);
    let after_reload = loop {
        let diagnostic = service.diagnostics();
        if !diagnostic.busy {
            break diagnostic;
        }
        tokio::time::sleep(Duration::from_millis(5)).await;
    };
    if after_reload.successful_loads != loads_before + 1 {
        return Err("concurrent reload created duplicate sessions".into());
    }
    let mut changed = config.clone();
    changed.threads = 1;
    let changed_result = service.embed_batch(changed, vec![texts[0].clone()]).await?;
    assert!(!changed_result.timings.reused_session);
    assert_eq!(
        changed_result.identity.fingerprint,
        cold.identity.fingerprint
    );
    let report = json!({"schema":"arline.bekko-r1-qualification.v1","os":std::env::consts::OS,"arch":std::env::consts::ARCH,
        "build":if cfg!(debug_assertions){"debug"}else{"release"},"runtime_version":"1.27.0","threads":2,"max_tokens":512,
        "identity":cold.identity,"reference":{"min_cosine":min_cosine,"max_component_error":max_component_error,"cosine_tolerance_min":reference["cosine_min"],"component_tolerance_max":reference["max_component_error"],"cases":texts.len()},
        "cold":cold.timings,"warm":{"samples":args.repeats,"total_p50_ms":quantile(&warm_total,0.5),"total_p95_ms":quantile(&warm_total,0.95),"inference_p50_ms":quantile(&warm_infer,0.5),"inference_p95_ms":quantile(&warm_infer,0.95),"artifact_and_runtime_validation_p50_ms":quantile(&hash_ms,0.5)},
        "batch":{"texts":16,"timings":batch.timings,"texts_per_second_end_to_end":16000.0/batch.timings.total_ms,"texts_per_second_inference_only":16000.0/batch.timings.inference_ms},
        "memory":{"before":before,"after_load":after_load,"after_eviction":after_eviction,"after_reload":memory()},
        "eviction":{"configured_seconds":args.eviction_seconds,"remaining_wait_observed_seconds":idle_wait_seconds,"worker_stopped":true,"concurrent_reload_single_load":true,"reload_timings":[left.timings,right.timings],"thread_change_reloaded":true},
        "missing_provider_detection":{"p50_ms":quantile(&missing_ms,0.5),"p95_ms":quantile(&missing_ms,0.95),"fallback":"fts5+structured","scope":"native provider missing-artifact error; not a retrieval benchmark"},
        "diagnostics":service.diagnostics(),"linux_qualified":false});
    writeln!(out, "{}", serde_json::to_string_pretty(&report)?)?;
    println!("Qualification saved to {}", args.out.display());
    Ok(())
}
