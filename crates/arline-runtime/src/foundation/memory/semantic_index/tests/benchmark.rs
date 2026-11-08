use super::*;
#[path = "../../../../../examples/support/process_memory.rs"]
mod process_memory;
use std::{io::Write, time::Duration};

struct Measured {
    provider: Arc<super::super::super::embedding::EmbeddingService>,
    batches: Mutex<Vec<Value>>,
}
impl EmbeddingProvider for Measured {
    async fn embed_batch(
        &self,
        config: BekkoConfig,
        texts: Vec<String>,
    ) -> std::result::Result<EmbeddingBatch, EmbeddingError> {
        let count = texts.len();
        let batch = self.provider.embed_batch(config, texts).await?;
        self.batches
            .lock()
            .unwrap()
            .push(json!({"texts":count,"timings":batch.timings}));
        Ok(batch)
    }
    fn diagnostics(&self) -> RuntimeDiagnostics {
        self.provider.diagnostics()
    }
}
async fn phase(state: &AppState, config: &BekkoConfig, provider: &Measured, size: usize) -> Value {
    let started = Instant::now();
    let identity = provider
        .provider
        .inspect_identity(config.clone())
        .await
        .unwrap();
    let id = enqueue(state, &identity, &scope()).unwrap();
    let result = process_job(state, &id, provider, config.clone(), size)
        .await
        .unwrap();
    // Same cleanup contract as public run_job; no other job is competing in
    // this isolated fixture, so work-queue admission time is not measured.
    provider.provider.unload().await.unwrap();
    json!({"wall_ms":started.elapsed().as_secs_f64()*1000.0,"job":result})
}
fn logical_bytes(state: &AppState) -> u64 {
    let con = state.store.connection().unwrap();
    let pages = con
        .pragma_query_value(None, "page_count", |r| r.get::<_, u64>(0))
        .unwrap();
    pages
        * con
            .pragma_query_value(None, "page_size", |r| r.get::<_, u64>(0))
            .unwrap()
}
fn q(values: &[f64], p: f64) -> f64 {
    let mut sorted = values.to_vec();
    sorted.sort_by(f64::total_cmp);
    sorted[((sorted.len() as f64 * p).ceil() as usize).saturating_sub(1)]
}

#[tokio::test]
#[ignore = "requires local Bekko, ONNX Runtime CPU 1.27.0 and ARLINE_R2_REPORT; run with --test-threads=1"]
async fn native_semantic_index_benchmark() {
    let output = std::env::var("ARLINE_R2_REPORT").expect("set ARLINE_R2_REPORT");
    let mut output = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(output)
        .unwrap();
    let frozen = include_str!("../../../../../tests/fixtures/semantic_index_r2.json");
    let workload: Value = serde_json::from_str(frozen).unwrap();
    let (_dir, state, mut config) = fixture();
    config.model_dir = std::env::var("ARLINE_BEKKO_MODEL_DIR").unwrap().into();
    config.runtime_library = std::env::var("ARLINE_ONNX_RUNTIME").unwrap().into();
    let templates = workload["templates"].as_array().unwrap();
    let count = workload["documents"].as_u64().unwrap() as usize;
    for i in 0..count {
        document(
            &state,
            &format!("doc-{i:04}"),
            &templates[i % templates.len()]
                .as_str()
                .unwrap()
                .replace("{n}", &i.to_string()),
        );
    }
    let size = workload["batch_size"].as_u64().unwrap() as usize;
    let before = process_memory::memory();
    let before_bytes = logical_bytes(&state);
    let provider = Measured {
        provider: state.embeddings.clone(),
        batches: Mutex::new(Vec::new()),
    };
    let initial = phase(&state, &config, &provider, size).await;
    assert_eq!(initial["job"]["status"], "completed");
    assert_eq!(initial["job"]["indexed"], count);
    let initial_batches = provider.batches.lock().unwrap().len();
    let after_initial_bytes = logical_bytes(&state);
    let noop = phase(&state, &config, &provider, size).await;
    assert_eq!(noop["job"]["indexed"], 0);
    assert_eq!(provider.batches.lock().unwrap().len(), initial_batches);
    let edits = workload["incremental_edits"].as_u64().unwrap() as usize;
    for i in 0..edits {
        let id = format!("doc-{i:04}");
        state.store.update("workspace_documents",&id,json!({"content":format!("Retcon revision {i}: the letter is now stored in the archive.")})).unwrap();
        super::super::super::refresh_document(&state, &id).unwrap();
    }
    let incremental = phase(&state, &config, &provider, size).await;
    assert_eq!(incremental["job"]["indexed"], edits);
    let identity = provider
        .provider
        .inspect_identity(config.clone())
        .await
        .unwrap();
    let coverage = index_status(&state, &identity.fingerprint, &scope()).unwrap();
    assert_eq!(coverage.current, count);
    assert_eq!(coverage.stale_vectors, edits);
    let allowed = state
        .store
        .query(
            "SELECT id FROM memory_chunks WHERE project_id='r2' AND semantic_status='active'",
            &[],
        )
        .unwrap()
        .into_iter()
        .map(|row| row["id"].as_str().unwrap().to_owned())
        .collect::<HashSet<_>>();
    let query = provider
        .provider
        .embed_batch(
            config.clone(),
            vec![workload["query"].as_str().unwrap().into()],
        )
        .await
        .unwrap()
        .vectors
        .pop()
        .unwrap();
    let mut search_times = Vec::new();
    for _ in 0..20 {
        let started = Instant::now();
        let result =
            diagnostic_search(&state, &identity.fingerprint, "r2", &allowed, &query, 10).unwrap();
        search_times.push(started.elapsed().as_secs_f64() * 1000.0);
        assert_eq!(result["hits"].as_array().unwrap().len(), 10);
    }
    let after_loaded = process_memory::memory();
    let other = super::super::super::embedding::EmbeddingService::default();
    let contention = other
        .embed_batch(config.clone(), vec!["Another workspace".into()])
        .await
        .unwrap_err();
    assert_eq!(contention.kind, ErrorKind::ResourceBusy);
    provider.provider.unload().await.unwrap();
    config.keep_warm_seconds = 2;
    other
        .embed_batch(config.clone(), vec!["After residency transfer".into()])
        .await
        .unwrap();
    let idle = Instant::now();
    loop {
        let diag = other.diagnostics();
        if !diag.busy && !diag.loaded && !diag.eviction_worker_running {
            break;
        }
        assert!(idle.elapsed() < Duration::from_secs(10));
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    let after_eviction = process_memory::memory();
    let recover_id = enqueue(&state, &identity, &scope()).unwrap();
    state.store.execute("UPDATE semantic_index_jobs SET status='running',owner='stopped-benchmark',lease_until=0 WHERE id=?",&[&recover_id]).unwrap();
    let recovery = Instant::now();
    let reopened = AppState::open(state.runtime_config().unwrap()).unwrap();
    let recovery_ms = recovery.elapsed().as_secs_f64() * 1000.0;
    assert_eq!(
        reopened
            .store
            .query(
                "SELECT status FROM semantic_index_jobs WHERE id=?",
                &[&recover_id]
            )
            .unwrap()[0]["status"],
        "interrupted"
    );
    let batches = provider.batches.lock().unwrap();
    let batch_ms = batches
        .iter()
        .map(|v| v["timings"]["total_ms"].as_f64().unwrap())
        .collect::<Vec<_>>();
    let report = json!({"schema":"arline.semantic-index-r2-benchmark.v1","fixture_sha256":digest(frozen),"fixture":workload,
        "os":std::env::consts::OS,"build":if cfg!(debug_assertions){"debug"}else{"release"},"model":identity,
        "initial":initial,"no_op":noop,"incremental":incremental,"batch_samples":*batches,
        "batch_total_p50_ms":q(&batch_ms,0.5),"batch_total_p95_ms":q(&batch_ms,0.95),
        "initial_chunks_per_second":count as f64*1000./initial["wall_ms"].as_f64().unwrap(),"incremental_chunks_per_second":edits as f64*1000./incremental["wall_ms"].as_f64().unwrap(),
        "logical_database_bytes":{"before":before_bytes,"after_initial":after_initial_bytes,"after_incremental":logical_bytes(&state)},
        "coverage":coverage,"recovery_ms":recovery_ms,"diagnostic_search":{"samples":20,"p50_ms":q(&search_times,0.5),"p95_ms":q(&search_times,0.95),"scope":"controlled fixture allowlist only"},
        "memory":{"before":before,"loaded":after_loaded,"after_eviction":after_eviction},"process_residency":{"limit":1,"second_workspace_error":contention,"transfer_after_unload":true,"idle_seconds":2},
        "limitations":"Storage benchmark, not narrative recall quality. Phase timings include identity validation, database work and explicit session release. Memory counts are for the isolated test process. Linux unqualified."});
    writeln!(output, "{}", serde_json::to_string_pretty(&report).unwrap()).unwrap();
}
